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

from ai_config import (
    get_api_key,
    get_groq_key,
    get_active_provider,
    MODEL_NAME,
    GROQ_MODEL,
    MAX_TOKENS,
    ASSISTANT_NAME,
    MAX_HISTORY_MESSAGES,
)
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
- Tu es un compagnon de conversation à part entière, pas un simple assistant borné à
  l'application : réponds naturellement à N'IMPORTE QUELLE question (culture générale,
  actualité, conseils, discussion, blagues...), exactement comme le ferait un ami calé
  en foot et en data. Ne dis jamais "je ne peux répondre qu'aux questions sur l'app".
- Phrases variées, pas de formules toutes faites répétées à chaque message.
- Tu utilises "tu", jamais de formules trop formelles ni de jargon d'entreprise.
- Tu peux poser une question de relance de temps en temps si ça a du sens (pas systématique).
- Emojis avec modération (0 à 2 par message), jamais dans chaque phrase.
- Réponses concises par défaut (3 à 6 phrases), plus long seulement si la question l'exige
  (ex: liste de plusieurs matchs).

ACTIONS DISPONIBLES (très important) :
- Tu n'es pas juste là pour répondre : tu peux AGIR réellement sur l'application, comme
  si l'utilisateur naviguait lui-même dans chaque page.
- lancer_cycle_complet : scraping de toutes les sources + entraînement + nouveaux
  pronostics + sauvegarde + règlement automatique. Utilise-le pour "scrape", "rafraîchis",
  "mets à jour", "relance tout", "entraîne le modèle".
- enregistrer_coupon_du_jour : sauvegarde le coupon recommandé actuellement.
- regler_coupons_maintenant : vérifie/règle les tickets en attente sans tout relancer.
- marquer_notifications_lues : marque les notifications comme lues.
- publier_message_salon : publie un message dans le salon communautaire (UNIQUEMENT si
  l'utilisateur a donné un message précis à publier).
- consulter_stats_globales : chiffres précis et à jour sur les performances.
- Dès qu'une demande correspond à une de ces actions, utilise l'outil directement plutôt
  que d'expliquer comment le faire manuellement dans l'interface.
- Une fois l'action exécutée, annonce le résultat clairement et simplement, sans jargon technique.

RÈGLES SUR LES DONNÉES DE L'APP (non négociables, s'applique uniquement aux
chiffres de CongoBet AI — pas aux questions de culture générale) :
- Tu ne dois JAMAIS inventer un chiffre, un score, une cote ou une statistique
  qui concerne l'application (matchs, pronostics, coupons, précision du modèle).
- Utilise UNIQUEMENT les données du bloc CONTEXTE ci-dessous pour tout ce qui est
  factuel sur l'app (nombre de matchs, cotes, confiance, précision du modèle, etc.).
- Si l'information demandée sur l'app n'est pas dans le CONTEXTE, dis-le honnêtement
  et propose une alternative (ex: "lance un scraping", "va voir la page Pronostics")
  plutôt que d'inventer une réponse.
- Pour toute question qui NE concerne PAS l'app, réponds normalement avec tes
  connaissances générales, sans cette contrainte.
- Tu n'es pas un conseiller financier : si on te demande de garantir un gain,
  rappelle avec légèreté que les paris comportent toujours un risque.

