import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User

ROLES = {"admin", "manager", "analyst", "sdr", "closer"}

bearer = HTTPBearer(auto_error=False)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{_b64(salt)}.{_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt_text, digest_text = encoded.split(".")
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(digest_text + "=" * (-len(digest_text) % 4))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_token(user: User) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": user.id, "tenant": user.tenant_id, "exp": int(time.time()) + 60 * 60 * 12}, separators=(",", ":")).encode())
    body = f"{header}.{payload}"
    signature = _b64(hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Autenticação necessária")
    try:
        header, payload, signature = credentials.credentials.split(".")
        body = f"{header}.{payload}"
        expected = _b64(hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if int(claims["exp"]) < int(time.time()):
            raise ValueError("expired")
        user = db.get(User, claims["sub"])
        if user is None or user.tenant_id != claims["tenant"]:
            raise ValueError("missing user")
        return user
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Token inválido ou expirado") from None


def require_roles(*allowed: str):
    def check(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="Seu perfil não permite esta ação")
        return user

    return check
