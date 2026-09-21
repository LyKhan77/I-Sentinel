from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://isentinel:isentinel@localhost/isentinel"
    jwt_secret: str = "CHANGE_ME"
    cookie_secure: bool = False  # true di belakang reverse proxy HTTPS; false agar LAN HTTP bisa login
    jwt_algorithm: str = "HS256"
    access_token_expire_min: int = 480
    node_api_key: str = "CHANGE_ME"
    telegram_bot_token: str = ""
    alert_min_severity: str = "warning"
    cam_username: str = ""
    cam_password: str = ""
    storage_root: str = "/data/isentinel"
    mqtt_url: str = "localhost:1883"
    mqtt_username: str = ""
    mqtt_password: str = ""
    go2rtc_url: str = "http://localhost:1984"
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
    no_exit_grace_min: int = 60  # toleransi setelah jam shift usai sebelum status jadi no_exit
    # catatan: JWT_SECRET wajib >= 32 karakter acak di produksi (lihat .env.example)

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
