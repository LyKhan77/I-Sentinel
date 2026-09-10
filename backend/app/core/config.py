from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://isentinel:isentinel@localhost/isentinel"
    jwt_secret: str = "CHANGE_ME"
    cookie_secure: bool = False  # true di belakang reverse proxy HTTPS; false agar LAN HTTP bisa login
    jwt_algorithm: str = "HS256"
    access_token_expire_min: int = 480
    node_api_key: str = "CHANGE_ME"
    telegram_bot_token: str = ""
    cam_username: str = ""
    cam_password: str = ""
    storage_root: str = "/data/isentinel"
    mqtt_url: str = "localhost:1883"
    go2rtc_url: str = "http://localhost:1984"
    retention_days: int = 30
    admin_username: str = "admin"
    admin_password: str = ""   # wajib diisi di .env server; bootstrap gagal jelas bila kosong
    # catatan: JWT_SECRET wajib >= 32 karakter acak di produksi (lihat .env.example)

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
