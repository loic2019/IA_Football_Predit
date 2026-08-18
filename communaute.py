"""
communaute.py — Salon public + messagerie privée façon Messenger
========================================================================
Nécessite d'être connecté (voir profil.py). Les messages sont stockés dans
community.db (jamais dans congobet.db).

Messagerie privée redesignée façon Messenger/Facebook : liste de conversations
à gauche (avatar + dernier message), fil de discussion actif à droite.

Note sur le "temps réel" : Streamlit ne pousse pas les mises à jour tout seul.
Un bouton "🔄 Actualiser" + rechargement après envoi suffisent pour un salon
de discussion (pas besoin de forcer un reload de page, qui a déjà causé des
problèmes de stabilité ailleurs dans ce dashboard).
"""

import streamlit as st

import community_db
import common
from community_db import avatar_html, is_user_admin


def _require_login():
    st.title("💬 Communauté des parieurs")
    st.info("🔒 Connecte-toi depuis la page **Profil** pour accéder au salon et à la messagerie.")


def _render_public_chat(profile):
    st.markdown("#### 📢 Salon public")
    st.caption("Visible par tous les parieurs connectés.")

    community_db.mark_public_read(profile["id"])

    if st.button("🔄 Actualiser le salon", key="refresh_public"):
        st.rerun()

    messages = community_db.list_public_messages(limit=200)
    with st.container(height=420):
        for m in messages:
            is_me = m["pseudo"] == profile["pseudo"]
            is_announcement = bool(m.get("is_announcement"))
            align = "flex-end" if is_me else "flex-start"
            row_dir = "row-reverse" if is_me else "row"

            if is_announcement:
                bg = "rgba(245,196,81,0.18)"
                border = "border:1px solid rgba(245,196,81,0.4);"
                prefix = "📌 <b>Annonce officielle</b><br>"
            else:
                bg = "rgba(51,199,255,0.2)" if is_me else "rgba(255,255,255,0.05)"
                border = ""
                prefix = ""

            avatar_small = avatar_html({"avatar_emoji": m["avatar_emoji"], "avatar_image_b64": m.get("avatar_image_b64")}, size=28)
            st.markdown(
                f"""
                <div style="display:flex;flex-direction:{row_dir};align-items:flex-end;gap:8px;margin-bottom:10px;">
                    {avatar_small}
                    <div style="display:flex;flex-direction:column;align-items:{align};max-width:75%;">
                        <div style="font-size:11px;color:rgba(232,236,255,0.6);margin-bottom:2px;">{m['pseudo']} · {m['created_at'][11:16]}</div>
                        <div style="background:{bg};{border}padding:8px 14px;border-radius:14px;">{prefix}{m['content']}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        if not messages:
            st.caption("Aucun message pour l'instant — sois le premier à écrire !")

    is_admin = is_user_admin(profile["id"])
    with st.form("public_message_form", clear_on_submit=True):
        content = st.text_input("Ton message", label_visibility="collapsed", placeholder="Écris un message au salon...")
        as_announcement = st.checkbox("📌 Poster en tant qu'annonce officielle", value=False) if is_admin else False
        sent = st.form_submit_button("Envoyer", width="stretch")
        if sent and content.strip():
            community_db.post_public_message(profile["id"], content, is_announcement=as_announcement)
            st.rerun()


def _conversation_row_html(user, preview: str, is_active: bool, unread: int = 0) -> str:
    bg = "rgba(51,199,255,0.12)" if is_active else "transparent"
    badge = (
        f'<span style="background:var(--accent);color:#04121f;font-size:11px;font-weight:700;'
        f'border-radius:10px;padding:1px 7px;">{unread}</span>'
        if unread else ""
    )
    return f"""
        <div style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:10px;background:{bg};margin-bottom:4px;">
            {avatar_html(user, size=40)}
            <div style="overflow:hidden;flex:1;">
                <div style="font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{user['pseudo']}</div>
                <div style="font-size:12px;color:rgba(232,236,255,0.55);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:180px;">{preview or "Nouvelle conversation"}</div>
            </div>
            {badge}
        </div>
    """


def _render_direct_messages(profile):
    st.markdown("#### ✉️ Messages privés")

    all_users = community_db.list_users(exclude_id=profile["id"])
    if not all_users:
        st.info("Aucun autre parieur inscrit pour l'instant.")
        return

    conversations = community_db.list_conversations(profile["id"])
    known_ids = {c["id"] for c in conversations}
    others_without_history = [
        {**u, "last_at": "", "preview": ""} for u in all_users if u["id"] not in known_ids
    ]
    options = conversations + others_without_history

    if "dm_selected_id" not in st.session_state and options:
        st.session_state.dm_selected_id = options[0]["id"]

    col_list, col_thread = st.columns([1, 2])

    with col_list:
        st.caption("Conversations")
        with st.container(height=440):
            for u in options:
                is_active = st.session_state.get("dm_selected_id") == u["id"]
                st.markdown(_conversation_row_html(u, u.get("preview", ""), is_active, u.get("unread", 0)), unsafe_allow_html=True)
                if st.button("Ouvrir", key=f"open_conv_{u['id']}", width="stretch"):
                    st.session_state.dm_selected_id = u["id"]
                    community_db.mark_dm_read(profile["id"], u["id"])
                    st.rerun()

    with col_thread:
        selected_id = st.session_state.get("dm_selected_id")
        selected_user = next((u for u in options if u["id"] == selected_id), None)

        if not selected_user:
            st.info("Choisis une conversation à gauche.")
            return

        community_db.mark_dm_read(profile["id"], selected_user["id"])

        header_col1, header_col2 = st.columns([4, 1])
        with header_col1:
            st.markdown(
                f"""<div style="display:flex;align-items:center;gap:10px;">
                        {avatar_html(selected_user, size=36)}
                        <span style="font-weight:600;font-size:16px;">{selected_user['pseudo']}</span>
                    </div>""",
                unsafe_allow_html=True,
            )
        with header_col2:
            if st.button("🔄", key="refresh_dm"):
                st.rerun()

        messages = community_db.list_direct_messages(profile["id"], selected_user["id"])
        with st.container(height=360):
            for m in messages:
                is_me = m["sender_id"] == profile["id"]
                align = "flex-end" if is_me else "flex-start"
                bg = "rgba(51,199,255,0.2)" if is_me else "rgba(255,255,255,0.05)"
                st.markdown(
                    f"""
                    <div style="display:flex;flex-direction:column;align-items:{align};margin-bottom:8px;">
                        <div style="font-size:11px;color:rgba(232,236,255,0.55);">{m['created_at'][11:16]}</div>
                        <div style="background:{bg};padding:8px 14px;border-radius:14px;max-width:80%;">{m['content']}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            if not messages:
                st.caption(f"Dis bonjour à {selected_user['pseudo']} 👋")

        with st.form(f"dm_message_form_{selected_user['id']}", clear_on_submit=True):
            content = st.text_input(
                "Message privé", label_visibility="collapsed", placeholder=f"Écrire à {selected_user['pseudo']}..."
            )
            sent = st.form_submit_button("Envoyer", width="stretch")
            if sent and content.strip():
                community_db.send_direct_message(profile["id"], selected_user["id"], content)
                st.rerun()


def render():
    if not common.is_logged_in():
        _require_login()
        return

    profile = common.get_current_profile()
    st.title("💬 Communauté des parieurs")

    tab_public, tab_dm = st.tabs(["📢 Salon public", "✉️ Messages privés"])
    with tab_public:
        _render_public_chat(profile)
    with tab_dm:
        _render_direct_messages(profile)