CONTEXTE ACTUEL (données réelles de l'application, à jour à l'instant) :
{context}
"""


TOOLS = [
    {
        "name": "lancer_cycle_complet",
        "description": (
            "Lance immédiatement le cycle complet de l'application : scraping de TOUTES les "
            "sources (Congobet, 1xBet, Premierbet), entraînement des modèles sur les données "
            "les plus récentes, génération des nouveaux pronostics, sauvegarde du coupon du "
            "jour et règlement automatique des coupons passés dont les matchs sont terminés. "
            "C'est l'action à utiliser dès que l'utilisateur veut des données à jour, de "
            "nouveaux pronostics, ou dit des choses comme 'scrape', 'rafraîchis', 'mets à "
            "jour', 'relance tout', 'entraîne le modèle'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "enregistrer_coupon_du_jour",
        "description": (
            "Enregistre (sauvegarde) le coupon de pronostics actuellement recommandé dans "
            "l'historique des tickets/coupons, pour qu'il soit suivi et réglé automatiquement "
            "une fois les matchs terminés. Utilise cet outil quand l'utilisateur demande "
            "d'enregistrer, de sauvegarder ou de valider un ticket/coupon/pari."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "regler_coupons_maintenant",
        "description": (
            "Vérifie les coupons/tickets en attente et règle ceux dont tous les matchs sont "
            "terminés (gagné/perdu), sans relancer tout le cycle de scraping. Utilise cet "
            "outil quand l'utilisateur demande de vérifier ses résultats, de régler ses "
            "tickets, ou de savoir s'il a gagné."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "marquer_notifications_lues",
        "description": "Marque toutes les notifications de l'utilisateur comme lues.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "publier_message_salon",
        "description": (
            "Publie un message au nom de l'utilisateur dans le salon public de la Communauté. "
            "N'utilise cet outil QUE si l'utilisateur a explicitement demandé de publier/poster "
            "ce message précis dans le salon/la communauté — jamais de ta propre initiative."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "Contenu exact du message à publier"}},
            "required": ["message"],
        },
    },
    {
        "name": "consulter_stats_globales",
        "description": (
            "Récupère les statistiques précises et à jour : précision du modèle, nombre de "
            "coupons gagnés/perdus, taux de réussite global. Utilise cet outil pour toute "
            "question chiffrée précise sur les performances, plutôt que d'estimer."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _tools_openai_format() -> list[dict]:
    """Convertit TOOLS (format Anthropic) au format attendu par l'API OpenAI-
    compatible de Groq : {"type": "function", "function": {name, description,
    parameters}} au lieu de {name, description, input_schema}."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOLS
    ]


def _current_user_id():
    try:
        import streamlit as st
        profile = st.session_state.get("user_profile")
        return profile.get("id") if profile else None
    except Exception:
        return None


