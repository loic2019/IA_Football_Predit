"""views/parametres.py — Informations système et configuration."""

import sqlite3

import streamlit as st

from common import DB_PATH, MODEL_PATH, get_db_connection, get_model_stats


def render():
    st.title("⚙️ Paramètres & Diagnostic")
    st.caption("Informations réelles sur l'état de l'application")

    st.markdown("### 💾 Base de données")
    if not DB_PATH.exists():
        st.error(f"❌ Fichier introuvable : `{DB_PATH.resolve()}`")
    else:
        st.success(f"✅ Fichier trouvé : `{DB_PATH.resolve()}`")
        conn = get_db_connection()
        if conn:
            try:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                tables = [t[0] for t in tables]
                st.markdown(f"**Tables détectées ({len(tables)}) :**")
                for t in tables:
                    try:
                        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    except sqlite3.Error:
                        count = "N/A"
                    st.markdown(
                        f"<div class='info-tile'>📋 <b>{t}</b> — {count} lignes</div>",
                        unsafe_allow_html=True,
                    )
            finally:
                conn.close()

    st.markdown("---")
    st.markdown("### 🧠 Modèle de prédiction")
    if not MODEL_PATH.exists():
        st.warning(f"⚠️ Fichier de modèle introuvable : `{MODEL_PATH.resolve()}`")
    else:
        st.success(f"✅ Fichier trouvé : `{MODEL_PATH.resolve()}`")
        stats = get_model_stats()
        if stats:
            st.json(
                {k: v for k, v in stats.items() if k != "history"},
                expanded=False,
            )
            st.caption(f"L'historique contient {len(stats.get('history', [])):,} entrées.")

    st.markdown("---")
    st.markdown("### 🎨 Apparence")
    theme_choice = st.radio(
        "Thème",
        ["🌙 Sombre", "☀️ Clair"],
        index=0 if st.session_state.get("theme", "dark") == "dark" else 1,
        horizontal=True,
    )
    new_theme = "dark" if theme_choice == "🌙 Sombre" else "light"
    if new_theme != st.session_state.get("theme", "dark"):
        st.session_state.theme = new_theme
        st.rerun()

    st.markdown("---")
    st.markdown("### 🎚️ Configuration")
    st.session_state.conf_threshold = st.slider(
        "Seuil de confiance par défaut (utilisé sur toutes les pages)",
        0,
        100,
        st.session_state.get("conf_threshold", 45),
        5,
        format="%d%%",
    )
    st.caption(
        "Ce seuil filtre les matchs affichés dans l'onglet Prédictions et sert de repère "
        "visuel dans le graphique de l'Accueil."
    )

    st.markdown("---")
    st.markdown("### ℹ️ À propos")
    st.markdown(
        """
        <div class="info-tile">
            ⚽ <b>CongoBet AI</b> — Dashboard de prédictions football<br>
            Sources : CongoBet, 1xBet, Sofascore<br>
            Toutes les statistiques affichées proviennent directement de la base locale
            <code>congobet.db</code> — aucune donnée n'est simulée dans l'interface,
            à l'exception des cotes de secours générées uniquement quand une cote réelle
            est absente pour un match donné.
        </div>
        """,
        unsafe_allow_html=True,
    )
