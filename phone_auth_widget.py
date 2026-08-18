"""
phone_auth_widget.py — Connexion par numéro de téléphone (SMS)
====================================================================
HISTORIQUE DU BUG CORRIGÉ ICI
-------------------------------
La version précédente tentait de transmettre le token Firebase à Python en
faisant naviguer `window.top.location` depuis l'intérieur d'un composant
`components.html`/`st.iframe`. Ça ne pouvait pas marcher : AUCUNE iframe
Streamlit n'inclut la permission de sandbox `allow-top-navigation` (vérifié
avec Playwright — l'attribut sandbox réel ne contient que `allow-forms
allow-modals allow-popups allow-popups-to-escape-sandbox allow-same-origin
allow-scripts allow-downloads`), donc cette navigation était systématiquement
bloquée par le navigateur, silencieusement.

CE QUI CHANGE
--------------
Ce module utilise maintenant `components.declare_component(...)`, le vrai
mécanisme bidirectionnel officiel de Streamlit. Le composant HTML/JS (voir
`phone_auth_component/index.html`) envoie sa valeur via
`window.parent.postMessage(...)` (protocole reconstruit à partir du code
source réel du package npm `streamlit-component-lib`, pas deviné) — ce
mécanisme ne nécessite PAS la permission de sandbox qui manquait, donc il
fonctionne dans n'importe quelle iframe Streamlit.

À FAIRE DANS LA CONSOLE FIREBASE (une fois) :
1. Authentication → Sign-in method → active "Téléphone"
2. Authentication → Settings → Domaines autorisés : ajoute "localhost" (déjà
   présent par défaut) et le domaine de production si tu déploies ailleurs.
3. Le quota gratuit SMS est limité (~10/jour en test) — au-delà, Firebase
   facture les SMS. Vérifie les tarifs sur la console si usage réel prévu.

⚠️ Cette fonctionnalité nécessite un vrai navigateur pour être testée
(reCAPTCHA + réception SMS réelle) — je ne peux pas la tester de bout en
bout depuis mon environnement de travail (pas de téléphone réel), donc
teste-la en conditions réelles après déploiement et dis-moi si le
comportement diffère de ce qui est documenté ici.
"""

from pathlib import Path

import streamlit.components.v1 as components

from firebase_config import FIREBASE_API_KEY, FIREBASE_AUTH_DOMAIN, FIREBASE_PROJECT_ID

_COMPONENT_DIR = Path(__file__).parent / "phone_auth_component"
_phone_auth_component = components.declare_component("phone_auth", path=str(_COMPONENT_DIR))


def render_phone_auth_widget(height: int = 320, key: str = "phone_auth_widget"):
    """
    Affiche le widget de connexion par téléphone.

    Renvoie None tant que rien n'est vérifié, ou un dict
    {"idToken": str, "phoneNumber": str} une fois le code SMS validé côté
    client — à re-vérifier IMPÉRATIVEMENT côté serveur avant d'ouvrir une
    session (voir auth_firebase.verify_id_token, jamais de confiance
    aveugle en ce que le navigateur renvoie).
    """
    firebase_config = {
        "apiKey": FIREBASE_API_KEY,
        "authDomain": FIREBASE_AUTH_DOMAIN,
        "projectId": FIREBASE_PROJECT_ID,
    }
    return _phone_auth_component(firebase_config=firebase_config, height=height, default=None, key=key)
