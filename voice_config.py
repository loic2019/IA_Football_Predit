# -*- coding: utf-8 -*-
"""
voice_config.py — Configuration de la voix du chatbot (reconnaissance +
synthèse vocale), taillée pour bien comprendre le français parlé/familier
congolais (argot, tournures locales, mélange avec le lingala).
==============================================================================
Deux niveaux de reconnaissance vocale (STT), du meilleur au dégradé — l'app
ne casse jamais faute de clé, comme pour ai_config.py :

1. OpenAI Whisper API (clé OPENAI_API_KEY) — nettement plus précis sur le
   français parlé informel/accents/argot que les solutions gratuites, et on
   peut le "biaiser" avec un lexique de termes locaux (CONGO_SLANG_PROMPT
   ci-dessous) pour améliorer la reconnaissance de mots qui n'existent pas
   en français standard.
2. Repli gratuit sans clé : reconnaissance vocale Google (via la librairie
   `SpeechRecognition`, déjà dans requirements.txt) — moins précis sur
   l'argot mais fonctionne sans configuration.

Pour activer le mode précis (recommandé vu que tu veux bien comprendre
l'argot congolais) :
    Windows (PowerShell) : $env:OPENAI_API_KEY="sk-..."
    ou dans .streamlit/secrets.toml :
        OPENAI_API_KEY = "sk-..."
Clé gratuite/payante à la demande sur https://platform.openai.com/api-keys
(Whisper coûte environ 0,006 $/minute audio — quasi négligeable pour un chat).
"""

import os

# ── Lexique pour biaiser la reconnaissance vers le français congolais ──────
# Whisper accepte un "prompt" de contexte qui l'oriente sur l'orthographe et
# le vocabulaire attendus (sans lui interdire d'entendre autre chose). Cette
# liste n'a pas besoin d'être exhaustive : quelques exemples suffisent à
# orienter le modèle sur ce registre de langue plutôt que sur du français
# standard. Complète-la librement avec tes propres expressions courantes.
CONGO_SLANG_PROMPT = (
    "Conversation en français parlé, familier, congolais (Congo-Brazzaville), "
    "avec parfois des mots de lingala mélangés au français : mundele, malamu, "
    "sango nini, awa, yango, mbote, tokoyaka, on va faire comment, ça va aller, "
    "c'est comment, on dit koman, mon vieux, doublage, ambiance, débrouille, "
    "on est ensemble, ça tape, pronostic, cote, coupon, mise."
)

ASSISTANT_VOICE_LANG = "fr"  # langue de la synthèse vocale (gTTS)


def get_openai_key() -> str | None:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        return st.secrets.get("OPENAI_API_KEY")
    except Exception:
        return None


def is_precise_stt_enabled() -> bool:
    """True si la clé OpenAI Whisper est configurée (meilleure précision argot)."""
    return bool(get_openai_key())
