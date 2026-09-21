# Runbook: Bersihkan Data Events (keep 1 contoh per type)

Kegunaan: hapus event lama (DB + blob disk) saat development/testing, sisakan
1 contoh per type yang punya snapshot + clip lengkap — supaya UI punya contoh
tiap kategori tanpa data sampah.

> DESTRUKTIF. Data absensi (`attendance_event`, `attendance_day`) TIDAK
> disentuh. Jalankan di server, bukan dari mesin lokal.

## Prosedur (gspe-ai3)

1. SSH ke server: `ssh gspe-ai3@192.168.2.133`
2. Simpan script di bawah sebagai `/tmp/cleanup_events.sh`, jalankan
   `bash /tmp/cleanup_events.sh`.

```python
# inti script (DATABASE_URL + STORAGE_ROOT dibaca dari I-Sentinel/.env)
import sqlalchemy as sa, json, os
e = sa.create_engine(os.environ["DATABASE_URL"]); root = os.environ["STORAGE_ROOT"]
with e.begin() as c:
    rows = c.exec_driver_sql("select id, event_id, type, clip_path, snapshot_path, payload from event order by created_at").all()
    seen = {}
    for id_, ev_id, typ, clip, snap, payload in rows:
        if typ not in seen and clip and snap:
            seen[typ] = id_
    keep = set(seen.values())
    for id_, ev_id, clip, snap, payload in rows:
        if id_ in keep: continue
        c.exec_driver_sql("delete from alert where event_id = %s", (id_,))  # FK RESTRICT
        c.exec_driver_sql("delete from event where id = %s", (id_,))
        for rel in (clip, snap, (json.loads(payload or "{}") or {}).get("crop_path")):
            if rel and os.path.isfile(os.path.join(root, rel)):
                os.remove(os.path.join(root, rel))
```

Catatan:
- `alert.event_id` FK → `event.id` tanpa ondelete → hapus alert dulu.
- `crop_path` hidup di payload JSON (bukan kolom) — ikut dihapus dari disk.
- Blob di `STORAGE_ROOT/{clips,snapshots,crops}`; path relatif.
- Bukti eksekusi 2026-09-21: 4491 → 5 events (attendance/intrusion/loitering/
  person_detect/running masing-masing 1), blob disk terbersihkan.

Rollback: tidak ada (data dihapus permanen) — backup dulu bila ragu:
`pg_dump -t event -t alert isentinel > backup.sql`.
