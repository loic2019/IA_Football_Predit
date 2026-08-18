"""
Couche service pour l'authentification.

Règle d'or du projet : ZÉRO changement dans le code métier existant.
On importe `auth_firebase.py` tel quel (module déjà présent à la racine
du projet, une fois ce dossier `api/` copié à côté) et on se contente de
traduire ses tuples (ok, data) en objets utilisables par les routers
FastAPI + en JWT applicatif.
"""
from api.core.security import create_access_token

import auth_firebase


def determine_role(email: str) -> str:
    """
    Reprend la même logique de rôle que l'app Streamlit actuelle
    (voir admin_config.py pour la liste des emails admin).
    """
    from admin_config import ADMIN_EMAILS

    return "admin" if email.lower() in {e.lower() for e in ADMIN_EMAILS} else "user"


def login(email: str, password: str) -> dict:
    ok, data = auth_firebase.sign_in(email, password)
    if not ok:
        return {"ok": False, "error": data}

    role = determine_role(email)
    token = create_access_token(sub=data["localId"], role=role, extra={"email": email})
    return {
        "ok": True,
        "session_token": token,
        "user": {
            "uid": data["localId"],
            "email": email,
            "display_name": data.get("displayName", ""),
            "role": role,
        },
    }


def signup(email: str, password: str, display_name: str = "") -> dict:
    ok, data = auth_firebase.sign_up(email, password, display_name)
    if not ok:
        return {"ok": False, "error": data}
    return login(email, password)


def send_password_reset(email: str) -> dict:
    ok, message = auth_firebase.send_password_reset(email)
    return {"ok": ok, "message": message}
