"""
admin.py — Panel administrateur
====================================
Accès réservé aux utilisateurs avec is_admin=1 (voir admin_config.py pour
promouvoir automatiquement ton compte au login/inscription — un admin peut
aussi promouvoir d'autres utilisateurs depuis ce panel).

Sections :
- Vue d'ensemble (données réelles : matchs, modèle, communauté)
- Gestion des utilisateurs (promotion admin, suspension)
- Modération des messages (salon public + privés)
- Contrôle de l'automatisation (cycle scraping/training/prédiction)
- Santé de la base de données (détecte les problèmes de schéma/orphelins —
  le genre de bug qui a cassé les prédictions sur ce projet)
"""

import sqlite3

import streamlit as st

import community_db
from community_db import avatar_html
from common import (
    DB_PATH,
    get_all_matches,
    get_finished_matches_count,
    get_future_matches_count,
    get_live_matches_count,
    get_model_stats,
    load_automation_state,
    run_auto_cycle,
    save_automation_state,
    seconds_until_next_cycle,
    is_logged_in,
    get_current_profile,
)


def _require_admin():
    st.title("🛡️ Panel administrateur")
    if not is_logged_in():
        st.warning("🔒 Connecte-toi (page Profil) pour accéder à cette section.")
    else:
        st.error("⛔ Accès réservé aux administrateurs.")


def _render_overview():
    st.markdown("### 📊 Vue d'ensemble")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Matchs en base", f"{get_all_matches():,}", border=True)
    c2.metric("En direct", f"{get_live_matches_count():,}", border=True)
    c3.metric("À venir", f"{get_future_matches_count():,}", border=True)
    c4.metric("Terminés", f"{get_finished_matches_count():,}", border=True)

    stats = get_model_stats() or {}
    total_pred = stats.get("total_predictions", 0)
    correct = stats.get("correct_predictions", 0)
    acc = (correct / max(1, total_pred)) * 100

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Prédictions faites", f"{total_pred:,}", border=True)
    c6.metric("Précision modèle", f"{acc:.1f}%", border=True)

    community_stats = community_db.admin_overview_stats()
    c7.metric("Parieurs inscrits", f"{community_stats['total_users']:,}", border=True)
    c8.metric("Messages échangés", f"{community_stats['total_messages']:,}", border=True)

    st.markdown("#### 🧠 Ensemble ML")
    try:
        from ml_models import ensemble as ml_ensemble
        ens_status = ml_ensemble.status()
        c9, c10, c11, c12 = st.columns(4)
        c9.metric("Réseau de neurones", "✅ Entraîné" if ens_status["deep_trained"] else "⏳ Pas encore")
        c10.metric("XGBoost", "✅ Entraîné" if ens_status["xgb_trained"] else "⏳ Pas encore")
        c11.metric("LightGBM", "✅ Entraîné" if ens_status["lgbm_trained"] else "⏳ Pas encore")
        c12.metric("Random Forest", "✅ Entraîné" if ens_status["rf_trained"] else "⏳ Pas encore")
        weights = ens_status["weights"]
        st.caption("Poids actuels (auto-évaluation) : " + " · ".join(f"{k} = {v:.0%}" for k, v in weights.items()))
    except Exception as e:
        st.caption(f"ℹ️ Ensemble ML indisponible : {e}")

    st.caption(
        f"Dont {community_stats['public_messages']} messages publics, "
        f"{community_stats['dm_messages']} messages privés, "
        f"{community_stats['total_followed']} pronostics suivis, "
        f"{community_stats['admin_count']} administrateur(s), "
        f"{community_stats['banned_count']} compte(s) suspendu(s)."
    )


def _render_users():
    st.markdown("### 👥 Gestion des utilisateurs")
    users = community_db.list_all_users_admin()
    if not users:
        st.info("Aucun utilisateur inscrit pour l'instant.")
        return

    current_user_id = st.session_state.user_profile["id"]

    for u in users:
        with st.container(border=True):
            col_info, col_stats, col_actions = st.columns([3, 2, 2])
            with col_info:
                badge = "🛡️ Admin" if u["is_admin"] else ""
                banned_badge = " · 🚫 Suspendu" if u["is_banned"] else ""
                st.markdown(
                    f"""<div style="display:flex;align-items:center;gap:10px;">
                            {avatar_html(u, size=36)}
                            <div><b>{u['pseudo']}</b> {badge}{banned_badge}</div>
                        </div>""",
                    unsafe_allow_html=True,
                )
                st.caption(f"{u['email']} · inscrit le {u['created_at'][:10]}")
            with col_stats:
                st.caption(f"💬 {u['messages_count']} messages")
                st.caption(f"🎯 {u['followed_count']} pronostics suivis")
            with col_actions:
                if u["id"] == current_user_id:
                    st.caption("— C'est toi —")
                else:
                    admin_toggle = st.checkbox(
                        "Administrateur", value=bool(u["is_admin"]), key=f"admin_toggle_{u['id']}"
                    )
                    if admin_toggle != bool(u["is_admin"]):
                        community_db.set_admin(u["id"], admin_toggle)
                        st.rerun()

                    ban_toggle = st.checkbox(
                        "Suspendre", value=bool(u["is_banned"]), key=f"ban_toggle_{u['id']}"
                    )
                    if ban_toggle != bool(u["is_banned"]):
                        community_db.set_banned(u["id"], ban_toggle)
                        st.rerun()


