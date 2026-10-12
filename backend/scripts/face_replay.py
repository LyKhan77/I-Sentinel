"""Replay offline event absensi: bandingkan keputusan `legacy` (tercatat) dan `strict` (match_strict).

Menguji ulang aturan ambang/margin pada crop event nyata, bukan waktu jendela. Jalankan di
container `api` dengan CPU dibatasi dan beri tahu user lebih dulu (lihat memori
`limit-cpu-for-server-diagnostics`):

    docker compose -f docker/compose.yml exec api \
        nice -n 19 taskset -c 0-3 python -m scripts.face_replay --days 14 --limit 200

Keluaran hanya ID event dan ID karyawan — tanpa nama, tanpa embedding. Syarat lolos spec §7.1:
`same_pct` ≥ 98 dan `flipped` 0.

Batas CPU: onnxruntime memasang afinitas threadnya sendiri, jadi `taskset` dan `OMP_NUM_THREADS` TIDAK
membatasinya (percobaan 2026-10-09: ±1600% CPU walau `taskset -c 0-3`). Skrip membatasi sesi onnxruntime
lewat `--threads` (bawaan 2) dan berhenti sendiri setelah `--max-seconds` (bawaan 300) sambil tetap
mencetak ringkasan; mulai dengan `--limit` kecil dan pantau `docker stats` beberapa detik pertama.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.event import Event
from app.services import face, face_policy

CATEGORIES = ("same", "flipped", "lost", "ambiguous", "gained", "both_none")
REPLAY_PASS_SAME_PCT = 98.0


def classify(legacy_employee_id: int | None, strict) -> str:
    """Kategori satu event: keputusan `legacy` tercatat vs keputusan `strict` pada crop yang sama."""
    if legacy_employee_id is not None:
        if strict.employee_id == legacy_employee_id:
            return "same"
        if strict.employee_id is not None:
            return "flipped"
        return "ambiguous" if strict.reason == "ambiguous" else "lost"
    return "gained" if strict.employee_id is not None else "both_none"


def cap_onnx_threads(threads: int) -> bool:
    """Paksa semua sesi onnxruntime memakai `threads` thread intra-op (inter-op 1, tanpa spin).

    Bila pemanggil tak memberi `sess_options` (cara insightface), dibuat baru; bila memberi, diubah.
    Mengembalikan False bila onnxruntime tidak terpasang.
    """
    try:
        import onnxruntime as ort
    except ImportError:
        return False
    original = ort.InferenceSession.__init__

    def limited(self, path_or_bytes, sess_options=None, *args, **kwargs):
        options = sess_options if sess_options is not None else ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        original(self, path_or_bytes, options, *args, **kwargs)

    ort.InferenceSession.__init__ = limited
    return True


def summarize(rows: list[dict]) -> dict:
    """Hitung kategori, `same_pct` atas event yang dikenali legacy, dan daftar event_id menonjol."""
    counts = dict.fromkeys(CATEGORIES, 0)
    flagged: dict[str, list[str]] = {key: [] for key in ("flipped", "ambiguous", "gained")}
    legacy_recognized = same = 0
    for row in rows:
        category = classify(row["legacy_employee_id"], row["strict"])
        counts[category] += 1
        if row["legacy_employee_id"] is not None:
            legacy_recognized += 1
            same += category == "same"
        if category in flagged:
            flagged[category].append(row["event_id"])
    return {
        "counts": counts,
        "legacy_recognized": legacy_recognized,
        "same_pct": round(100.0 * same / legacy_recognized, 1) if legacy_recognized else 0.0,
        **flagged,
    }


def _candidates(db, days: int, limit: int):
    """Event absensi ber-crop_path dalam `days` terakhir.

    Filter waktu di Python: SQLite (tes) menyimpan datetime tanpa zona, Postgres (server) aware.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (db.query(Event).filter(Event.type == "attendance")
            .order_by(Event.ts_event.desc()).limit(limit).all())
    selected = []
    for ev in rows:
        crop = (ev.payload or {}).get("crop_path")
        ts = ev.ts_event if ev.ts_event.tzinfo else ev.ts_event.replace(tzinfo=timezone.utc)
        if crop and ts >= since:
            selected.append((ev, crop))
    return selected


def _print_report(rows: list[dict], summary: dict, scanned: int, no_face: int = 0,
                  stopped_after: float | None = None) -> None:
    counts = summary["counts"]
    print(f"event absensi ber-crop dalam jendela: {scanned}, direplay: {len(rows)}")
    print(f"tanpa wajah: {no_face}")
    if stopped_after is not None:
        print(f"dihentikan: batas waktu {stopped_after:g} dtk tercapai; ringkasan hanya untuk yang sempat diproses")
    print("kategori: " + ", ".join(f"{key}={counts[key]}" for key in CATEGORIES))
    print(f"same_pct: {summary['same_pct']}% dari {summary['legacy_recognized']} event yang dikenali legacy")
    for row in rows:
        category = classify(row["legacy_employee_id"], row["strict"])
        if category in ("flipped", "ambiguous", "gained"):
            print(f"{category}: event={row['event_id']} legacy={row['legacy_employee_id']} "
                  f"strict={row['strict'].employee_id} reason={row['strict'].reason} "
                  f"margin={row['strict'].margin}")
    verdict = "lolos" if summary["same_pct"] >= REPLAY_PASS_SAME_PCT and not summary["flipped"] \
        else "belum lolos"
    print(f"syarat spec §7.1 (same_pct >= {REPLAY_PASS_SAME_PCT} dan flipped 0): {verdict}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay offline keputusan absensi (legacy vs strict).")
    parser.add_argument("--days", type=int, default=14, help="jendela event ke belakang (hari)")
    parser.add_argument("--limit", type=int, default=200, help="maksimum event diperiksa")
    parser.add_argument("--sleep", type=float, default=0.2, help="jeda antar crop (detik, pembatas CPU)")
    parser.add_argument("--threads", type=int, default=2, help="thread intra-op onnxruntime (pembatas CPU)")
    parser.add_argument("--max-seconds", type=float, default=300.0,
                        help="berhenti sendiri setelah sekian detik dan tetap mencetak ringkasan")
    args = parser.parse_args(argv)

    # dibatasi sebelum model dimuat (onnxruntime membaca OMP saat import/init)
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    cap_onnx_threads(args.threads)

    db = SessionLocal()
    try:
        selected = _candidates(db, args.days, args.limit)
        face.refresh_gallery(db)
        policy = face_policy.load(db)
        print(f"kebijakan: ambang {policy.match_threshold} margin {policy.match_margin}")
        rows: list[dict] = []
        no_face = 0
        started = time.monotonic()
        stopped_after = None
        for done, (ev, crop) in enumerate(selected, start=1):
            if time.monotonic() - started >= args.max_seconds:
                stopped_after = args.max_seconds
                break
            path = Path(settings.storage_root) / crop
            try:
                faces = face.engine.embed(str(path))
            except RuntimeError as exc:
                print(f"model wajah tidak tersedia: {exc}", file=sys.stderr)
                return 2
            if not faces:
                no_face += 1
                print(f"event={ev.event_id} dilewati: tidak ada wajah di crop", flush=True)
                continue
            best = face._best_face(faces)
            rows.append({
                "event_id": ev.event_id,
                "legacy_employee_id": (ev.payload or {}).get("employee_id"),
                "strict": face.match_strict(best.vector, None, policy),
            })
            if done % 20 == 0:
                print(f"... {done}/{len(selected)} crop diproses", flush=True)
            time.sleep(max(0.0, args.sleep))
        _print_report(rows, summarize(rows), len(selected), no_face, stopped_after)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
