"""views/chatbot.py — Chatbot IA branché sur les données réelles.

MODIFICATION : le chatbot utilise désormais Claude (voir chatbot_ai.py) pour
générer des réponses naturelles, dynamiques et humaines, tout en restant
strictement ancré sur les vraies données de l'app (aucun chiffre inventé —
voir le prompt système dans chatbot_ai.py). Si aucune clé API n'est
configurée (voir ai_config.py), on retombe automatiquement sur l'ancien
système de réponses par mots-clés ci-dessous, pour que l'app ne casse jamais.
"""

from datetime import datetime

import streamlit as st

from common import (
    format_date,
    get_all_matches,
    get_finished_matches_count,
    get_future_matches,
    get_future_matches_count,
    get_live_matches_count,
    get_model_stats,
)
from ai_config import is_ai_enabled, ASSISTANT_NAME


def _answer_fallback(question: str) -> str:
    """Ancien système par mots-clés — utilisé uniquement si aucune clé API IA n'est configurée."""
    q = question.lower().strip()

    if any(k in q for k in ["combien de match", "nombre de match", "total de match"]):
        return f"📦 Il y a actuellement **{get_all_matches():,}** matchs en base de données."

    if "futur" in q or ("prochain" in q and "match" in q):
        future = get_future_matches(5)
        if not future:
            return "🔮 Je n'ai trouvé aucun match futur en base. Lancez le scraping depuis la sidebar."
        lines = []
        for m in future:
            date_display = format_date(m.get("date", ""))
            lines.append(f"- **{m.get('home','')} vs {m.get('away','')}** ({m.get('league','N/A')}) le {date_display}")
        return "🔮 Voici les prochains matchs :\n" + "\n".join(lines)

    if "meilleur" in q and ("pronostic" in q or "prediction" in q or "prédiction" in q):
        return (
            "🎯 Les pronostics sont générés par ton moteur `predictor.py`. "
            "Lance dans un terminal :\n\n"
            "`python predictor.py --analyze` pour voir l'analyse complète, ou\n"
            "`python predictor.py --coupon 8` pour un coupon optimisé."
        )

    if any(k in q for k in ["précision", "precision", "performance", "accuracy", "fiabilité", "fiable"]):
        stats = get_model_stats()
        if not stats:
            return "📊 Aucune statistique de performance n'est disponible pour le moment. Entraînez d'abord le modèle."
        total = stats.get("total_predictions", 0)
        correct = stats.get("correct_predictions", 0)
        acc = (correct / max(1, total)) * 100
        return f"🎯 Le modèle a une précision globale de **{acc:.1f}%** sur **{total:,}** prédictions ({correct:,} correctes)."

    if "direct" in q or "live" in q or "en cours" in q:
        live = get_live_matches_count()
        if live == 0:
            return "🔴 Aucun match en direct actuellement."
        return f"🔴 Il y a **{live}** match(s) en direct en ce moment."

    if any(k in q for k in ["résumé", "resume", "état", "etat", "statut", "situation"]):
        total = get_all_matches()
        future = get_future_matches_count()
        finished = get_finished_matches_count()
        live = get_live_matches_count()
        return (
            f"📊 Voici un résumé de la base :\n"
            f"- 📦 Total : **{total:,}** matchs\n"
            f"- 🔮 Futurs : **{future:,}**\n"
            f"- ✅ Terminés : **{finished:,}**\n"
            f"- 🔴 En direct : **{live:,}**"
        )

    if any(k in q for k in ["aide", "help", "commande", "quoi faire"]):
        return (
            "🤖 Je peux répondre à des questions comme :\n"
            "- *Combien de matchs sont en base ?*\n"
            "- *Quels sont les prochains matchs ?*\n"
            "- *Quel est le meilleur pronostic du moment ?*\n"
            "- *Quelle est la précision du modèle ?*\n"
            "- *Y a-t-il un match en direct ?*\n"
            "- *Fais-moi un résumé*"
        )

    return (
        "🤔 Je n'ai pas bien compris. Essayez de demander : le nombre de matchs, "
        "les prochains matchs, le meilleur pronostic, la précision du modèle, ou tapez "
        "*aide* pour voir ce que je peux faire."
    )


def _generate_reply(user_input: str) -> str:
    """Génère la réponse du bot : IA (Claude) si configurée, sinon fallback par mots-clés."""
    if not is_ai_enabled():
        return _answer_fallback(user_input)

    try:
        from chatbot_ai import get_reply_non_streaming
        return get_reply_non_streaming(st.session_state.chat_messages + [{"role": "user", "content": user_input}])
    except Exception as e:
        return f"⚠️ Le mode IA a rencontré une erreur ({e}), voici une réponse basique à la place :\n\n" + _answer_fallback(user_input)


def render():
    st.title(f"🤖 {ASSISTANT_NAME} — Chatbot IA")
    if is_ai_enabled():
        st.caption("🟢 Mode IA activé (Claude) — réponses naturelles, ancrées sur tes vraies données")
    else:
        st.caption(
            "🟡 Mode basique (mots-clés) — configure ANTHROPIC_API_KEY pour activer les réponses "
            "naturelles et dynamiques (voir ai_config.py)"
        )

    # Historique de conversation
    chat_html = "<div class='chat-container'>"
    for msg in st.session_state.chat_messages:
        role_class = "user" if msg["role"] == "user" else "bot"
        content = msg["content"].replace("\n", "<br>")
        chat_html += (
            f"<div class='chat-msg {role_class}'>{content}"
            f"<div class='chat-time'>{msg['time']}</div></div>"
        )
    chat_html += "</div>"
    st.markdown(chat_html, unsafe_allow_html=True)

    st.markdown("")

    with st.form(key="chat_form", clear_on_submit=True):
        col1, col2 = st.columns([5, 1])
        with col1:
            user_input = st.text_input(
                "Message", placeholder="Posez votre question...", label_visibility="collapsed"
            )
        with col2:
            submitted = st.form_submit_button("Envoyer ➤", width="stretch")

    if submitted and user_input.strip():
        now = datetime.now().strftime("%H:%M")
        st.session_state.chat_messages.append({"role": "user", "content": user_input, "time": now})
        with st.spinner(f"{ASSISTANT_NAME} réfléchit..."):
            reply = _generate_reply(user_input)
        st.session_state.chat_messages.append({"role": "bot", "content": reply, "time": now})
        st.rerun()

    st.markdown("---")
    cols = st.columns(4)
    quick_questions = [
        "Combien de matchs en base ?",
        "Prochains matchs ?",
        "Meilleur pronostic ?",
        "Précision du modèle ?",
    ]
    for col, question in zip(cols, quick_questions):
        if col.button(question, width="stretch"):
            now = datetime.now().strftime("%H:%M")
            st.session_state.chat_messages.append({"role": "user", "content": question, "time": now})
            with st.spinner(f"{ASSISTANT_NAME} réfléchit..."):
                reply = _generate_reply(question)
            st.session_state.chat_messages.append({"role": "bot", "content": reply, "time": now})
            st.rerun()

    if st.button("🗑️ Effacer la conversation"):
        st.session_state.chat_messages = [
            {
                "role": "bot",
                "content": f"👋 Conversation réinitialisée. Comment puis-je t'aider ?",
                "time": datetime.now().strftime("%H:%M"),
            }
        ]
        st.rerun()
