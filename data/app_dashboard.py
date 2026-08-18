"""
app_dashboard.py — Dashboard CongoBet AI (multi-pages)
================================================================================
Point d'entrée de l'application. Configure la page, injecte le CSS, affiche
la sidebar commune (scraping + seuil de confiance) et déclare la navigation
entre les différentes pages de l'application.

MODIFICATIONS (bug de débordement du menu du haut) :
- Constaté par capture d'écran réelle (Playwright) : avec les 11 pages dans
  st_navbar, la barre déborde et les derniers éléments (Communauté, Fichiers,
  Profil, Administration, Paramètres) sont physiquement coupés/invisibles —
  ce n'est pas une histoire de connexion, c'est un débordement horizontal.
- Correctif : le menu du haut ne garde que les pages "cœur d'usage"
  (Accueil, Pronostics, Palmarès, Communauté, Profil) — 5 items, qui tiennent
  sur un écran étroit. Les pages secondaires (Chatbot IA, Historique,
  Statistiques, Fichiers, Paramètres, Administration) sont désormais dans un
  vrai menu vertical dans la sidebar, où il n'y a aucun risque de
  débordement (défilement vertical naturel).
- La sélection est synchronisée entre les deux (st.session_state.active_page)
  : cliquer un item de la sidebar ou du menu du haut met à jour l'autre.

Lancement : streamlit run app_dashboard.py
"""

import sys
import io
from pathlib import Path

try:
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import streamlit as st
from streamlit_navigation_bar import st_navbar

from common import (
    inject_css,
    init_session_state,
    goto_page,
    load_automation_state,
    seconds_until_next_cycle,
    sidebar_scraping_panel,
)
import accueil
import historique
import statistiques
import chatbot
import parametres
import pronostics
import fichiers
import profil
import communaute
import admin
import palmares
import community_db
import dashboard
import backtest_ui

# ============================================================================
# CONFIGURATION DE LA PAGE
# ============================================================================

