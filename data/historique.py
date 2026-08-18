"""views/historique.py — Historique des matchs terminés."""

import plotly.graph_objects as go
import streamlit as st

from common import DB_PATH, format_date, get_finished_matches


def render():
    st.title("✅ Historique des Matchs")
    st.caption("Résultats réels importés depuis la base de données")

    if not DB_PATH.exists():
        st.warning("⚠️ Base de données non trouvée !")
        st.stop()

    finished_matches = get_finished_matches(500)

    if not finished_matches:
        st.info("ℹ️ Aucun match terminé trouvé.")
        return

    col1, col2 = st.columns([3, 2])
    with col1:
        search = st.text_input("🔍 Rechercher une équipe", placeholder="Ex: Marseille, Lyon...")
    with col2:
        leagues = sorted({str(m.get("league", "N/A")) for m in finished_matches})
        league_filter = st.selectbox("🏆 Ligue", ["Toutes"] + leagues)

    filtered = []
    for m in finished_matches:
        if league_filter != "Toutes" and str(m.get("league", "N/A")) != league_filter:
            continue
        if search:
            s = search.lower()
            if s not in str(m.get("home", "")).lower() and s not in str(m.get("away", "")).lower():
                continue
        filtered.append(m)

    # --- Stats rapides sur l'échantillon filtré ---
    home_wins = sum(1 for m in filtered if (m.get("home_score") or 0) > (m.get("away_score") or 0))
    draws = sum(1 for m in filtered if (m.get("home_score") or 0) == (m.get("away_score") or 0))
    away_wins = sum(1 for m in filtered if (m.get("home_score") or 0) < (m.get("away_score") or 0))

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
        date_display = format_date(m.get("date", ""), fmt="%d/%m/%Y")
        st.markdown(
            f"""
        <div class="history-match">
            <div class="teams">{m.get('home', '')} vs {m.get('away', '')}</div>
            <div class="score">{m.get('home_score', 0)} - {m.get('away_score', 0)}</div>
            <div style="font-size:13px;color:rgba(232,236,255,0.6);">📅 {date_display}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )
