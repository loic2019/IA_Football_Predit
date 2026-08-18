# -*- coding: utf-8 -*-
"""
api/deps.py — Dépendances FastAPI (authentification, rôles).
================================================================================
RÉUTILISE telles quelles les fonctions déjà existantes :
- auth_firebase.verify_id_token()  → vérifie le idToken Firebase (même projet,
  même API REST Identity Toolkit que Streamlit).
- community_db.get_user_by_uid()   → résout le profil local (pseudo, avatar,
  is_admin) à partir du firebase_uid — mêmes comptes, mêmes rôles.

Aucune logique d'authentification n'est dupliquée ou réécrite ici.
"""

from fastapi import Depends, Header, HTTPException, status

import auth_firebase
import community_db


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    """Extrait et vérifie le token Bearer, retourne le profil local complet
    (id, pseudo, avatar_emoji, is_admin, email, firebase_uid)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token manquant.")

    id_token = authorization.removeprefix("Bearer ").strip()
    ok, data = auth_firebase.verify_id_token(id_token)
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, data.get("error", "Token invalide."))

    firebase_uid = data.get("localId")
    profile = community_db.get_user_by_uid(firebase_uid)
    if not profile:
        # Compte Firebase valide mais pas encore de profil local (1ère connexion)
        # → le frontend doit rediriger vers la création de profil.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profil non trouvé — complète ton inscription.")

    return dict(profile)


def get_admin_user(current: dict = Depends(get_current_user)) -> dict:
    """Dépendance pour les routes réservées aux administrateurs (même champ
    is_admin que celui utilisé par Streamlit — voir community_db.is_user_admin)."""
    if not current.get("is_admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Réservé aux administrateurs.")
    return current
