"""
Émission/validation des JWT internes à l'API.

Pourquoi un JWT "maison" en plus du token Firebase ?
- Le token Firebase (id_token) expire vite (1h) et n'est pas fait pour être
  relu à chaque requête HTTP par un serveur tiers sans le SDK Admin.
- On échange donc, une fois à la connexion, l'id_token Firebase vérifié
  contre un JWT applicatif que le frontend Next.js stocke (cookie httpOnly)
  et renvoie à chaque appel API. Le rôle/permissions y sont inclus.
"""
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from api.core.config import get_settings

settings = get_settings()


def create_access_token(*, sub: str, role: str, extra: dict | None = None) -> str:
    payload = {
        "sub": sub,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        **(extra or {}),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