st.set_page_config(
    page_title="CongoBet AI",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# PAGES : cœur d'usage (menu du haut) + secondaires (sidebar)
# ============================================================================

ALL_PAGES = {
    "Accueil": accueil.render,
    "Pronostics": pronostics.render,
    "Palmarès": palmares.render,
    "Communauté": communaute.render,
    "Profil": profil.render,
    "Chatbot IA": chatbot.render,
    "Historique": historique.render,
    "Statistiques": statistiques.render,
    "Dashboard": dashboard.render,
    "Backtesting": backtest_ui.render,
    "Fichiers": fichiers.render,
    "Paramètres": parametres.render,
    "Administration": admin.render,
}

TOP_NAV_PAGES = ["Accueil", "Pronostics", "Palmarès", "Communauté"]
SIDEBAR_PAGES = ["Chatbot IA", "Historique", "Statistiques", "Dashboard", "Backtesting", "Fichiers", "Paramètres", "Profil"]
ADMIN_ONLY_PAGES = ["Administration"]

if "active_page" not in st.session_state:
    st.session_state.active_page = "Accueil"
if "top_nav_last" not in st.session_state:
    st.session_state.top_nav_last = "Accueil"

# Garde défensive : goto_page() (utilisé depuis n'importe quelle page, y
# compris des pages secondaires comme Statistiques) peut avoir positionné
# top_nav_last sur une page que st_navbar ne connaît pas — il exige que
# `selected` soit strictement dans sa propre liste, sinon il lève une
# exception. On ramène donc systématiquement à "Accueil" si besoin.
if st.session_state.top_nav_last not in TOP_NAV_PAGES:
    st.session_state.top_nav_last = "Accueil"

LOGO_PATH = str((Path(__file__).parent / "assets" / "logo.svg").resolve())

# On ne passe à st_navbar QUE la dernière sélection connue PARMI ses propres
# items (top_nav_last), jamais active_page directement : si active_page est
# une page secondaire (venue de la sidebar), st_navbar n'a aucune idée de son
# existence et retomberait sur "Accueil", ce qui écraserait à tort le choix
# fait depuis la sidebar au rerun suivant.
navbar_selected = st_navbar(
    TOP_NAV_PAGES,
    selected=st.session_state.top_nav_last,
    logo_path=LOGO_PATH,
    logo_page=None,
    styles={
        "nav": {
            "background-color": "#0a0e1a",
            "border-bottom": "1px solid rgba(255,255,255,0.08)",
            "justify-content": "flex-end",
            "padding": "0 24px",
            "height": "60px",
        },
        "div": {"max-width": "100%"},
        "img": {"padding-right": "20px"},
        "span": {
            "color": "#e8ecff",
            "font-family": "Inter, sans-serif",
            "font-weight": "600",
            "font-size": "14px",
            "padding": "14px 16px",
            "border-radius": "8px",
        },
        "active": {
            "color": "#33c7ff",
            "background-color": "rgba(51,199,255,0.12)",
            "font-weight": "700",
        },
        "hover": {"color": "#33c7ff", "background-color": "rgba(255,255,255,0.05)"},
    },
)

# Un vrai clic sur le menu du haut (valeur différente de ce qu'on lui a donné)
# devient la page active. Sinon (l'utilisateur navigue via la sidebar), on ne
# touche à rien : active_page reste piloté par la sidebar.
if navbar_selected != st.session_state.top_nav_last:
    st.session_state.top_nav_last = navbar_selected
    st.session_state.active_page = navbar_selected

inject_css()
init_session_state()

auto_state = load_automation_state()

# Calculé tôt : pilote à la fois la sidebar (masquée si non connecté) et le
# routage de la page principale (forcée sur Profil si non connecté).
logged_in = bool(st.session_state.get("auth_user") and st.session_state.get("user_profile"))

# ============================================================================
# SIDEBAR COMMUNE (visible sur toutes les pages)
# ============================================================================

with st.sidebar:
    st.markdown("## ⚽ CongoBet AI")
    st.caption("Données réelles")

    is_admin = False
    if logged_in:
        profile = st.session_state.user_profile
        st.success(f"{profile['avatar_emoji']} Connecté : {profile['pseudo']}")
        unread = community_db.get_unread_public_count(profile["id"])
        if unread:
            st.caption(f"📬 {unread} nouveau(x) message(s) — page **Communauté**.")
        unread_dm = community_db.get_unread_dm_count(profile["id"])
        if unread_dm:
            st.caption(f"✉️ {unread_dm} message(s) privé(s) non lu(s) — page **Communauté**.")
        is_admin = community_db.is_user_admin(profile["id"])
        if is_admin:
            st.caption("🛡️ Statut administrateur actif")

        # --- Notifications (pronostics suivis gagnants, coupon du jour, etc.) ---
        community_db.refresh_followed_picks_results(profile["id"])
        unread_notif = community_db.get_unread_notification_count(profile["id"])
        notif_list = community_db.list_notifications(profile["id"], limit=10)

        # Pop-up (toast) pour les notifications non lues, une seule fois par
        # notification (mémorisé en session pour ne pas re-pop à chaque rerun).
        st.session_state.setdefault("_toasted_notif_ids", set())
        for n in notif_list:
            if not n["is_read"] and n["id"] not in st.session_state["_toasted_notif_ids"]:
                st.toast(f"{n['title']} — {n['message']}", icon="🎉" if n["type"] == "pick_won" else "🔔")
                st.session_state["_toasted_notif_ids"].add(n["id"])

        with st.expander(f"🔔 Notifications{f' ({unread_notif})' if unread_notif else ''}", expanded=False):
            if not notif_list:
                st.caption("Aucune notification pour l'instant.")
            else:
                if unread_notif and st.button("Tout marquer comme lu", key="mark_notif_read", width="stretch"):
                    community_db.mark_notifications_read(profile["id"])
                    st.rerun()
                for n in notif_list:
                    marker = "🟢" if not n["is_read"] else "⚪"
                    st.caption(f"{marker} **{n['title']}**  \n{n['message']}")

    else:
        st.info("🔒 Connecte-toi pour accéder à l'application.")

    # Toute la navigation (Pronostics, pages secondaires, outils de scraping,
    # auto-training) reste cachée tant qu'on n'est pas connecté — demande
    # explicite : l'app s'ouvre entièrement une fois connecté, pas avant.
    if logged_in:
        st.markdown("---")
        if st.button(
            "⚽ Pronostics",
            key="nav_pronostics_fixed",
            width="stretch",
            type="primary" if st.session_state.active_page == "Pronostics" else "secondary",
        ):
            goto_page("Pronostics")

        st.markdown("---")
        st.markdown("### 📄 Plus de pages")
        secondary_pages = SIDEBAR_PAGES + (ADMIN_ONLY_PAGES if is_admin else [])
        for page_name in secondary_pages:
            is_active = st.session_state.active_page == page_name
            if st.button(
                page_name,
                key=f"nav_{page_name}",
                width="stretch",
                type="primary" if is_active else "secondary",
            ):
                goto_page(page_name)

        st.markdown("---")
        sidebar_scraping_panel()
        live_state = load_automation_state()
        remaining = seconds_until_next_cycle(live_state)
        next_text = "maintenant" if remaining == 0 else f"{remaining // 60}m {remaining % 60}s"
        st.caption(f"Auto-cycle reel : {live_state.get('last_cycle_status', 'never')} | prochain : {next_text}")
        st.markdown("---")
        st.markdown("### 🔄 Auto-training")
        st.markdown(
            f"""
            <div style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:rgba(46,204,135,0.1);border-radius:10px;border:1px solid rgba(46,204,135,0.2);">
                <span class="live-dot"></span>
                <span style="font-size:13px;">Prochain entraînement dans {next_text}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ============================================================================
# BARRE CTA (connexion/inscription bien visible, ou profil si connecté)
# ============================================================================

_cta_spacer, _cta_col1, _cta_col2 = st.columns([5, 1.1, 1.3])
if logged_in:
    _profile = st.session_state.user_profile
    with _cta_col2:
        if st.button(f"{_profile['avatar_emoji']} {_profile['pseudo']}", key="cta_profile", width="stretch"):
            goto_page("Profil")
else:
    with _cta_col1:
        if st.button("🔑 Connexion", key="cta_login", width="stretch"):
            goto_page("Profil")
    with _cta_col2:
        if st.button("📝 Inscription", key="cta_signup", width="stretch", type="primary"):
            goto_page("Profil")

# ============================================================================
# ROUTAGE MANUEL VERS LA PAGE SÉLECTIONNÉE
# ============================================================================

# Tant qu'on n'est pas connecté, seule la page Profil (connexion/inscription)
# est accessible, quelle que soit la page mémorisée en session — demande
# explicite : l'app reste fermée jusqu'à connexion.
if not logged_in:
    profil.render()
else:
    page_render = ALL_PAGES.get(st.session_state.active_page, accueil.render)
    page_render()