def _render_moderation():
    st.markdown("### 🧹 Modération des messages")
    messages = community_db.list_recent_messages_admin(limit=100)
    if not messages:
        st.info("Aucun message pour l'instant.")
        return

    for m in messages:
        with st.container(border=True):
            col_content, col_action = st.columns([5, 1])
            with col_content:
                channel_label = "📢 Public" if m["channel"] == "public" else f"✉️ Privé → {m['receiver_pseudo']}"
                announce = " 📌 ANNONCE" if m.get("is_announcement") else ""
                st.caption(f"{channel_label}{announce} · {m['sender_pseudo']} · {m['created_at'][:16]}")
                st.write(m["content"])
            with col_action:
                if st.button("🗑️ Supprimer", key=f"del_msg_{m['id']}"):
                    community_db.delete_message(m["id"])
                    st.rerun()


def _render_automation():
    st.markdown("### ⚙️ Automatisation")
    state = load_automation_state()
    remaining = seconds_until_next_cycle(state)

    c1, c2 = st.columns(2)
    with c1:
        st.metric("Statut dernier cycle", state.get("last_cycle_status", "never"))
    with c2:
        st.metric("Prochain cycle", "maintenant" if remaining == 0 else f"{remaining // 60}m {remaining % 60}s")

    enabled = st.toggle("Cycle automatique activé", value=state.get("enabled", True), key="admin_auto_toggle")
    if enabled != state.get("enabled", True):
        state["enabled"] = enabled
        save_automation_state(state)
        st.rerun()

    if st.button("▶️ Forcer un cycle maintenant", width="stretch"):
        with st.spinner("Cycle en cours (scraping + entraînement + prédiction)..."):
            result = run_auto_cycle(force=True, include_premierbet=True)
        st.success(f"Statut : {result.get('state', {}).get('last_cycle_status')}")
        st.json(result.get("summary", {}))

    st.caption(
        "ℹ️ En temps normal, le cycle tourne via `auto_cycle_worker.py` (process séparé). "
        "Ce bouton force un cycle immédiat depuis le dashboard."
    )


def _render_db_health():
    st.markdown("### 🩺 Santé de la base de données")
    st.caption(
        "Détecte le type de problème qui a cassé les prédictions sur ce projet : "
        "cotes orphelines (sans match correspondant) et matchs sans aucune cote."
    )

    if not DB_PATH.exists():
        st.warning("congobet.db introuvable.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        st.write(f"**Tables présentes :** {', '.join(tables)}")

        if "matches" in tables and "odds" in tables:
            cols = {c[1] for c in conn.execute("PRAGMA table_info(matches)").fetchall()}
            id_col = "id" if "id" in cols else "match_id"
            match_ids = {r[0] for r in conn.execute(f"SELECT {id_col} FROM matches").fetchall()}

            odds_match_ids = {r[0] for r in conn.execute("SELECT DISTINCT match_id FROM odds").fetchall()}
            orphan_odds = odds_match_ids - match_ids

            c1, c2, c3 = st.columns(3)
            c1.metric("Matchs", len(match_ids))
            c2.metric("Match_id distincts dans odds", len(odds_match_ids))
            c3.metric("Cotes orphelines (⚠️)", len(orphan_odds))

            if orphan_odds:
                st.error(
                    f"⚠️ {len(orphan_odds)} match_id dans `odds` n'ont AUCUNE correspondance dans `matches`. "
                    "C'est exactement le symptôme du bug corrigé (scraper écrivant dans le mauvais schéma). "
                    "Relance un scraping complet (`Scraper tous`) pour resynchroniser."
                )
                with st.expander("Voir quelques ids orphelins"):
                    st.code("\n".join(str(x) for x in list(orphan_odds)[:20]))
            else:
                st.success("✅ Toutes les cotes correspondent à un match existant.")

        if "matches_legacy_backup" in tables:
            count = conn.execute("SELECT COUNT(*) FROM matches_legacy_backup").fetchone()[0]
            st.info(
                f"ℹ️ Une sauvegarde `matches_legacy_backup` existe encore ({count} lignes) — "
                "résidu de la migration de sécurité effectuée précédemment. Tu peux la supprimer "
                "manuellement une fois certain de ne plus en avoir besoin."
            )
    finally:
        conn.close()


def render():
    if not is_logged_in():
        _require_admin()
        return

    profile = get_current_profile()
    if not community_db.is_user_admin(profile["id"]):
        _require_admin()
        return

    st.title("🛡️ Panel administrateur")
    st.caption(f"Connecté en tant que {profile['pseudo']}")

    tab_overview, tab_users, tab_mod, tab_auto, tab_health = st.tabs(
        ["📊 Vue d'ensemble", "👥 Utilisateurs", "🧹 Modération", "⚙️ Automatisation", "🩺 Santé DB"]
    )
    with tab_overview:
        _render_overview()
    with tab_users:
        _render_users()
    with tab_mod:
        _render_moderation()
    with tab_auto:
        _render_automation()
    with tab_health:
        _render_db_health()
