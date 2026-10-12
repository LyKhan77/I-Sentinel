"""Tujuan event per behavior zona (`delivery`) dan Mode uji (`test_until`/`revert_to`).

Tanpa migrasi: kunci hidup di JSON `zone.behaviors[]`. Semua fungsi di sini murni
(tanpa DB/IO) supaya aturan stempel dan kedaluwarsa bisa diuji langsung, dan dipakai
bersama oleh router zona (`app/api/zones.py`) dan gerbang Telegram (`alerting`).

Nilai:
- `delivery` ∈ {`all`, `inbox`, `test`} — untuk semua kind deteksi (lima behavior alert dan
  `attendance`); absensi tetap punya `record`/`unknown_delivery` sendiri.
- `unknown_delivery` ∈ {`all`, `inbox`, `none`} — tujuan wajah tidak dikenal pada behavior
  `attendance`; tanpa kunci diturunkan dari toggle lama `telegram_unknown`.
- `test_until` (ISO-8601 UTC) dan `revert_to` ∈ {`all`, `inbox`} hanya ada saat `delivery == "test"`.
- Tanpa `delivery`: diturunkan dari `telegram` item, atau flag zona bila item tanpa key
  (zona pra-R5 `behaviors is None` memakai flag zona).
"""
from datetime import datetime, timedelta, timezone

TEST_HOURS = 24
DELIVERY_KINDS = ("intrusion", "loitering", "running", "idle_zone", "crowd", "attendance")
DELIVERIES = ("all", "inbox", "test")
UNKNOWN_DELIVERIES = ("all", "inbox", "none")


def parse_until(value) -> datetime | None:
    """ISO-8601 → datetime UTC; `None` bila hilang/tak terbaca (diperlakukan kedaluwarsa).

    String tanpa offset diperlakukan UTC (nilai selalu ditulis server sebagai `isoformat()`
    dari datetime UTC beraksi zona; ini penjaga untuk data lama/klien lain).
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def effective_delivery(behavior: dict | None, zone_telegram: bool, now: datetime | None = None) -> str:
    """Tujuan efektif satu behavior: `all` | `inbox` | `test`.

    Mode uji yang sudah lewat `test_until` kembali ke `revert_to` (bawaan `all`) — inilah
    satu-satunya tempat aturan kedaluwarsa hidup, dipakai API (Telegram) dan node (penekanan event).
    """
    now = now or datetime.now(timezone.utc)
    if not isinstance(behavior, dict):
        return "all" if zone_telegram else "inbox"
    delivery = behavior.get("delivery")
    if delivery == "test":
        until = parse_until(behavior.get("test_until"))
        if until is not None and now < until:
            return "test"
        return behavior.get("revert_to") if behavior.get("revert_to") in ("all", "inbox") else "all"
    if delivery in ("all", "inbox"):
        return delivery
    return "all" if behavior.get("telegram", zone_telegram) else "inbox"


def unknown_delivery(behaviors: list | None) -> str:
    """Tujuan wajah tidak dikenal satu zona: `all` | `inbox` | `none`.

    Item `kind == "attendance"` pertama yang berupa dict yang menentukan. Tanpa kunci sah
    nilainya diturunkan dari toggle lama `telegram_unknown` (hanya `false` → `inbox`) dan
    `behaviors` kosong/`None` → `all`, supaya zona lama berperilaku persis seperti sebelumnya.
    Murni: data sampah (`None`, `[None, "old"]`, nilai tak sah) tidak melempar.
    """
    for b in behaviors or []:
        if isinstance(b, dict) and b.get("kind") == "attendance":
            value = b.get("unknown_delivery")
            if value in UNKNOWN_DELIVERIES:
                return value
            return "inbox" if b.get("telegram_unknown") is False else "all"
    return "all"


def _previous_delivery(prev: dict | None) -> str:
    """Tujuan efektif behavior sebelum uji dimulai (`all` bila tidak ada jejak)."""
    if not isinstance(prev, dict):
        return "all"
    if prev.get("delivery") in ("all", "inbox"):
        return prev["delivery"]
    if prev.get("delivery") == "test":
        # uji lama (kedaluwarsa) — yang berlaku sesudahnya adalah `revert_to`-nya
        return prev.get("revert_to") if prev.get("revert_to") in ("all", "inbox") else "all"
    if "telegram" in prev:
        return "all" if prev["telegram"] else "inbox"
    return "all"


def stamp_test_mode(new: list | None, old: list | None, now: datetime | None = None) -> list | None:
    """Normalisasi behaviors yang akan disimpan; masukan tidak diubah (salinan baru).

    - `delivery != "test"`: buang `test_until`/`revert_to` (kunci uji menggantung).
    - `delivery == "test"` yang baru / kedaluwarsa: `test_until = now + 24 jam`,
      `revert_to` = tujuan efektif sebelumnya.
    - `delivery == "test"` yang sedang berjalan: nilai tersimpan dipertahankan
      (menyimpan perubahan lain tidak memperpanjang uji).
    """
    if new is None:
        return new
    now = now or datetime.now(timezone.utc)
    olds: dict[str, dict] = {}
    for b in old or []:
        if isinstance(b, dict) and isinstance(b.get("kind"), str):
            olds[b["kind"]] = b
    out: list = []
    for b in new:
        if not isinstance(b, dict):
            out.append(b)
            continue
        item = dict(b)
        if item.get("delivery") != "test":
            item.pop("test_until", None)
            item.pop("revert_to", None)
            out.append(item)
            continue
        prev = olds.get(item.get("kind"))
        prev_until = parse_until(prev.get("test_until")) if isinstance(prev, dict) else None
        if isinstance(prev, dict) and prev.get("delivery") == "test" and prev_until is not None and prev_until > now:
            item["test_until"] = prev["test_until"]
            item["revert_to"] = prev.get("revert_to") if prev.get("revert_to") in ("all", "inbox") else "all"
        else:
            item["test_until"] = (now + timedelta(hours=TEST_HOURS)).isoformat()
            item["revert_to"] = _previous_delivery(prev)
        out.append(item)
    return out
