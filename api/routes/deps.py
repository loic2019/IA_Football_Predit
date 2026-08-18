"""
Dépendances FastAPI réutilisables : utilisateur courant, garde-fous de rôle.

Toute la logique de permissions existante (qui a accès à l'admin, etc.)
reste définie côté Python métier (admin_config.py) — on ne fait ici que
la câbler à la couche HTTP.
"""
from fastapi import Cookie, Depends, HTTPException, status

from api.core.security import decode_access_token


def get_current_user(session_token: str | None = Cookie(default=None)) -> dict:
    """
    Lit le JWT applicatif depuis un cookie httpOnly `session_token`
    (posé par /auth/login). Rejette si absent/invalide/expiré.
    """
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Non authentifié")

    payload = decode_access_token(session_token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalide ou expirée")

    return payload  # {"sub": uid, "role": "...", ...}


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Réservé aux administrateurs")
    return user
