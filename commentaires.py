# -*- coding: utf-8 -*-
"""
commentaires.py — Commentaires publics sous chaque match / pronostic
=======================================================================
Même esprit que communaute.py (salon public), mais rattaché à un match_id
précis plutôt qu'à un salon global. Stocké dans community.db, table
`match_comments` (voir community_db.py).

Utilisation depuis pronostics.py (ou toute page qui affiche une carte de
match) :

    from commentaires import render_match_comments
    render_match_comments(match_id=pred["id"], profile=profile)

`profile` peut être None si l'utilisateur n'est pas connecté : dans ce cas
les commentaires existants restent visibles (lecture publique), mais l'ajout
est désactivé avec une invite à se connecter — cohérent avec le reste de
l'app (voir profil.py).
"""

import streamlit as st

import community_db
from community_db import avatar_html, is_user_admin


def render_match_comments(match_id: str, profile: dict | None, expanded: bool = False):
    """Affiche le fil de commentaires d'un match donné + formulaire d'ajout."""
    count = community_db.count_comments(match_id)
    label = f"💬 Commentaires ({count})" if count else "💬 Commentaires"

    with st.expander(label, expanded=expanded):
        comments = community_db.list_comments(match_id)

        if not comments:
            st.caption("Aucun commentaire pour l'instant — sois le premier à donner ton avis !")
        else:
            for c in comments:
                avatar_small = avatar_html(
                    {"avatar_emoji": c["avatar_emoji"], "avatar_image_b64": c.get("avatar_image_b64")},
                    size=26,
                )
                st.markdown(
                    f"""
                    <div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:10px;">
                        {avatar_small}
                        <div style="flex:1;">
                            <div style="font-size:12px;color:rgba(232,236,255,0.6);">
                                <b>{c['pseudo']}</b> · {c['created_at'][11:16]}
                            </div>
                            <div style="background:rgba(255,255,255,0.05);padding:6px 12px;
                                        border-radius:10px;margin-top:2px;">{c['content']}</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                # Bouton de suppression pour l'auteur ou un admin.
                if profile and (c["user_id"] == profile["id"] or is_user_admin(profile["id"])):
                    if st.button("🗑️ Supprimer", key=f"del_comment_{c['id']}"):
                        community_db.delete_comment(c["id"], profile["id"])
                        st.rerun()

        st.divider()

        if not profile:
            st.info("🔒 Connecte-toi depuis la page **Profil** pour commenter.")
            return

        with st.form(f"comment_form_{match_id}", clear_on_submit=True):
            content = st.text_input(
                "Ton avis sur ce match",
                label_visibility="collapsed",
                placeholder="Ton avis, ton analyse, ta cote préférée...",
            )
            sent = st.form_submit_button("Publier")
            if sent and content.strip():
                community_db.add_comment(match_id, profile["id"], content)
                st.rerun()
