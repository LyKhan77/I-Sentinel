# Milestone Brief — Edge: Jetson Orin Nano

> Brief. Baru dikembangkan menjadi plan detail SETELAH Fase 5 selesai dan keputusan pembelian/jumlah Jetson ada.

**Goal:** Sebagian kamera dipindah ke Jetson Orin Nano: vision-node + go2rtc jalan di edge, server tetap pusat DB/alert/UI. Bukti: kamera di edge-01 menghasilkan event + clip yang masuk sistem identik dengan kamera di server; edge diputus LAN → event tetap masuk setelah reconnect (store-and-forward terbukti).

**Prasyarat:** Fase 5 done; hardware Jetson + JetPack (TensorRT) siap; kamera edge terpasang fisik dekat edge box.

## Scope

1. **Packaging vision-node untuk Jetson**: wheel `isentinel-vision` (tanpa backend deps), export engine TensorRT di Orin (script sama), systemd unit edge, config node via env + MQTT.
2. **go2rtc di edge**: kamera edge connect ke go2rtc lokal; live view browser tetap melalui server (go2rtc server pull dari edge, atau direct — diputus saat plan detail; pertimbangan bandwidth).
3. **Store-and-forward nyata**: disk queue (SQLite/fasterxml) di edge, flush saat online; blob upload retry; timestamp asli dipertahankan.
4. **Provisioning node**: daftarkan node di UI (Configuration), API key per node, assign kamera ke node (tab Kamera sudah ada dropdown node).
5. **Monitoring**: heartbeat edge (cpu/gpu/mem/disk-queue-depth) → dashboard node status + alert saat offline.

## Kriteria bukti

- [ ] 4–8 kamera di Orin Nano @ 5 FPS: GPU edge < 80%, power mode tercatat.
- [ ] Cabut LAN edge 5 menit selama ada aktivitas → reconnect → semua event masuk, urut ts_event, tanpa duplikat.
- [ ] Enroll face baru di server → langsung berlaku tanpa restart edge (face tetap di server).
- [ ] Dashboard menampilkan node edge-01 online + kamera per node benar.

## Risiko

- JetPack/TensorRT versi → pin versi di docs; engine tidak lintas-device (build per node, script bukan artefak).
- Clock drift edge → NTP wajib di edge (runbook); ts_event dari edge dipercaya setelah NTP.
- Bandwidth clip 4K dari edge → clip dibuat di edge (mainstream lokal) lalu upload — bukan stream raw ke server.
