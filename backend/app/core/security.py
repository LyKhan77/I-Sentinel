import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
from app.core.config import settings

# ponytail: raw bcrypt — passlib 1.7.4 is broken with bcrypt 5.x (detect_wrap_bug raises), pinning deps was out of scope
def hash_password(pw: str) -> str: return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
def verify_password(pw: str, h: str) -> bool: return bcrypt.checkpw(pw.encode(), h.encode())

def create_access_token(user_id: int, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_min)
    return jwt.encode({"sub": str(user_id), "role": role, "exp": exp}, settings.jwt_secret, settings.jwt_algorithm)

def decode_token(token: str) -> dict | None:
    try: return jwt.decode(token, settings.jwt_secret, [settings.jwt_algorithm])
    except jwt.PyJWTError: return None

# get_current_user / require_admin live in app/api/deps.py (Task 5) — need get_db.
