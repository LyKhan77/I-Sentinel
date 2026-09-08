# Milestone Brief — Fase 4: Absensi Wajah

> Brief. Dikembangkan menjadi plan detail setelah Fase 3 selesai.

**Goal:** Siklus absensi penuh: enrollment wajah (upload) → person lewat gate → wajah dikenali → attendance entry/exit → rekap harian dengan shift & status telat/NO EXIT → export/import. Bukti: satu orang test masuk+keluar gate → rekap harian benar (ontime/late/no_exit), CSV export cocok.

**Prasyarat:** Fase 3 done (event pipeline, snapshot, alert).

## Scope

1. **Models**: `employee`, `face_embedding` (vector 512 as JSON/blob + source path + quality), `shift`, `attendance_event`, `attendance_days`, gate = zone type absensi + direction.
2. **Face service** (`services/face.py`): InsightFace (SCRFD deteksi + ArcFace embedding) — jalankan di server atas crop best-shot dari vision-node (analyzer `face_gate.py`: pilih frame wajah terbesar/terjelas saat track di zona absensi); gallery in-memory (<100) + cosine ≥ 0.40; refresh saat enrollment berubah.
3. **Enrollment API+UI**: karyawan CRUD, upload foto (min 3 pose / max 5 untuk aktif), galeri + skor kualitas, hapus biometrik (PDP), assign shift. Sesuai mockup 05.
4. **Attendance logic** (`services/attendance.py`): event entry/exit → attendance_event (ts_event dari gate) → agregasi attendance_days: ontime/late(≥toleransi)/waiting/no_exit(1 jam setelah akhir shift)/absent; admin override dengan catatan audit; job harian menutup status no_exit/absent.
5. **UI Attendance** sesuai mockup 04: tab harian/rentang/per-karyawan, summary, timeline entry-exit (toleransi kuning), export CSV/XLSX + import.
6. **Gate config UI**: tab Gate Absensi (kamera↔arah, validasi satu arah, toggle snapshot) sesuai mockup 06.
7. **Event attendance**: tipe `attendance` masuk web inbox + snapshot gate (toggle).

## Kriteria bukti

- [ ] Unit: agregasi attendance_days (ontime/late/waiting/no_exit/absent), face match threshold gallery kecil, min-3-foto rule — hijau CPU (embedding dummy).
- [ ] Server: orang test terdaftar → entry+exit → rekap + status benar; orang tidak dikenal → event unknown (tidak jadi absensi).
- [ ] Export CSV dibandingkan manual — cocok; import roundtrip.
- [ ] Enrollment <100 wajah: match < 50 ms (log).

## Risiko

- Kualitas wajah gate (sudut, cahaya) → quality gate pada best-shot (blur/ukuran min); tuning threshold per gate tersedia.
- Embedding storage: JSON float array cukup untuk <100; migrasi pgvector hanya jika >5k (tercatat).
