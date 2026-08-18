"""
palmares.py — Palmarès public : tickets gagnés/perdus + évolution de la précision
======================================================================================
Montre aux visiteurs la performance RÉELLE du modèle : chaque ticket affiché
vient de model_data.json (`history`), c'est-à-dire des prédictions faites AVANT
de connaître le résultat, comparées ensuite au résultat réel — pas de
rétro-fabrication. Aucune donnée inventée : si l'historique est vide, la page
le dit clairement plutôt que d'afficher de faux tickets.
"""

from datetime import datetime

import streamlit as st

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

from common import get_model_stats, render_page_header


def _ticket_card(entry: dict):
    won = bool(entry.get("correct"))
    stamp_color = "var(--success)" if won else "var(--danger)"
    stamp_bg = "var(--success-soft)" if won else "var(--danger-soft)"
    stamp_text = "✅ GAGNÉ" if won else "❌ PERDU"
    pred_label = {"1": "Victoire domicile", "X": "Match nul", "2": "Victoire extérieur"}.get(
        entry.get("prediction", ""), entry.get("prediction", "")
    )
    cote = entry.get("cote") or 0
    date_display = (entry.get("trained_at") or "")[:16].replace("T", " ")

    st.markdown(
        f"""
        <div class="match-card" style="border-left-color:{stamp_color};">
            <div class="match-header">
                <span class="match-league">{entry.get('league') or 'N/A'}</span>
                <span class="match-datetime">{date_display}</span>
            </div>
            <div class="match-body">
                <span class="match-team">{entry.get('home','?')}</span>
                <span style="color:var(--text-muted);font-size:13px;">vs</span>
                <span class="match-team">{entry.get('away','?')}</span>
            </div>
            <div class="match-prediction">
                <span class="pred">{entry.get('prediction','?')}</span>
                <span style="color:var(--text-muted);">{pred_label}</span>
                <span style="color:var(--gold);font-weight:700;">Cote {cote:.2f}</span>
                <span style="color:var(--text-muted);">Confiance {entry.get('confidence',0):.0%}</span>
                <span style="margin-left:auto;background:{stamp_bg};color:{stamp_color};font-weight:800;
                             padding:4px 14px;border-radius:8px;letter-spacing:0.05em;">{stamp_text}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _evolution_chart(history: list[dict]):
    if not PLOTLY_AVAILABLE or len(history) < 2:
        return

    sorted_history = sorted(history, key=lambda e: e.get("trained_at", ""))
    cumulative_correct = 0
    x_vals, y_vals = [], []
    for i, entry in enumerate(sorted_history, start=1):
        if entry.get("correct"):
            cumulative_correct += 1
        x_vals.append(entry.get("trained_at", "")[:10])
        y_vals.append(round(cumulative_correct / i * 100, 1))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(1, len(y_vals) + 1)), y=y_vals,
        mode="lines", line=dict(color="#33c7ff", width=3),
        fill="tozeroy", fillcolor="rgba(51,199,255,0.08)",
        name="Précision cumulée",
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e8ecff", family="Inter"),
        margin=dict(l=10, r=10, t=10, b=10),
        height=280,
        xaxis=dict(title="Nᵉ pronostic", gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(title="Précision cumulée (%)", gridcolor="rgba(255,255,255,0.05)", range=[0, 100]),
    )
    st.plotly_chart(fig, width="stretch")


def render():
    render_page_header("🏆", "Palmarès public", "Chaque pronostic, son résultat réel — rien de caché.")

    stats = get_model_stats()
    if not stats or not stats.get("history"):
        st.info(
            "📭 Aucun pronostic vérifié pour l'instant. Cette page se remplit automatiquement "
            "après que le modèle ait été entraîné sur des matchs terminés (voir Paramètres "
            "ou attends le prochain cycle automatique)."
        )
        return

    history = stats["history"]
    total = len(history)
    won = sum(1 for e in history if e.get("correct"))
    win_rate = (won / total * 100) if total else 0

    recent = sorted(history, key=lambda e: e.get("trained_at", ""), reverse=True)
    current_streak = 0
    streak_type = None
    for e in recent:
        is_win = bool(e.get("correct"))
        if streak_type is None:
            streak_type = is_win
            current_streak = 1
        elif is_win == streak_type:
            current_streak += 1
        else:
            break

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🎟️ Tickets vérifiés", f"{total:,}")
    c2.metric("✅ Gagnés", f"{won:,}")
    c3.metric("📊 Taux de réussite", f"{win_rate:.1f}%")
    streak_label = f"{current_streak} {'✅' if streak_type else '❌'}" if streak_type is not None else "—"
    c4.metric("🔥 Série actuelle", streak_label)

    st.markdown("#### 📈 Évolution de la précision")
    _evolution_chart(history)

    st.markdown("---")
    st.markdown("#### 🎟️ Derniers tickets")

    filter_choice = st.radio(
        "Filtrer", ["Tous", "Gagnés uniquement", "Perdus uniquement"], horizontal=True, label_visibility="collapsed"
    )
    if filter_choice == "Gagnés uniquement":
        filtered = [e for e in recent if e.get("correct")]
    elif filter_choice == "Perdus uniquement":
        filtered = [e for e in recent if not e.get("correct")]
    else:
        filtered = recent

    limit = 30
    for entry in filtered[:limit]:
        _ticket_card(entry)

    if len(filtered) > limit:
        st.caption(f"… et {len(filtered) - limit} autre(s) ticket(s) non affiché(s).")
