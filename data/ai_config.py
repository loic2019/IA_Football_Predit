"""
ai_config.py — Configuration du chatbot IA (Claude, via l'API Anthropic)
==============================================================================
⚠️ Contrairement à la clé Firebase (publique par conception), une clé API
Anthropic est un SECRET : ne la mets JAMAIS en dur dans le code, ne la commit
jamais dans un dépôt Git. Ce module la lit dans cet ordre de priorité :

1. Variable d'environnement ANTHROPIC_API_KEY
2. st.secrets["ANTHROPIC_API_KEY"] (fichier .streamlit/secrets.toml, jamais commité)

COMMENT OBTENIR UNE CLÉ
-------------------------
1. https://console.anthropic.com → Settings → API Keys → Create Key
2. Soit tu l'exportes en variable d'environnement avant de lancer Streamlit :
     Windows (PowerShell) : $env:ANTHROPIC_API_KEY="sk-ant-..."
     Windows (cmd)        : set ANTHROPIC_API_KEY=sk-ant-...
     Linux/Mac            : export ANTHROPIC_API_KEY="sk-ant-..."
   Puis : streamlit run app_dashboard.py
3. Soit tu crées un fichier `.streamlit/secrets.toml` (à la racine du projet) :
     ANTHROPIC_API_KEY = "sk-ant-..."
   (ajoute `.streamlit/secrets.toml` à ton .gitignore !)

Sans clé configurée, le chatbot bascule automatiquement sur son ancien mode
"réponses par mots-clés" (voir chatbot.py) — l'app ne plante jamais faute de clé.
"""

import os

MODEL_NAME = "claude-sonnet-5"
MAX_TOKENS = 700
ASSISTANT_NAME = "Max"  # nom du chatbot, utilisé dans le persona

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


def is_ai_enabled() -> bool:
    return bool(get_api_key())
