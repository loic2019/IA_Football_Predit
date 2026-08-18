"""views/historique.py — Historique des matchs terminés."""

import plotly.graph_objects as go
import streamlit as st

from common import DB_PATH, format_date, get_finished_matches
from match_classification import annotate_matches, summarize, match_date_value, STATUS_BADGE


def _get_finished_matches_with_fallback(limit=500):
    """get_finished_matches() seul retourne quasi toujours vide : congobet.db
    ne remplit presque jamais home_score/away_score lui-même (voir le
    commentaire de common.get_training_matches()). On applique ici le même
    correctif déjà utilisé pour l'entraînement — filet de secours gratuit
    (historical_results.db) — pour que cette page affiche vraiment quelque
    chose au lieu d'être vide en permanence."""
    from coupon_tracker import get_recent_matches_with_results

    matches = get_finished_matches(limit)
    seen_ids = {m.get("id") for m in matches}

    try:
        recent = get_recent_matches_with_results(days_back=30, limit=limit)
    except Exception:
        recent = []

    for m in recent:
        if m.get("id") not in seen_ids:
            matches.append(m)
            seen_ids.add(m.get("id"))

    return matches


def render():
    st.title("✅ Historique des Matchs")
    st.caption("Résultats réels importés depuis la base de données")

    if not DB_PATH.exists():
        st.warning("⚠️ Base de données non trouvée !")
        st.stop()

    finished_matches = _get_finished_matches_with_fallback(500)

    if not finished_matches:
        st.info("ℹ️ Aucun match terminé trouvé.")
        return

    # Classification VERIFIED/UNVERIFIED/INVALID/DUPLICATE — voir
    # match_classification.py pour la logique exacte (basée sur la manière
    # dont chaque résultat a réellement été retrouvé, pas une supposition).
    finished_matches = annotate_matches(finished_matches)
    global_report = summarize(finished_matches)

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("✓ Vérifiés", f"{global_report['verified']:,}",
              help="Résultat lu directement dans congobet.db pour ce match précis.")
    b2.metric("⚠ Non vérifiés", f"{global_report['unverified']:,}",
              help="Résultat retrouvé par correspondance nom d'équipe + date (±3 jours) contre "
                   "une base externe — vraisemblable mais pas garanti par un identifiant exact.")
    b3.metric("✕ Invalides", f"{global_report['invalid']:,}",
              help="Équipe, date ou score manquant — exclus des statistiques ci-dessous.")
    b4.metric("↔ Doublons", f"{global_report['duplicate']:,}",
              help="Même match (équipes + jour) déjà présent ailleurs dans la liste.")

    col1, col2, col3 = st.columns([3, 2, 2])
    with col1:
        search = st.text_input("🔍 Rechercher une équipe", placeholder="Ex: Marseille, Lyon...")
    with col2:
        leagues = sorted({str(m.get("league", "N/A")) for m in finished_matches})
        league_filter = st.selectbox("🏆 Ligue", ["Toutes"] + leagues)
    with col3:
        status_filter = st.selectbox("Statut", ["Vérifiés + non vérifiés", "Vérifiés uniquement", "Tous (avec invalides/doublons)"])

    filtered = []
    for m in finished_matches:
        if league_filter != "Toutes" and str(m.get("league", "N/A")) != league_filter:
            continue
        if search:
            s = search.lower()
            if s not in str(m.get("home", "")).lower() and s not in str(m.get("away", "")).lower():
                continue
        if status_filter == "Vérifiés uniquement" and m["_status"] != "VERIFIED":
            continue
        if status_filter == "Vérifiés + non vérifiés" and m["_status"] not in ("VERIFIED", "UNVERIFIED"):
            continue
        filtered.append(m)

    # --- Stats rapides sur l'échantillon filtré ---
    # Un match INVALID a des scores manquants (None) : sans cette exclusion,
    # (None or 0) == (None or 0) le comptait silencieusement comme un nul 0-0
    # — un vrai match jamais joué faussait donc les statistiques affichées.
    usable = [m for m in filtered if m["_status"] in ("VERIFIED", "UNVERIFIED")]
    home_wins = sum(1 for m in usable if (m.get("home_score") or 0) > (m.get("away_score") or 0))
    draws = sum(1 for m in usable if (m.get("home_score") or 0) == (m.get("away_score") or 0))
    away_wins = sum(1 for m in usable if (m.get("home_score") or 0) < (m.get("away_score") or 0))

    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📦 Matchs affichés", f"{len(filtered):,}")
    c2.metric("🏠 Victoires domicile", f"{home_wins:,}")
    c3.metric("⚖️ Nuls", f"{draws:,}")
    c4.metric("✈️ Victoires extérieur", f"{away_wins:,}")

    if filtered:
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=["Domicile", "Nul", "Extérieur"],
                    values=[home_wins, draws, away_wins],
                    marker=dict(colors=["#2ecc87", "#f5c451", "#ff6b57"]),
                    hole=0.5,
                )
            ]
        )
        fig.update_layout(
            title="Répartition des résultats",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="rgba(232,236,255,0.6)"),
            height=320,
            margin=dict(t=50, b=10, l=10, r=10),
        )
        st.plotly_chart(fig, width='stretch')

    st.markdown("---")
    st.markdown(f"### 📜 Résultats ({len(filtered)})")

    if not filtered:
        st.warning("Aucun match ne correspond à ces filtres.")
        return

    for m in filtered[:100]:
        date_display = format_date(match_date_value(m), fmt="%d/%m/%Y")
        symbol, color, label = STATUS_BADGE[m["_status"]]
        st.markdown(
            f"""
        <div class="history-match">
            <div class="teams">{m.get('home', '')} vs {m.get('away', '')}</div>
            <div class="score">{m.get('home_score', 0)} - {m.get('away_score', 0)}</div>
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div style="font-size:13px;color:rgba(232,236,255,0.6);">📅 {date_display}</div>
                <div style="font-size:12px;color:{color};" title="{label}">{symbol} {label}</div>
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )
