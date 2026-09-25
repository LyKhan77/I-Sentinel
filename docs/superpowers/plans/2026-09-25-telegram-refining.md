# Telegram Refining (feedback lapangan) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menerapkan 5 feedback uji lapangan Telegram: rate-limit per orang (critical tanpa batas, lainnya 2 menit), caption rapi (HTML, tipe berbahasa Inggris), label snapshot = jenis kejadian / nama karyawan, nama zona di Inbox, dan tautan "Atur zona" menggantikan Reset override.

**Architecture:** Perubahan kecil di alur yang sudah ada: `alerting.should_alert` (kunci rate-limit + jendela per severity), `telegram.format_caption`/`deliver` (`parse_mode=HTML`), `vision/recorder._draw_track_box` (label tipe), `services/annotate.py` + `attendance.handle_face_event` (label nama/Unknown di snapshot absensi, Pillow), `EventsPage` (peta nama zona), `DetectionPage` + `ZonesPage` (tautan + parameter `camera`).

**Tech Stack:** FastAPI/SQLAlchemy/Pydantic v2, Pillow (sudah terpasang), OpenCV di vision, React 19 + Carbon, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-25-telegram-alerts-design.md` (fitur dasar) + keputusan feedback di bawah (disetujui user 2026-09-25, desain in-chat).

## Keputusan feedback (user, 2026-09-25)

| # | Keputusan |
|---|---|
| F1 | Rate-limit **per orang**: kunci kamera + zona + tipe alert + `track_id`. Severity **critical tanpa batas**; severity lain (warning, info — termasuk wajah tidak dikenal) **2 menit**. Absensi tercatat tetap tanpa batas. `zone.rate_limit_min` tidak dibaca lagi. |
| F2 | Caption per baris, judul tebal **bahasa Inggris** (`INTRUSION`, `LOITERING`, `RUNNING`, `ATTENDANCE — CHECK IN/OUT`, `UNKNOWN FACE`, tipe baru → `TYPE` huruf besar), label detail **Indonesia** (Kamera, Zona, Waktu, Level, Nama), tautan klip di akhir. |
| F3 | Tombol **Reset override** di Deteksi & Model dihapus → tautan **"Atur zona →"** ke Zona Deteksi dengan kamera itu terpilih. |
| F4 | Inbox menampilkan **nama zona**, bukan angka. |
| F5 | Label snapshot: behavior → **jenis kejadian** (bukan `ID n`); absensi → **nama karyawan** atau **Unknown** (ditulis backend setelah pencocokan). Live View tidak berubah. |

## Global Constraints

- Branch `feat/telegram-alerts` (sudah di-push, HEAD `0b4724b`); lanjutkan di branch yang sama.
- **Tanpa AI attribution** di commit/kode/docs (`AGENTS.md` §9).
- Tanpa dependensi baru, tanpa migrasi DB. Token bot tidak pernah di log/response/output (aturan fitur Telegram tetap berlaku).
- Pipeline wajah vision (`face_worker.py`) **tidak diubah**; label nama absensi ditulis backend.
- Semua string UI lewat `i18n.tsx` (`id` + `en`). Mobile 390 px tanpa overflow.
- Setiap task: commit Conventional Commits + satu bullet di `CHANGELOG.md` bagian `### Integrasi bot Telegram (2026-09-25)` (tambahkan di akhir bagian itu).
- Baseline `feat/telegram-alerts` @ `0b4724b`: backend **406 passed**; vision **204 passed, 3 deselected**; frontend **137 passed**; build 0; lint = set rule+file lama.
- **Eksekutor berhenti setelah `git push`** (diizinkan). Deploy (restart API **dan** vision-node) + uji lapangan dikerjakan sesi perencana.

## Deviasi / catatan desain

1. Kolom rata (`Kamera : …`) di preview tidak bisa rata di Telegram (font proporsional) → dipakai `<b>Kamera</b>: …` per baris; tampilan tetap satu data per baris.
2. Caption tidak lagi dipotong di akhir (memotong string HTML bisa merusak tag → Telegram 400). Setiap nilai dibatasi panjangnya sebelum di-escape, sehingga total pasti < 1024.

## Review Focus

1. **Dua orang berbeda di zona & menit yang sama** → dua alert terkirim. Tes: Task 1 `test_two_people_same_zone_both_sent`.
2. **Zona critical** → tidak pernah `rate_limited`, walau orang yang sama. Tes: Task 1 `test_critical_never_rate_limited`.
3. **Nama kamera/zona/karyawan mengandung `<`, `&`** → caption tetap valid HTML (di-escape). Tes: Task 2 `test_caption_escapes_html`.
4. **Snapshot absensi hilang/rusak** → pencocokan & absensi tetap tercatat (anotasi best-effort). Tes: Task 3 `test_annotate_snapshot_missing_file_is_noop`.
5. **Zona yang sudah dihapus** di Inbox → tampil `#id`, tidak crash. Tes: Task 4 `inbox shows zone names`.

---

### Task 1: Rate-limit per orang + jendela per severity

**Files:**
- Modify: `backend/app/services/alerting.py` (`should_alert`, konstanta)
- Modify: `backend/app/models/zone.py:16` (komentar `rate_limit_min` deprecated)
- Test: `backend/tests/test_alerting.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `alerting.RATE_LIMIT_MIN: dict[str, int] = {"critical": 0}`, `alerting.DEFAULT_RATE_LIMIT_MIN = 2`; kunci rate-limit = `(camera_id, zone_id, alert_type(event), payload.track_id)`.

- [ ] **Step 1: Ubah/tambah tes (gagal)**

Di `backend/tests/test_alerting.py`:
- Helper `_event` menerima `track=None`: bila tidak `None`, `payload = {**(payload or {}), "track_id": track}`.
- Ganti tes rate-limit behavior yang lama (yang memakai menit 2 dan 6 dengan jendela 5) dengan:

```python
def test_same_person_rate_limited_for_two_minutes(db, queued):
    cam, zone = _zone(db, INTRUSION_ON)
    first = alerting.handle(db, _event(db, cam, zone, track=7), now=NOW)
    again = alerting.handle(db, _event(db, cam, zone, track=7), now=NOW + timedelta(seconds=90))
    later = alerting.handle(db, _event(db, cam, zone, track=7), now=NOW + timedelta(seconds=150))
    assert (first.status, again.status, later.status) == ("queued", "rate_limited", "queued")


def test_two_people_same_zone_both_sent(db, queued):
    cam, zone = _zone(db, INTRUSION_ON)
    a = alerting.handle(db, _event(db, cam, zone, track=1), now=NOW)
    b = alerting.handle(db, _event(db, cam, zone, track=2), now=NOW + timedelta(seconds=5))
    assert (a.status, b.status) == ("queued", "queued") and len(queued) == 2


def test_critical_never_rate_limited(db, queued):
    cam, zone = _zone(db, INTRUSION_ON)
    for i in range(3):
        ev = _event(db, cam, zone, track=7, severity="critical")
        assert alerting.handle(db, ev, now=NOW + timedelta(seconds=i)).status == "queued"


def test_unknown_face_rate_limited_per_track(db, queued):
    cam, zone = _zone(db, GATE_ON, type="attendance", direction="entry")

    def unknown(track, sec):
        ev = _event(db, cam, zone, type="attendance", severity="info", track=track,
                    payload={"match_reason": "no_match"})
        return alerting.handle(db, ev, now=NOW + timedelta(seconds=sec)).status

    assert [unknown(1, 0), unknown(1, 30), unknown(2, 40)] == ["queued", "rate_limited", "queued"]
```

- Tes lama `test_unknown_face_rate_limit_separate_from_matched` / tes lain yang mengandalkan jendela 5 menit: sesuaikan waktu ke jendela 2 menit (mis. `minutes=1` → tetap di dalam jendela, `minutes=3` → di luar) tanpa melemahkan assertion; sebutkan di ringkasan.

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_alerting.py -q`
Expected: FAIL — `test_two_people_same_zone_both_sent` (orang kedua `rate_limited`), `test_critical_never_rate_limited`.

- [ ] **Step 3: Implementasi**

`backend/app/services/alerting.py`:
- Konstanta di bawah `logger`:

```python
# F1 (feedback lapangan): per orang; critical tak pernah ditahan, severity lain 2 menit.
RATE_LIMIT_MIN = {"critical": 0}
DEFAULT_RATE_LIMIT_MIN = 2


def _track(event):
    return (event.payload or {}).get("track_id")
```

- Di `should_alert`, ganti blok rate-limit (dari `cutoff = …` sampai `return False, "rate_limited"`) dengan:

```python
    window = RATE_LIMIT_MIN.get(event.severity, DEFAULT_RATE_LIMIT_MIN)
    if window <= 0:
        return True, ""
    cutoff = now - timedelta(minutes=window)
    recent = (
        db.query(Alert)
        .filter(
            Alert.camera_id == event.camera_id,
            Alert.zone_id == event.zone_id,
            Alert.type == alert_type(event),
            Alert.created_at > cutoff,
            Alert.status != "rate_limited",
        )
        .all()
    )
    # kunci per orang: track lain di zona yang sama tidak ikut tertahan
    track = _track(event)
    if any(a.event is not None and _track(a.event) == track for a in recent):
        return False, "rate_limited"
    return True, ""
```

(Pertahankan filter `status != "rate_limited"` yang sudah ada di kode saat ini bila bentuknya berbeda; tujuannya sama.)

`backend/app/models/zone.py:16` — komentar: `# deprecated: rate-limit Telegram kini per orang + per severity (alerting.RATE_LIMIT_MIN)`.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`
Expected: semua passed.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Feedback F1: rate-limit per orang**: kunci kamera + zona + tipe + `track_id` (orang berbeda selalu dapat alert),
  severity critical tanpa batas, lainnya 2 menit (dulu per zona 5 menit — orang kedua / kejadian penting ikut
  tertahan). `zone.rate_limit_min` deprecated. Backend **<angka> passed**.
```

```bash
git add backend/app/services/alerting.py backend/app/models/zone.py backend/tests/test_alerting.py CHANGELOG.md
git commit -m "feat(alert): rate-limit Telegram per orang, critical tanpa batas, lainnya 2 menit"
```

---

### Task 2: Caption rapi (HTML) + `parse_mode`

**Files:**
- Modify: `backend/app/services/telegram.py` (`format_caption`, `deliver`, konstanta label)
- Test: `backend/tests/test_telegram.py`, `backend/tests/test_alert_dispatcher.py` (bila memeriksa teks caption)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `format_caption(event, camera_name, zone_name, app_url, tz=None) -> str` (HTML Telegram); `deliver(...)` mengirim `parse_mode="HTML"` pada `sendPhoto` dan `sendMessage`; `TYPE_TITLE = {"intrusion": "INTRUSION", "loitering": "LOITERING", "running": "RUNNING"}`.

- [ ] **Step 1: Ganti tes caption (gagal)**

Di `backend/tests/test_telegram.py`, **ganti semua tes `format_caption` yang ada** dengan:

```python
def test_caption_behavior_layout():
    text = telegram.format_caption(_event(), "Lorong Server", "Lorong-15", "http://10.0.0.1:5173", tz=WIB)
    assert text.splitlines() == [
        "🚨 <b>INTRUSION</b>",
        "",
        "<b>Kamera</b>: Lorong Server",
        "<b>Zona</b>: Lorong-15",
        "<b>Waktu</b>: 25 Sep 2026 11:42:07 WIB",
        "<b>Level</b>: WARNING",
        "",
        "🎥 Lihat klip: http://10.0.0.1:5173/events?event=1234",
    ]


def test_caption_attendance_check_in_out_and_unknown():
    matched = _event(type="attendance", severity="info", payload={
        "match_reason": "matched", "direction": "exit", "employee_name": "Budi Santoso"})
    lines = telegram.format_caption(matched, "Receptionist", "Gerbang Lobi", None, tz=WIB).splitlines()
    assert lines[:4] == ["✅ <b>ATTENDANCE — CHECK OUT</b>", "", "<b>Nama</b>: Budi Santoso",
                         "<b>Kamera</b>: Receptionist"]
    assert not any(line.startswith("<b>Level</b>") for line in lines)
    unknown = _event(type="attendance", severity="info", payload={"match_reason": "no_match"})
    lines = telegram.format_caption(unknown, "Receptionist", "Gerbang Lobi", None, tz=WIB).splitlines()
    assert lines[0] == "⚠️ <b>UNKNOWN FACE</b>" and "<b>Zona</b>: Gerbang Lobi" in lines
    assert not any("Lihat klip" in line for line in lines)


def test_caption_new_type_uppercased_and_no_zone():
    text = telegram.format_caption(_event(type="fall_detect"), "Lobi", None, None, tz=WIB)
    assert text.splitlines()[0] == "🚨 <b>FALL_DETECT</b>"
    assert "<b>Zona</b>" not in text


def test_caption_escapes_html():
    ev = _event(type="attendance", severity="info", payload={
        "match_reason": "matched", "direction": "entry", "employee_name": "A&B <x>"})
    text = telegram.format_caption(ev, "Cam <1>", "Z & Z", None, tz=WIB)
    assert "A&amp;B &lt;x&gt;" in text and "Cam &lt;1&gt;" in text and "Z &amp; Z" in text
    assert "<x>" not in text


def test_caption_bounded_length_naive_utc():
    naive = _event(ts_event=datetime(2026, 9, 25, 4, 42, 7), type="x" * 2000)
    text = telegram.format_caption(naive, "C" * 500, "Z" * 500, "http://h", tz=WIB)
    assert "11:42:07" in text and len(text) <= telegram.CAPTION_MAX
```

Ubah juga ekspektasi `test_deliver_text_without_photo` menjadi `{"chat_id": "-1001", "text": "halo", "parse_mode": "HTML"}` dan tambahkan di `test_deliver_photo_uses_multipart`: `assert b'name="parse_mode"' in req.data and b"HTML" in req.data`. Di `test_alert_dispatcher.py`, bila ada assertion `caption.startswith("🚨 Intrusi — …")`, ganti menjadi `sent[0]["caption"].startswith("🚨 <b>INTRUSION</b>")`.

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_telegram.py tests/test_alert_dispatcher.py -q`
Expected: FAIL — format lama.

- [ ] **Step 3: Implementasi**

`backend/app/services/telegram.py`:
- `import html` di kepala; ganti `LABELS` (dan `HEADER_MAX` bila ada) dengan:

```python
TYPE_TITLE = {"intrusion": "INTRUSION", "loitering": "LOITERING", "running": "RUNNING"}
FIELD_MAX = 120  # nilai per baris dibatasi sebelum escape → caption selalu < CAPTION_MAX
```

- `deliver`: tambahkan `"parse_mode": "HTML"` ke data `sendPhoto` dan `sendMessage`.
- Ganti `format_caption`:

```python
def format_caption(event, camera_name: str, zone_name: str | None, app_url: str | None, tz=None) -> str:
    """Caption HTML Telegram: judul tebal (Inggris), satu data per baris (label Indonesia)."""
    def val(v) -> str:
        return html.escape(str(v)[:FIELD_MAX])

    ts = event.ts_event if event.ts_event.tzinfo else event.ts_event.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(tz)
    payload = event.payload or {}
    rows: list[tuple[str, str]] = []
    if event.type == "attendance" and payload.get("match_reason") == "matched":
        arah = "CHECK IN" if payload.get("direction") == "entry" else "CHECK OUT"
        title = f"✅ <b>ATTENDANCE — {arah}</b>"
        rows.append(("Nama", payload.get("employee_name") or "-"))
    elif event.type == "attendance":
        title = "⚠️ <b>UNKNOWN FACE</b>"
    else:
        title = f"🚨 <b>{val(TYPE_TITLE.get(event.type, str(event.type).upper()))}</b>"
    rows.append(("Kamera", camera_name))
    if zone_name:
        rows.append(("Zona", zone_name))
    rows.append(("Waktu", ts.strftime("%d %b %Y %H:%M:%S %Z").strip()))
    if event.type != "attendance":
        rows.append(("Level", str(event.severity or "").upper()))
    lines = [title, ""] + [f"<b>{k}</b>: {val(v)}" for k, v in rows]
    if app_url:
        lines += ["", f"🎥 Lihat klip: {val(app_url)}/events?event={event.id}"]
    return "\n".join(lines)
