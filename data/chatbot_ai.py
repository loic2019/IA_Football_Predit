"""
chatbot_ai.py — Cerveau du chatbot : contexte réel + génération via Claude
==============================================================================
Principe : on ne laisse JAMAIS le modèle inventer des chiffres. On récupère
d'abord les vraies données (common.py, predictions_history.json), on les
injecte dans le prompt système sous forme de contexte structuré, et on
demande explicitement au modèle de ne citer que ces chiffres-là. Le style de
réponse (naturel, humain, dynamique) est géré par le persona du prompt
système — pas en sacrifiant l'exactitude des données.

Utilise le SDK officiel `anthropic` (pip install anthropic).
"""

import json
from datetime import datetime

from ai_config import get_api_key, MODEL_NAME, MAX_TOKENS, ASSISTANT_NAME, MAX_HISTORY_MESSAGES
from common import (
    get_all_matches,
    get_finished_matches_count,
    get_future_matches,
    get_future_matches_count,
    get_live_matches,
    get_live_matches_count,
    get_model_stats,
    PREDICTIONS_PATH,
)


def _load_latest_predictions(limit: int = 8) -> list[dict]:
    if not PREDICTIONS_PATH.exists():
        return []
    try:
        with open(PREDICTIONS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("predictions", [])[:limit]
    except Exception:
        return []


def build_context_block() -> str:
    """Construit un bloc de contexte texte à partir des VRAIES données de l'app."""
    total = get_all_matches()
    future = get_future_matches_count()
    finished = get_finished_matches_count()
    live = get_live_matches_count()
    stats = get_model_stats() or {}

    lines = [
        f"Horodatage actuel : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Matchs en base : {total} au total, {live} en direct, {future} à venir, {finished} terminés.",
    ]

    if stats:
        acc = (stats.get("correct_predictions", 0) / max(1, stats.get("total_predictions", 1))) * 100
        lines.append(
            f"Modèle de prédiction : {stats.get('total_predictions', 0)} prédictions faites au total, "
            f"précision globale {acc:.1f}%."
        )
    else:
        lines.append("Modèle de prédiction : pas encore de statistiques disponibles (aucun entraînement effectué).")

    live_matches = get_live_matches(5)
    if live_matches:
        lines.append("Matchs en direct actuellement :")
        for m in live_matches:
            lines.append(f"  - {m.get('home','?')} vs {m.get('away','?')} ({m.get('league','N/A')})")

    future_matches = get_future_matches(5)
    if future_matches:
        lines.append("Prochains matchs (5 premiers) :")
        for m in future_matches:
            lines.append(f"  - {m.get('home','?')} vs {m.get('away','?')} ({m.get('league','N/A')}) le {m.get('date','?')}")

    predictions = _load_latest_predictions(8)
    if predictions:
        lines.append("Derniers pronostics générés par predictor.py (les seuls chiffres de confiance/cote valides) :")
        for p in predictions:
            lines.append(
                f"  - {p.get('home','?')} vs {p.get('away','?')} : pronostic {p.get('prediction','?')}, "
                f"confiance {p.get('confidence',0):.0%}, cote {p.get('cote',0):.2f}"
            )
    else:
        lines.append("Aucun pronostic généré récemment (va sur la page Pronostics pour en générer).")

    return "\n".join(lines)


SYSTEM_PROMPT_TEMPLATE = """Tu es {name}, l'assistant conversationnel de CongoBet AI, une application
d'analyse de paris sportifs football. Tu discutes avec un parieur via un chat.

TON STYLE (très important) :
- Tu parles comme un vrai passionné de football, pas comme un robot. Ton dynamique,
  naturel, chaleureux, parfois un brin d'humour ou d'enthousiasme quand c'est pertinent
  (un bon value bet, un match qui s'annonce serré, etc.).
- Phrases variées, pas de formules toutes faites répétées à chaque message.
- Tu utilises "tu", jamais de formules trop formelles ni de jargon d'entreprise.
- Tu peux poser une question de relance de temps en temps si ça a du sens (pas systématique).
- Emojis avec modération (0 à 2 par message), jamais dans chaque phrase.
- Réponses concises par défaut (3 à 6 phrases), plus long seulement si la question l'exige
  (ex: liste de plusieurs matchs).

RÈGLES SUR LES DONNÉES (non négociables) :
- Tu ne dois JAMAIS inventer un chiffre, un score, une cote ou une statistique.
- Utilise UNIQUEMENT les données du bloc CONTEXTE ci-dessous pour tout ce qui est
  factuel (nombre de matchs, cotes, confiance, précision du modèle, etc.).
- Si l'information demandée n'est pas dans le CONTEXTE, dis-le honnêtement et
  propose une alternative (ex: "lance un scraping depuis la sidebar", "va voir
  la page Pronostics") plutôt que d'inventer une réponse.
- Tu n'es pas un conseiller financier : si on te demande de garantir un gain,
  rappelle avec légèreté que les paris comportent toujours un risque.

CONTEXTE ACTUEL (données réelles de l'application, à jour à l'instant) :
{context}
"""


def get_system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(name=ASSISTANT_NAME, context=build_context_block())


def _to_anthropic_messages(chat_messages: list[dict]) -> list[dict]:
    """Convertit st.session_state.chat_messages (role: user/bot) au format API (user/assistant)."""
    trimmed = chat_messages[-MAX_HISTORY_MESSAGES:]
    result = []
    for m in trimmed:
        role = "user" if m["role"] == "user" else "assistant"
        result.append({"role": role, "content": m["content"]})
    return result


def stream_reply(chat_messages: list[dict]):
    """
    Générateur de texte (pour st.write_stream) : appelle Claude en streaming.
    `chat_messages` = st.session_state.chat_messages, le dernier message doit
    être celui de l'utilisateur.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=get_api_key())
    messages = _to_anthropic_messages(chat_messages)

    with client.messages.stream(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=get_system_prompt(),
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


def get_reply_non_streaming(chat_messages: list[dict]) -> str:
    """Alternative sans streaming (utile pour les boutons de questions rapides)."""
    import anthropic

    client = anthropic.Anthropic(api_key=get_api_key())
    messages = _to_anthropic_messages(chat_messages)

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=get_system_prompt(),
        messages=messages,
    )
    return "".join(block.text for block in response.content if block.type == "text")
