"""
ai_config.py — Configuration du chatbot IA (Claude/Anthropic OU Groq)
==============================================================================
⚠️ Une clé API est un SECRET : ne la mets JAMAIS en dur dans le code, ne la
commit jamais dans un dépôt Git. Ce module la lit dans cet ordre de priorité
pour chaque fournisseur :

1. Variable d'environnement (ANTHROPIC_API_KEY ou GROQ_API_KEY)
2. st.secrets["..."] (fichier .streamlit/secrets.toml, jamais commité)

DEUX FOURNISSEURS POSSIBLES
-------------------------
- **Groq** (gratuit, très rapide, modèles open-source comme Llama) — priorité
  si sa clé est configurée. Clé sur https://console.groq.com/keys (gratuit,
  pas de carte bancaire requise).
- **Anthropic/Claude** (payant à l'usage, qualité de pointe) — utilisé si pas
  de clé Groq mais une clé Anthropic est configurée.
     https://console.anthropic.com → Settings → API Keys → Create Key

COMMENT CONFIGURER (au choix, l'un ou l'autre, ou les deux) :
   Windows (PowerShell) : $env:GROQ_API_KEY="gsk_..."
   Windows (cmd)        : set GROQ_API_KEY=gsk_...
   Linux/Mac            : export GROQ_API_KEY="gsk_..."
   Puis : streamlit run app_dashboard.py

   Ou fichier `.streamlit/secrets.toml` (à la racine du projet) :
     GROQ_API_KEY = "gsk_..."
     ANTHROPIC_API_KEY = "sk-ant-..."
   (ajoute `.streamlit/secrets.toml` à ton .gitignore !)

Sans aucune clé configurée, le chatbot bascule automatiquement sur son ancien
mode "réponses par mots-clés" (voir chatbot.py) — l'app ne plante jamais
faute de clé.
"""

import os

MODEL_NAME = "claude-sonnet-5"
MAX_TOKENS = 700
ASSISTANT_NAME = "Max"  # nom du chatbot, utilisé dans le persona

# Modèle Groq utilisé — llama-3.3-70b-versatile est le meilleur compromis
# gratuit actuel pour le français informel/argot. Si Groq déprécie ce nom de
# modèle, la liste à jour est sur https://console.groq.com/docs/models
GROQ_MODEL = "llama-3.3-70b-versatile"

# Historique de conversation envoyé au modèle (nombre de messages max, pour
# limiter les coûts/latence tout en gardant du contexte)
MAX_HISTORY_MESSAGES = 16


def get_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key

    try:
        import streamlit as st
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None


def get_groq_key() -> str | None:
    key = os.environ.get("GROQ_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        return st.secrets.get("GROQ_API_KEY")
    except Exception:
        return None


def get_active_provider() -> str | None:
    """Groq en priorité (gratuit) si configuré, sinon Anthropic si configuré,
    sinon None (mode basique par mots-clés)."""
    if get_groq_key():
        return "groq"
    if get_api_key():
        return "anthropic"
    return None


def is_ai_enabled() -> bool:
    return get_active_provider() is not None