```

(`TEST_TEXT` tidak mengandung karakter HTML khusus — aman dengan `parse_mode=HTML`.)

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`
Expected: semua passed.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Feedback F2: caption rapi**: judul tebal berbahasa Inggris (`INTRUSION`, `ATTENDANCE — CHECK IN/OUT`,
  `UNKNOWN FACE`, tipe baru → huruf besar), satu data per baris (Nama/Kamera/Zona/Waktu/Level), tautan klip di akhir;
  `parse_mode=HTML` dengan escape nilai, panjang tiap nilai dibatasi (tanpa memotong tag). Backend **<angka> passed**.
```

```bash
git add backend/app/services/telegram.py backend/tests/test_telegram.py backend/tests/test_alert_dispatcher.py CHANGELOG.md
git commit -m "feat(telegram): caption per baris (HTML), tipe alert berbahasa Inggris"
```

---

### Task 3: Label snapshot — jenis kejadian (vision) + nama/Unknown (backend)

**Files:**
- Modify: `vision/vision/recorder.py` (`_draw_track_box`)
- Modify: `backend/app/services/annotate.py` (fungsi baru `annotate_snapshot`)
- Modify: `backend/app/services/attendance.py` (`handle_face_event`)
- Test: `vision/tests/test_recorder.py`, `backend/tests/test_annotate.py` (baru), `backend/tests/test_attendance_logic.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `annotate.annotate_snapshot(image_path: str, label: str, bbox_norm: list[float] | None, color=GREEN) -> None` (best-effort, overwrite); `annotate.ORANGE`; vision `recorder.TYPE_LABEL`.

- [ ] **Step 1: Tulis tes (gagal)**

`vision/tests/test_recorder.py` — tambah:

```python
def test_snapshot_label_is_event_type_not_track_id(tmp_path, monkeypatch):
    import cv2
    labels = []
    real = cv2.putText
    monkeypatch.setattr(cv2, "putText", lambda img, text, *a, **k: labels.append(text) or real(img, text, *a, **k))
    rec = Recorder(1, make_cfg(tmp_path), autostart=False)
    ok, buf = cv2.imencode(".jpg", np.full((480, 640, 3), 255, np.uint8))
    for kind in ("intrusion", "loitering", "fall_detect"):
        ev = {**_ev(tid=7), "type": kind}
        rec._draw_track_box(buf.tobytes(), ev)
    assert labels == ["INTRUSION", "LOITERING", "FALL_DETECT"]
    rec.close()
```

`backend/tests/test_annotate.py` (baru):

```python
from PIL import Image

from app.services.annotate import ORANGE, annotate_snapshot


def _jpeg(path, size=(640, 480)):
    Image.new("RGB", size, (255, 255, 255)).save(path, "JPEG")


def test_annotate_snapshot_draws_label_above_box(tmp_path):
    p = tmp_path / "snap.jpg"
    _jpeg(p)
    annotate_snapshot(str(p), "Budi Santoso", [0.4, 0.4, 0.6, 0.7])
    img = Image.open(p).convert("RGB")
    # area label tepat di atas kotak (y = 0.4 * 480 = 192) tidak lagi putih
    crop = img.crop((256 + 2, 192 - 16, 256 + 40, 192 - 4))
    assert any(px != (255, 255, 255) for px in crop.getdata())


def test_annotate_snapshot_without_bbox_uses_top_left(tmp_path):
    p = tmp_path / "snap.jpg"
    _jpeg(p)
    annotate_snapshot(str(p), "Unknown", None, color=ORANGE)
    assert any(px != (255, 255, 255) for px in Image.open(p).convert("RGB").crop((0, 0, 60, 30)).getdata())


def test_annotate_snapshot_missing_file_is_noop(tmp_path):
    annotate_snapshot(str(tmp_path / "missing.jpg"), "X", None)  # tidak raise
```

