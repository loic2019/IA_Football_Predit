# -*- coding: utf-8 -*-
"""api/routers/auth.py — Inscription, connexion, profil courant.
Réutilise auth_firebase.py et community_db.py sans aucune modification."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth_firebase
import community_db
from api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str
    password: str


class ProfileCreate(BaseModel):
    firebase_uid: str
    email: str
    pseudo: str
    avatar_emoji: str = "⚽"


@router.post("/signup")
def signup(payload: Credentials):
    ok, data = auth_firebase.sign_up(payload.email, payload.password)
    if not ok:
        raise HTTPException(400, data.get("error", "Échec de l'inscription."))
    return data


@router.post("/login")
def login(payload: Credentials):
    ok, data = auth_firebase.sign_in(payload.email, payload.password)
    if not ok:
        raise HTTPException(401, data.get("error", "Échec de la connexion."))
    return data


@router.post("/complete-profile")
def complete_profile(payload: ProfileCreate):
    """Crée le profil local (pseudo, avatar) après une 1ère inscription Firebase."""
    existing = community_db.get_user_by_uid(payload.firebase_uid)
    if existing:
        return dict(existing)
    profile = community_db.create_user_profile(
        firebase_uid=payload.firebase_uid,
        email=payload.email,
        pseudo=payload.pseudo,
        avatar_emoji=payload.avatar_emoji,
    )
    return dict(profile)


@router.get("/me")
def me(current: dict = Depends(get_current_user)):
    return current