def _execute_tool(tool_name: str, tool_input: dict | None = None) -> str:
    """Exécute une action réelle demandée par Claude et retourne un résultat texte
    (jamais d'exception non gérée : toute erreur est renvoyée comme texte, pour que
    le modèle puisse la reformuler proprement à l'utilisateur)."""
    tool_input = tool_input or {}
    try:
        if tool_name == "lancer_cycle_complet":
            from common import run_auto_cycle

            result = run_auto_cycle(force=True)
            if not result.get("ran", True) and result.get("reason") == "not_due":
                return "Un cycle vient déjà de tourner récemment, pas besoin d'en relancer un pour l'instant."
            training = result.get("training", {})
            prediction = result.get("prediction", {})
            settle = result.get("coupon_tracking", {}).get("settle", {})
            return (
                f"Cycle complet terminé : scraping de toutes les sources effectué, "
                f"entraînement sur {training.get('samples', training.get('n_samples', '?'))} matchs, "
                f"{prediction.get('prediction_count', 0)} pronostics générés, "
                f"coupon du jour de {prediction.get('coupon_size', 0)} sélection(s) "
                f"(cote totale {prediction.get('coupon_total_cote', 0):.2f}), "
                f"{settle.get('settled', 0)} coupon(s) réglé(s) au passage."
            )

        if tool_name == "enregistrer_coupon_du_jour":
            from common import run_prediction_pipeline
            from coupon_tracker import save_daily_coupon

            snapshot = run_prediction_pipeline(limit=200, min_confidence=0.0, min_cote=1.30)
            coupon = snapshot.get("coupon", {})
            if not coupon.get("selections"):
                return "Aucune sélection ne passe le seuil de confiance actuel : rien à enregistrer pour l'instant."
            result = save_daily_coupon(coupon, force=True)
            if result.get("saved"):
                return (
                    f"Coupon enregistré avec succès (id {result['coupon_id']}), "
                    f"{len(coupon['selections'])} sélection(s), cote totale {coupon.get('total_cote', 0):.2f}. "
                    "Il sera réglé automatiquement une fois les matchs terminés."
                )
            return f"Non enregistré : {result.get('reason', 'raison inconnue')}."

        if tool_name == "regler_coupons_maintenant":
            from coupon_tracker import settle_pending_coupons

            result = settle_pending_coupons()
            settled = result.get("settled", 0)
            still_pending = result.get("still_pending", 0)
            if settled == 0:
                return (
                    "Aucun coupon en attente n'a pu être réglé pour l'instant "
                    f"({still_pending} en attente, matchs pas encore tous terminés)."
                )
            return (
                f"{settled} coupon(s) réglé(s) avec succès "
                f"({still_pending} restent en attente, matchs pas encore tous terminés). "
                "Détail disponible dans l'historique des coupons."
            )

        if tool_name == "marquer_notifications_lues":
            import community_db

            user_id = _current_user_id()
            if not user_id:
                return "Impossible d'identifier l'utilisateur connecté pour marquer ses notifications."
            community_db.mark_notifications_read(user_id)
            return "Toutes les notifications ont été marquées comme lues."

        if tool_name == "publier_message_salon":
            import community_db

            user_id = _current_user_id()
            message = tool_input.get("message", "").strip()
            if not user_id:
                return "Impossible d'identifier l'utilisateur connecté pour publier ce message."
            if not message:
                return "Aucun contenu de message fourni."
            community_db.post_public_message(user_id, message)
            return f"Message publié dans le salon public : « {message} »"

        if tool_name == "consulter_stats_globales":
            from coupon_tracker import get_global_stats

            model_stats = get_model_stats() or {}
            g = get_global_stats() or {}
            acc = (model_stats.get("correct_predictions", 0) / max(1, model_stats.get("total_predictions", 1))) * 100
            coupon_accuracy = f"{g['accuracy'] * 100:.1f}%" if g.get("accuracy") is not None else "pas encore assez de données"
            roi = f"{g['avg_roi'] * 100:+.1f}%" if g.get("avg_roi") is not None else "N/A"
            return (
                f"Modèle : {model_stats.get('total_predictions', 0)} prédictions faites, précision {acc:.1f}%. "
                f"Coupons réglés : {g.get('coupons_settled', 0)}, "
                f"{g.get('matches_correct', 0)}/{g.get('matches_total', 0)} pronostics corrects "
                f"({coupon_accuracy}), ROI moyen {roi}."
            )

        return f"Outil inconnu : {tool_name}"
    except Exception as e:
        return f"Erreur pendant l'exécution de l'action : {e}"


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
    Générateur de texte (pour st.write_stream) : appelle le fournisseur actif
    (Groq ou Claude) en streaming. `chat_messages` = st.session_state.chat_messages,
    le dernier message doit être celui de l'utilisateur.
    """
    provider = get_active_provider()

    if provider == "groq":
        from openai import OpenAI

        client = OpenAI(api_key=get_groq_key(), base_url="https://api.groq.com/openai/v1")
        messages = [{"role": "system", "content": get_system_prompt()}] + _to_anthropic_messages(chat_messages)
        stream = client.chat.completions.create(
            model=GROQ_MODEL, max_tokens=MAX_TOKENS, messages=messages, stream=True
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
        return

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
    """Alternative sans streaming (utile pour les boutons de questions rapides
    et le vocal). Gère la boucle d'outils (tool use) : si le modèle demande à
    exécuter une action réelle (scraper, enregistrer un coupon...), on
    l'exécute puis on renvoie le résultat pour qu'il formule sa réponse finale."""
    if get_active_provider() == "groq":
        return _get_reply_groq(chat_messages)
    return _get_reply_anthropic(chat_messages)


def _get_reply_anthropic(chat_messages: list[dict]) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=get_api_key())
    messages = _to_anthropic_messages(chat_messages)

    for _ in range(4):  # limite de sécurité anti-boucle infinie
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=MAX_TOKENS,
            system=get_system_prompt(),
            messages=messages,
            tools=TOOLS,
        )

        if response.stop_reason != "tool_use":
            return "".join(block.text for block in response.content if block.type == "text")

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result_text = _execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })
        messages.append({"role": "user", "content": tool_results})

    return "Désolé, je n'ai pas réussi à finaliser cette action, réessaie ou reformule ta demande."


def _get_reply_groq(chat_messages: list[dict]) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=get_groq_key(), base_url="https://api.groq.com/openai/v1")
    messages = [{"role": "system", "content": get_system_prompt()}] + _to_anthropic_messages(chat_messages)
    tools = _tools_openai_format()

    for _ in range(4):  # limite de sécurité anti-boucle infinie
        response = client.chat.completions.create(
            model=GROQ_MODEL, max_tokens=MAX_TOKENS, messages=messages, tools=tools
        )
        message = response.choices[0].message

        if response.choices[0].finish_reason != "tool_calls" or not message.tool_calls:
            return message.content or ""

        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ],
        })
        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            result_text = _execute_tool(tc.function.name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_text})

    return "Désolé, je n'ai pas réussi à finaliser cette action, réessaie ou reformule ta demande."
