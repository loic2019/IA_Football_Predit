"""accueil.py — Page d'accueil : hub / page d'atterrissage.

REFONTE : l'accueil n'est plus juste un tableau de stats — c'est maintenant
un vrai hub : bandeau live, CTA connexion/inscription (ou message de
bienvenue si connecté), aperçu cliquable des autres pages, performance du
modèle en un coup d'œil, et un aperçu des derniers tickets gagnés/perdus.
Les graphiques détaillés d'évolution restent sur la page Statistiques (pas
de duplication).
"""

from datetime import datetime

import streamlit as st

from common import (
    DB_PATH,
    get_all_matches,
    get_finished_matches_count,
    get_future_matches_count,
    get_live_matches,
    get_live_matches_count,
    get_model_stats,
    goto_page,
    render_page_header,
)


def _goto(page_name: str):
    goto_page(page_name)


def _render_live_ticker():
    """Bandeau de matchs en direct en tête de page — structure inspirée des
    conventions génériques de sites de paris (cartes + badge LIVE + cotes),
    habillée avec l'identité visuelle CongoBet AI (pas de copie de marque)."""
    live_matches = get_live_matches(limit=3)
    if not live_matches:
        return

    st.markdown("#### 🔴 En direct maintenant")
    cols = st.columns(len(live_matches))
    for col, m in zip(cols, live_matches):
        with col:
            st.markdown(
                f"""
                <div class="match-card" style="border-left-color:var(--danger);">
                    <div class="match-header">
                        <span class="match-league">{m.get('league') or 'N/A'}</span>
                        <span style="display:flex;align-items:center;gap:6px;background:var(--danger-soft);
                                     color:var(--danger);padding:2px 10px;border-radius:12px;font-size:11px;font-weight:700;">
                            <span class="live-dot" style="background:var(--danger);"></span> EN DIRECT
                        </span>
                    </div>
                    <div class="match-body">
                        <span class="match-team">{m.get('home','?')}</span>
                        <span style="color:var(--text-muted);font-size:12px;">vs</span>
                        <span class="match-team">{m.get('away','?')}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    st.markdown("---")


def _render_hero():
    """CTA connexion/inscription (visiteur) ou message de bienvenue (connecté)."""
    logged_in = bool(st.session_state.get("auth_user") and st.session_state.get("user_profile"))

    if logged_in:
        profile = st.session_state.user_profile
        st.markdown(
            f"""
            <div class="match-card" style="border-left-color:var(--success);display:flex;align-items:center;gap:16px;">
                <div style="font-size:36px;">{profile['avatar_emoji']}</div>
                <div>
                    <div style="font-family:var(--font-display);font-size:18px;font-weight:700;">
                        Bon retour, {profile['pseudo']} 👋
                    </div>
                    <div style="color:var(--text-muted);font-size:13px;">
                        Suis tes pronostics, discute avec les autres parieurs, ou lance un nouveau coupon.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="match-card" style="border-left-color:var(--accent);">
                <div style="font-family:var(--font-display);font-size:20px;font-weight:700;margin-bottom:4px;">
                    Rejoins la communauté CongoBet AI
                </div>
                <div style="color:var(--text-muted);font-size:14px;">
                    Suis tes pronostics, vois ton taux de réussite et discute avec les autres parieurs.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        c1, c2, _ = st.columns([1, 1, 3])
        with c1:
            if st.button("🔑 Se connecter", width="stretch", type="primary"):
                _goto("Profil")
        with c2:
            if st.button("📝 S'inscrire", width="stretch"):
                _goto("Profil")
    st.markdown("---")


def _render_overview_cards():
    st.markdown("### 🧭 Explorer")
    cards = [
        ("🎯", "Pronostics", "Coupon du moment, généré par l'ensemble ML", "Pronostics"),
        ("🏆", "Palmarès", "Tickets gagnés/perdus, en toute transparence", "Palmarès"),
        ("💬", "Communauté", "Salon public et messages privés entre parieurs", "Communauté"),
        ("📊", "Statistiques", "Évolution détaillée de la précision du modèle", "Statistiques"),
        ("🤖", "Chatbot IA", "Pose tes questions à Max, notre assistant", "Chatbot IA"),
    ]
    cols = st.columns(len(cards))
    for col, (icon, title, desc, target) in zip(cols, cards):
        with col:
            st.markdown(
                f"""
                <div class="info-tile" style="min-height:118px;">
                    <div style="font-size:26px;">{icon}</div>
                    <div style="font-family:var(--font-display);font-weight:700;font-size:15px;margin-top:4px;">{title}</div>
                    <div style="color:var(--text-muted);font-size:12px;margin-top:2px;">{desc}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Ouvrir →", key=f"card_{target}", width="stretch"):
                _goto(target)
    st.markdown("---")


def _render_performance_highlights(model_stats: dict):
    st.markdown("### 📈 Performance du modèle")
    total_pred = model_stats.get("total_predictions", 0) if model_stats else 0
    correct_pred = model_stats.get("correct_predictions", 0) if model_stats else 0
    acc = (correct_pred / max(1, total_pred)) * 100

    c1, c2, c3 = st.columns(3)
    c1.metric("📊 Prédictions vérifiées", f"{total_pred:,}")
    c2.metric("🎯 Précision globale", f"{acc:.1f}%")
    c3.metric("✅ Bonnes prédictions", f"{correct_pred:,}")
    if st.button("Voir l'évolution détaillée →", key="see_stats"):
        _goto("Statistiques")
    st.markdown("---")


def _render_recent_tickets(model_stats: dict):
    st.markdown("### 🎟️ Derniers tickets")
    history = (model_stats or {}).get("history", [])
    if not history:
        st.info("📭 Pas encore de tickets vérifiés — reviens après le prochain cycle d'entraînement.")
        return

    recent = sorted(history, key=lambda e: e.get("trained_at", ""), reverse=True)[:3]
    cols = st.columns(len(recent))
    for col, entry in zip(cols, recent):
        won = bool(entry.get("correct"))
        stamp_color = "var(--success)" if won else "var(--danger)"
        stamp_text = "✅ GAGNÉ" if won else "❌ PERDU"
        with col:
            st.markdown(
                f"""
                <div class="match-card" style="border-left-color:{stamp_color};">
                    <div class="match-header">
                        <span class="match-league">{entry.get('league') or 'N/A'}</span>
                        <span style="color:{stamp_color};font-weight:800;font-size:12px;">{stamp_text}</span>
                    </div>
                    <div class="match-body">
                        <span class="match-team" style="font-size:13px;">{entry.get('home','?')}</span>
                        <span style="color:var(--text-muted);font-size:11px;">vs</span>
                        <span class="match-team" style="font-size:13px;">{entry.get('away','?')}</span>
                    </div>
                    <div style="text-align:center;color:var(--gold);font-size:12px;font-weight:700;">
                        {entry.get('prediction','?')} · cote {entry.get('cote', 0):.2f}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    if st.button("Voir tout le palmarès →", key="see_palmares"):
        _goto("Palmarès")
    st.markdown("---")


def render():
    if not DB_PATH.exists():
        st.warning("⚠️ Base de données non trouvée !")
        st.info("💡 Lancez d'abord le scraping : python scraper_multi.py")
        st.stop()

    render_page_header("⚽", "CongoBet AI", "Données réelles, prédictions en direct")

    _render_live_ticker()
    _render_hero()

    total_matches = get_all_matches()
    future_count = get_future_matches_count()
    finished_count = get_finished_matches_count()
    live_count = get_live_matches_count()
    model_stats = get_model_stats()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📦 Total matchs", f"{total_matches:,}")
    col2.metric("🔮 Matchs futurs", f"{future_count:,}")
    col3.metric("✅ Terminés", f"{finished_count:,}")
    col4.metric("🔴 En direct", f"{live_count:,}")
    st.caption(f"📊 Dernière lecture : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    st.markdown("---")

    _render_overview_cards()
    _render_performance_highlights(model_stats)
    _render_recent_tickets(model_stats)

    st.caption(f"⚽ CongoBet AI | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
