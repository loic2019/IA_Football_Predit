# -*- coding: utf-8 -*-
"""api/routers/profile.py — Écran Profil.
Réutilise community_db.py tel quel."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_current_user
import community_db

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
def get_profile(current: dict = Depends(get_current_user)):
    return current


class ProfileUpdate(BaseModel):
    pseudo: str | None = None
    avatar_emoji: str | None = None
    avatar_image_b64: str | None = None
    clear_avatar_image: bool = False


@router.put("")
def update_profile(payload: ProfileUpdate, current: dict = Depends(get_current_user)):
    if payload.pseudo and community_db.pseudo_taken(payload.pseudo) and payload.pseudo != current.get("pseudo"):
        return {"updated": False, "reason": "Ce pseudo est déjà pris."}
    community_db.update_profile(
        current["id"],
        pseudo=payload.pseudo,
        avatar_emoji=payload.avatar_emoji,
        avatar_image_b64=payload.avatar_image_b64,
        clear_avatar_image=payload.clear_avatar_image,
    )
    return {"updated": True, "profile": community_db.get_user_by_uid(current["firebase_uid"])}


@router.get("/avatar-choices")
def avatar_choices():
    return ["⚽", "🎯", "🔥", "🍀", "🦁", "🐺", "🐍", "🚀", "👑", "🎲"]
