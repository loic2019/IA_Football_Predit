# -*- coding: utf-8 -*-
"""
voice_io.py — Transcription (voix -> texte) et synthèse (texte -> voix) pour
le chatbot "Max".
==============================================================================
transcribe_audio(audio_bytes) :
    1. Si OPENAI_API_KEY configurée -> Whisper API, biaisé avec le lexique
       congolais (voir voice_config.CONGO_SLANG_PROMPT) pour une bien
       meilleure reconnaissance de l'argot/tournures locales.
    2. Sinon -> repli gratuit sans clé (Google Speech Recognition via la
       librairie `SpeechRecognition`), moins précis mais fonctionnel.

synthesize_speech(text) :
    Génère un audio MP3 de la réponse du bot via gTTS (gratuit, aucune clé).
"""

from __future__ import annotations

import io

from voice_config import get_openai_key, is_precise_stt_enabled, CONGO_SLANG_PROMPT, ASSISTANT_VOICE_LANG


def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcrit un enregistrement audio (bytes WAV, tel que renvoyé par
    st.audio_input) en texte français. Ne lève jamais d'exception : retourne
    une chaîne vide en cas d'échec, à afficher comme message d'erreur côté UI.
    """
    if not audio_bytes:
        return ""

    if is_precise_stt_enabled():
        try:
            return _transcribe_whisper(audio_bytes)
        except Exception as e:
            # Ne bloque pas l'utilisateur : on retente le repli gratuit.
            print(f"⚠️ Whisper API indisponible ({e}), repli sur reconnaissance gratuite.")

    return _transcribe_free(audio_bytes)


def _transcribe_whisper(audio_bytes: bytes) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=get_openai_key())
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "message.wav"  # l'API se base sur l'extension pour le format

    result = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language="fr",
        prompt=CONGO_SLANG_PROMPT,
    )
    return (result.text or "").strip()


def _transcribe_free(audio_bytes: bytes) -> str:
    import speech_recognition as sr

    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
            audio = recognizer.record(source)
        return recognizer.recognize_google(audio, language="fr-FR").strip()
    except sr.UnknownValueError:
        return ""
    except Exception as e:
        print(f"⚠️ Reconnaissance vocale gratuite indisponible : {e}")
        return ""


def synthesize_speech(text: str) -> bytes | None:
    """Génère un MP3 de la réponse du bot à voix haute. Retourne None en cas
    d'échec (ex: pas de connexion internet) — l'UI doit alors se contenter
    d'afficher la réponse en texte, sans planter.
    """
    if not text or not text.strip():
        return None
    try:
        from gtts import gTTS

        buf = io.BytesIO()
        gTTS(text=text, lang=ASSISTANT_VOICE_LANG).write_to_fp(buf)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        print(f"⚠️ Synthèse vocale indisponible : {e}")
        return None
