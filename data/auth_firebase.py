"""
auth_firebase.py — Authentification via l'API REST Firebase (Identity Toolkit)
===================================================================================
Pas besoin du SDK JS ni de firebase-admin : l'API REST "Identity Toolkit" de
Firebase Auth s'utilise directement en HTTP depuis Python, avec la seule
apiKey publique du projet (voir firebase_config.py).

Fonctions exposées :
- sign_up(email, password)          -> crée un compte, renvoie (ok, data/erreur)
- sign_in(email, password)          -> connecte, renvoie (ok, data/erreur)
- send_password_reset(email)        -> envoie un mail de réinitialisation
- refresh_id_token(refresh_token)   -> renouvelle un token expiré

En cas d'erreur, Firebase renvoie un code HTTP 400 avec un message dans
error.message (ex: "EMAIL_EXISTS", "INVALID_LOGIN_CREDENTIALS",
"WEAK_PASSWORD : Password should be at least 6 characters"). On traduit les
plus courants en français pour l'affichage utilisateur.
"""

import requests

from firebase_config import FIREBASE_API_KEY, IDENTITY_TOOLKIT_BASE, SECURE_TOKEN_BASE

_ERROR_MESSAGES_FR = {
    "EMAIL_EXISTS": (
        "Cet email est déjà utilisé par un compte existant. "
        "Essaie plutôt l'onglet 🔑 Connexion, ou ❓ Mot de passe oublié si tu ne t'en souviens plus."
    ),
    "EMAIL_NOT_FOUND": "Aucun compte ne correspond à cet email.",
    "INVALID_PASSWORD": "Mot de passe incorrect.",
    "INVALID_LOGIN_CREDENTIALS": "Email ou mot de passe incorrect.",
    "USER_DISABLED": "Ce compte a été désactivé.",
    "WEAK_PASSWORD": "Mot de passe trop court (6 caractères minimum).",
    "INVALID_EMAIL": "Adresse email invalide.",
    "MISSING_PASSWORD": "Merci de saisir un mot de passe.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "Trop de tentatives. Réessaie dans quelques minutes.",
    "CONFIGURATION_NOT_FOUND": (
        "⚙️ Configuration Firebase incomplète : la méthode de connexion Email/Mot de passe "
        "n'est pas activée sur ton projet. Va sur console.firebase.google.com → ton projet "
        "→ Authentication → Sign-in method → active 'Email/Password' → Enregistrer, "
        "puis réessaie."
    ),
    "OPERATION_NOT_ALLOWED": (
        "⚙️ Cette méthode de connexion est désactivée dans la console Firebase "
        "(Authentication → Sign-in method → active la méthode correspondante)."
    ),
    "API_KEY_INVALID": "⚙️ Clé API Firebase invalide — vérifie firebase_config.py.",
    "PROJECT_NOT_FOUND": "⚙️ Projet Firebase introuvable — vérifie FIREBASE_PROJECT_ID dans firebase_config.py.",
}


def _translate_error(response_json: dict) -> str:
    try:
        message = response_json.get("error", {}).get("message", "Erreur inconnue")
    except Exception:
        return "Erreur inconnue"
    code = message.split(" : ")[0].split(":")[0].strip()
    return _ERROR_MESSAGES_FR.get(code, message)


def sign_up(email: str, password: str, display_name: str = "") -> tuple[bool, dict]:
    """Crée un compte Firebase Auth. Renvoie (True, {idToken, localId, ...}) ou (False, {"error": "..."})."""
    url = f"{IDENTITY_TOOLKIT_BASE}:signUp?key={FIREBASE_API_KEY}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    try:
        r = requests.post(url, json=payload, timeout=15)
        data = r.json()
    except requests.exceptions.RequestException as e:
        return False, {"error": f"Impossible de contacter Firebase : {e}"}

    if r.status_code != 200:
        return False, {"error": _translate_error(data)}

    if display_name:
        _update_display_name(data.get("idToken"), display_name)

    return True, data


def sign_in(email: str, password: str) -> tuple[bool, dict]:
    """Connecte un utilisateur existant. Renvoie (True, {idToken, localId, ...}) ou (False, {"error": "..."})."""
    url = f"{IDENTITY_TOOLKIT_BASE}:signInWithPassword?key={FIREBASE_API_KEY}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    try:
        r = requests.post(url, json=payload, timeout=15)
        data = r.json()
    except requests.exceptions.RequestException as e:
        return False, {"error": f"Impossible de contacter Firebase : {e}"}

    if r.status_code != 200:
        return False, {"error": _translate_error(data)}

    return True, data


def send_password_reset(email: str) -> tuple[bool, str]:
    """Envoie un email de réinitialisation de mot de passe."""
    url = f"{IDENTITY_TOOLKIT_BASE}:sendOobCode?key={FIREBASE_API_KEY}"
    payload = {"requestType": "PASSWORD_RESET", "email": email}
    try:
        r = requests.post(url, json=payload, timeout=15)
        data = r.json()
    except requests.exceptions.RequestException as e:
        return False, f"Impossible de contacter Firebase : {e}"

    if r.status_code != 200:
        return False, _translate_error(data)

    return True, "Email de réinitialisation envoyé."


def refresh_id_token(refresh_token: str) -> tuple[bool, dict]:
    """Renouvelle un idToken expiré (Firebase idTokens expirent après 1h)."""
    url = f"{SECURE_TOKEN_BASE}?key={FIREBASE_API_KEY}"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    try:
        r = requests.post(url, data=payload, timeout=15)
        data = r.json()
    except requests.exceptions.RequestException as e:
        return False, {"error": f"Impossible de contacter Firebase : {e}"}

    if r.status_code != 200:
        return False, {"error": _translate_error(data)}

    return True, data


def verify_id_token(id_token: str) -> tuple[bool, dict]:
    """
    Vérifie un idToken côté serveur (via accounts:lookup) avant de faire confiance
    à ce que le navigateur a renvoyé. Utilisé après la connexion par téléphone
    (le JS Firebase tourne dans le navigateur, on ne fait jamais confiance à un
    uid/téléphone envoyé tel quel sans le revalider auprès de Firebase).
    Renvoie (True, {localId, phoneNumber, email, ...}) ou (False, {"error": "..."}).
    """
    url = f"{IDENTITY_TOOLKIT_BASE}:lookup?key={FIREBASE_API_KEY}"
    try:
        r = requests.post(url, json={"idToken": id_token}, timeout=15)
        data = r.json()
    except requests.exceptions.RequestException as e:
        return False, {"error": f"Impossible de contacter Firebase : {e}"}

    if r.status_code != 200:
        return False, {"error": _translate_error(data)}

    users = data.get("users", [])
    if not users:
        return False, {"error": "Token invalide ou expiré."}

    return True, users[0]


def _update_display_name(id_token: str, display_name: str) -> None:
    """Enregistre le pseudo côté Firebase Auth (facultatif, cosmétique)."""
    if not id_token:
        return
    url = f"{IDENTITY_TOOLKIT_BASE}:update?key={FIREBASE_API_KEY}"
    payload = {"idToken": id_token, "displayName": display_name, "returnSecureToken": False}
    try:
        requests.post(url, json=payload, timeout=15)
    except requests.exceptions.RequestException:
        pass  # non bloquant : le pseudo est de toute façon stocké dans community.db