`backend/tests/test_attendance_logic.py` — tambah:

```python
def test_face_snapshot_labeled_with_name_or_unknown(db, monkeypatch):
    calls = []
    monkeypatch.setattr(attendance, "annotate_snapshot",
                        lambda path, label, bbox, color=None: calls.append((path.endswith("snapshots/s.jpg"), label)))
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    monkeypatch.setattr(attendance.face, "match_crop", _matched(e.id))
    ev = _raw_event(db, "entry", _at(*MON, 7, 10), {"bbox_norm": [0.1, 0.1, 0.2, 0.2]})
    ev.snapshot_path = "snapshots/s.jpg"
    db.commit()
    attendance.handle_face_event(db, ev)
    monkeypatch.setattr(attendance.face, "match_crop", _no_match())
    ev2 = _raw_event(db, "entry", _at(*MON, 7, 20))
    ev2.snapshot_path = "snapshots/s.jpg"
    db.commit()
    attendance.handle_face_event(db, ev2)
    assert calls == [(True, e.name), (True, "Unknown")]
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_recorder.py -q -k label` dan `cd backend && .venv/bin/python -m pytest tests/test_annotate.py tests/test_attendance_logic.py -q`
Expected: FAIL — label masih `ID 7`; `annotate_snapshot` tidak ada.

- [ ] **Step 3: Implementasi**

`vision/vision/recorder.py` — konstanta modul di dekat `_TRACK_COLORS`:

```python
    # label snapshot = jenis kejadian (feedback F5), bukan ID track
    TYPE_LABEL = {"intrusion": "INTRUSION", "loitering": "LOITERING", "running": "RUNNING"}
```

dan di `_draw_track_box` ganti `label = f"ID {payload.get('track_id')}"` dengan
`label = self.TYPE_LABEL.get(event.get("type"), str(event.get("type") or "").upper())`; docstring: "Bbox track + label jenis kejadian".

`backend/app/services/annotate.py` — `from PIL import Image, ImageDraw, ImageFont`, konstanta `ORANGE = (230, 130, 0)`, lalu:

```python
def annotate_snapshot(image_path: str, label: str, bbox_norm: list[float] | None,
                      color=GREEN) -> None:
    """Label (nama karyawan / Unknown) di atas kotak wajah pada snapshot frame penuh (overwrite).

    bbox_norm relatif frame (payload node). Best-effort: file hilang/corrupt → log + lanjut.
    """
    try:
        img = Image.open(image_path)
        img.load()
    except Exception:
        face.logger.warning("annotate: tidak bisa buka snapshot %s", image_path, exc_info=True)
        return
    try:
        img = img.convert("RGB")
        d = ImageDraw.Draw(img)
        w, h = img.size
        x, y = 8, 8
        if bbox_norm and len(bbox_norm) == 4:
            x, y = int(bbox_norm[0] * w), int(bbox_norm[1] * h)
        size = max(14, w // 45)
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:  # Pillow lama tanpa argumen size
            font = ImageFont.load_default()
        tw = int(d.textlength(label, font=font))
        top = max(0, y - size - 8)
        d.rectangle([x, top, x + tw + 10, top + size + 6], fill=color)
        d.text((x + 5, top + 2), label, fill=(255, 255, 255), font=font)
        img.save(image_path, "JPEG", quality=90)
    except Exception:
        face.logger.warning("annotate: label snapshot gagal %s", image_path, exc_info=True)
```

`backend/app/services/attendance.py`:
- import: `from app.services.annotate import ORANGE, annotate_face_crop, annotate_snapshot` (sesuaikan dengan import `annotate_face_crop` yang ada).
- Helper:

