"""
firebase_config.py — Configuration Firebase pour l'authentification CongoBet AI
=================================================================================
Projet Firebase DÉDIÉ à CongoBet AI : congobet-71479.
Aucun partage avec d'autres apps (livraison de repas, etc.).

Note : une "apiKey" Firebase Web est publique par conception (elle identifie le
projet, elle ne donne aucun accès sans passer par les règles de sécurité
Auth/Firestore). Ce n'est PAS un secret à cacher — mais ne mets jamais ici une
clé de compte de service (celle-là oui, doit rester privée, et n'est pas
utilisée dans ce projet : on passe uniquement par l'API REST Identity Toolkit).

Utilisation : Firebase gère UNIQUEMENT l'authentification (email/mot de passe).
Toutes les données applicatives (profils, stats, messages entre parieurs)
restent en SQLite local (community.db), séparées de congobet.db.
"""

FIREBASE_API_KEY = "AIzaSyA5Ba7PDplTmzj75lR4-GNyK8jZJ6kIkp4"
FIREBASE_AUTH_DOMAIN = "congobet-71479.firebaseapp.com"
FIREBASE_PROJECT_ID = "congobet-71479"

# Endpoints Identity Toolkit (API REST Firebase Auth — aucun SDK JS nécessaire,
# ça fonctionne très bien depuis un backend Python/Streamlit).
IDENTITY_TOOLKIT_BASE = "https://identitytoolkit.googleapis.com/v1/accounts"
SECURE_TOKEN_BASE = "https://securetoken.googleapis.com/v1/token"
