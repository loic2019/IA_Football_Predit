from fastapi import APIRouter, HTTPException, Response, status

from api.schemas.auth import LoginRequest, SignupRequest
from api.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "session_token"


@router.post("/login")
def login(payload: LoginRequest, response: Response):
    result = auth_service.login(payload.email, payload.password)
    if not result["ok"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, result["error"])

    # Cookie httpOnly : le JWT n'est jamais lisible en JS côté navigateur
    # (protection XSS), Next.js le lit côté serveur via les headers de requête.
    response.set_cookie(
        COOKIE_NAME,
        result["session_token"],
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24,
    )
    return result["user"]


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, response: Response):
    result = auth_service.signup(payload.email, payload.password, payload.display_name)
    if not result["ok"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result["error"])

    response.set_cookie(COOKIE_NAME, result["session_token"], httponly=True, secure=True, samesite="lax")
    return result["user"]


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.post("/password-reset")
def password_reset(email: str):
    return auth_service.send_password_reset(email)