```python
def _label_snapshot(event, payload: dict, label: str, color=None) -> None:
    """Snapshot absensi diberi nama/Unknown setelah pencocokan (vision belum tahu identitas)."""
    if event.snapshot_path:
        kwargs = {"color": color} if color is not None else {}
        annotate_snapshot(str(Path(settings.storage_root) / event.snapshot_path), label,
                          payload.get("bbox_norm"), **kwargs)
```

- Di cabang `res.employee_id is None`: bila `res.reason == "no_match"`, panggil `_label_snapshot(event, payload, "Unknown", ORANGE)` sebelum `_save`.
- Setelah `payload["employee_name"] = …` (cabang cocok): `_label_snapshot(event, payload, emp.name if emp is not None else "Unknown")`.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: backend suite penuh + `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"`
Expected: semua passed (vision 205, 3 deselected).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Feedback F5: label snapshot**: kotak orang di snapshot behavior berlabel jenis kejadian (`INTRUSION`/`LOITERING`/
  `RUNNING`, tipe baru huruf besar) — bukan `ID n`; snapshot absensi diberi nama karyawan (atau `Unknown` oranye
  untuk wajah tak dikenal) oleh backend setelah pencocokan (Pillow, best-effort) → foto Telegram ikut berlabel.
  Pipeline wajah vision tidak berubah. Backend **<angka>**, vision **<angka>** passed.
```

```bash
git add vision/vision/recorder.py vision/tests/test_recorder.py backend/app/services/annotate.py backend/app/services/attendance.py backend/tests/test_annotate.py backend/tests/test_attendance_logic.py CHANGELOG.md
git commit -m "feat(snapshot): label jenis kejadian dan nama/Unknown pada snapshot"
```

---

### Task 4: Nama zona di Inbox + tautan "Atur zona" di Deteksi & Model

**Files:**
- Modify: `frontend/src/features/events/EventsPage.tsx` (peta nama zona)
- Modify: `frontend/src/features/config/DetectionPage.tsx` (hapus Reset, tautan Atur zona)
- Modify: `frontend/src/features/config/ZonesPage.tsx` (pilih kamera dari `?camera=`)
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/events.test.tsx`, `frontend/src/__tests__/detection.test.tsx`, `frontend/src/__tests__/zones.test.tsx`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Tulis/ubah tes (gagal)**

`events.test.tsx` — di `stubFetch`, tambahkan respons `if (u.includes('/zones')) return { ok: true, status: 200, json: () => Promise.resolve([{ id: 7, name: 'Lorong-15', camera_id: 1 }]) }` (sebelum fallback 404), lalu:

```tsx
test('inbox shows zone names; deleted zone falls back to #id', async () => {
  const withZones: EventOut[] = [
    { ...EVENTS[0], zone_id: 7 },
    { ...EVENTS[1], zone_id: 99 },
  ]
  vi.stubGlobal('fetch', stubFetch(withZones))
  renderPage()
  expect(await screen.findByText(/Lorong-15/)).toBeInTheDocument()
  expect(screen.getByText(/#99/)).toBeInTheDocument()
  expect(screen.getByTestId('event-detail')).toHaveTextContent('Lorong-15')
})
```

`detection.test.tsx` — ganti tes `reset override tidak lagi mengirim analyzers` dengan:

```tsx
test('tiap kamera punya tautan Atur zona, tanpa tombol Reset override', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const body = url.includes('/detector-settings') ? settings : url.includes('/zones') ? [zone]
      : url.includes('/cameras') ? [camera] : { id: 1, username: 'admin', role: 'admin' }
    return { ok: true, status: 200, json: async () => body }
  }))
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=detection']}><ConfigurationPage /></MemoryRouter></I18nProvider>)
  const link = await screen.findByRole('link', { name: 'Atur zona →' })
  expect(link).toHaveAttribute('href', '/configuration?tab=zones&camera=1')
  expect(screen.queryByRole('button', { name: 'Reset override' })).not.toBeInTheDocument()
})
```

`zones.test.tsx` — tambah:

```tsx
test('?camera=<id> memilih kamera itu', async () => {
  window.history.pushState({}, '', '/configuration?tab=zones&camera=2')
  try {
    vi.stubGlobal('fetch', stubFetch({ zones: [] }))
    render(<I18nProvider><ZonesPage /></I18nProvider>)
    await waitFor(() => {
      const zoneCalls = (fetch as unknown as Mock).mock.calls.map(([u]) => String(u))
      expect(zoneCalls.some((u) => u.includes('/zones?camera_id=2'))).toBe(true)
    })
  } finally {
    window.history.pushState({}, '', '/')
  }
})
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/events.test.tsx src/__tests__/detection.test.tsx src/__tests__/zones.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implementasi**

`EventsPage.tsx`:
- `import { listZones } from '../../api/zones'`; state `const [zoneNames, setZoneNames] = useState<Record<number, string>>({})`; di effect yang memuat kamera tambahkan
  `listZones().then((zs) => setZoneNames(Object.fromEntries(zs.map((z) => [z.id, z.name])))).catch(() => setZoneNames({}))`.
- Helper `const zoneName = (id: number) => zoneNames[id] ?? `#${id}``.
- Tag daftar: `{t('events.col.zone')} {zoneName(e.zone_id)}`; detail: `{selected.zone_id != null ? zoneName(selected.zone_id) : '—'}`.

`DetectionPage.tsx`:
- `import { Link } from 'react-router-dom'`; ganti `<button … det-link … Reset>` dengan
  `<Link className="det-link" to={`/configuration?tab=zones&camera=${camera.id}`}>{t('detection.editZones')}</Link>`.
- Hint: tambahkan bahwa mengosongkan kolom = nilai global (key `detection.hint` sudah menyebutnya — pastikan tetap).

`ZonesPage.tsx` — di effect pemuatan awal, sebelum `const first = …`:

```tsx
        // tautan "Atur zona" dari Deteksi & Model: ?camera=<id> memilih kamera itu
        const wanted = Number(new URLSearchParams(window.location.search).get('camera'))
        const first = cs.find((c) => c.id === wanted)
          ?? cs.find((c) => all.some((z) => z.camera_id === c.id)) ?? cs[0]
```

(Baca `window.location.search` langsung — `ZonesPage` dirender tanpa router di tes; di aplikasi URL browser sama dengan router.)

`i18n.tsx`: `id` `'detection.editZones': 'Atur zona →'`, `en` `'detection.editZones': 'Edit zones →'`; hapus `detection.reset` bila tidak dirujuk lagi.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: semua passed; build 0; lint set sama. 390 px untuk Inbox dan Deteksi & Model.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Feedback F3/F4**: Inbox menampilkan **nama zona** (zona terhapus → `#id`); Deteksi & Model mengganti tombol Reset
  override dengan tautan **"Atur zona →"** yang membuka Zona Deteksi dengan kamera itu terpilih (`?camera=`).
  Frontend **<angka> passed**, build 0, lint set sama.
```

```bash
git add frontend/src/features/events/EventsPage.tsx frontend/src/features/config/DetectionPage.tsx frontend/src/features/config/ZonesPage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/events.test.tsx frontend/src/__tests__/detection.test.tsx frontend/src/__tests__/zones.test.tsx CHANGELOG.md
git commit -m "feat(ui): nama zona di Inbox + tautan Atur zona dari Deteksi & Model"
```

---

### Task 5: Suite penuh + dokumen + push (eksekutor berhenti di sini)

- [ ] **Step 1: Suite penuh**

```bash
cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1; cd ..
backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu" | tail -1
cd frontend && npx vitest run | tail -3 && npm run build > /dev/null; echo build=$?; npm run lint | tail -2; cd ..
```

- [ ] **Step 2: Dokumen** — README §Alert Telegram: rate-limit per orang (critical tanpa batas, lainnya 2 menit), format pesan. Commit:

```bash
git add README.md CHANGELOG.md
git commit -m "docs(telegram): rate-limit per orang + format pesan"
```

- [ ] **Step 3: Push** — `git push origin feat/telegram-alerts` (diizinkan). **Jangan** deploy, ssh, atau merge.

Catatan untuk sesi perencana: deploy butuh restart **isentinel-api dan vision-node** (Task 3 mengubah vision).
