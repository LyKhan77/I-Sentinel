from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://isentinel:isentinel@localhost/isentinel"
    jwt_secret: str = "CHANGE_ME"
    cookie_secure: bool = False  # true di belakang reverse proxy HTTPS; false agar LAN HTTP bisa login
    jwt_algorithm: str = "HS256"
    access_token_expire_min: int = 2880  # 48 jam; diperpanjang otomatis (sesi bergulir)
    node_api_key: str = "CHANGE_ME"
    telegram_bot_token: str = ""
    # deprecated: gerbang Telegram = toggle per behavior
    alert_min_severity: str = "warning"
    cam_username: str = ""
    cam_password: str = ""
    storage_root: str = "/data/isentinel"
    # Password kamera (profil kredensial "store:") — file 0600, WAJIB di luar storage_root
    camera_secrets_file: str = "~/.isentinel/camera-secrets.json"
    mqtt_url: str = "localhost:1883"
    mqtt_username: str = ""
    mqtt_password: str = ""
    go2rtc_url: str = "http://localhost:1984"
    # alamat RTSP go2rtc yang dipakai vision node `server`; tidak dikirim ke browser
    go2rtc_rtsp_url: str = "rtsp://localhost:8554"
    # Host yang dipakai untuk URL go2rtc yang dikirim KE BROWSER (webrtc/mse/hls/snapshot).
    # Kosong = pakai host dari header Host request. Header itu tidak bisa dipercaya
    # begitu ada reverse proxy (proxy Vite dev menggantinya jadi localhost:8000),
    # sehingga klien LAN menerima "localhost:1984" = koneksi ke mesin klien sendiri.
    # Isi dengan IP/hostname server yang bisa dijangkau klien, mis. 192.168.2.133
    go2rtc_public_host: str = ""
    # detector defaults pushed to vision nodes via MQTT config (per-camera override later)
    detector_model: str = "yolo26s.engine"
    detector_nms: bool = False
    detector_conf: float = 0.4
    detector_imgsz: int = 640
    # R5 "Detection & Model": default global untuk kamera tanpa override.
    default_ai_fps: float = 5.0
    motion_enabled: bool = True           # motion gate: inferensi hanya saat ada gerakan
    motion_threshold: float = 25.0        # selisih intensitas piksel (0-255)
    motion_min_area: float = 0.01         # area gerak minimum (rasio frame)
    motion_force_interval_s: float = 2.0  # paksa inferensi berkala (objek diam)
    retention_days: int = 30
    login_max_attempts: int = 5      # percobaan login gagal per (username, ip) sebelum dikunci
    login_lockout_min: int = 15      # lama kunci, menit
    admin_username: str = "admin"
    admin_password: str = ""   # wajib diisi di .env server; bootstrap gagal jelas bila kosong
    # face recognition (insightface buffalo_l): model diunduh scripts/download_face_models.py
    face_model_dir: str = "~/.isentinel/faces_models"
    face_match_threshold: float = 0.40
    face_min_quality: float = 0.5
    face_dup_warn: float = 0.6  # warn enrollment bila cosine vs employee lain >= ini
    # fallback gerbang wajah attendance bila baris detector_setting belum ada
    face_min_width_px: float = 80.0
    face_min_det_score: float = 0.6
    face_max_yaw: float = 0.35
    face_blur_min: float = 120.0
    face_min_frames: int = 3
    # identitas intrusion critical: margin top-1/top-2 + parameter kolektor (fallback bila baris DB tidak ada)
    face_id_margin: float = 0.15
    face_max_pitch: float = 0.30
    face_best_k: int = 5
    face_ident_min_width_px: float = 60.0
    face_ident_window_s: float = 8.0
    # mode absensi tahap 2 (fallback bila baris detector_setting belum ada): legacy | unified
    face_attendance_mode: str = "legacy"
    face_attendance_window_s: float = 1.5
    attendance_cooldown_min: int = 5
    no_exit_grace_min: int = 60  # toleransi setelah jam shift usai sebelum status jadi no_exit
    # catatan: JWT_SECRET wajib >= 32 karakter acak di produksi (lihat .env.example)

    # Optional on-premise multimodal captioning and event questions.
    llm_enabled: bool = False
    llm_api_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_extra_body: dict = {"chat_template_kwargs": {"enable_thinking": False}}
    llm_max_tokens: int = 1000
    llm_timeout_caption_s: float = 60
    llm_timeout_ask_s: float = 120
    llm_concurrency: int = 2
    llm_ask_rate_per_min: int = 6
    llm_caption_min_interval_s: float = 60
    ai_queue_max: int = 100

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
