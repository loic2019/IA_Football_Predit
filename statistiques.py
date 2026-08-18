"""views/statistiques.py — Analyse approfondie des performances de l'IA."""

import plotly.graph_objects as go
import streamlit as st

from common import get_model_stats


def render():
    st.title("📊 Statistiques Détaillées du Modèle")

    model_stats = get_model_stats()
    if not model_stats:
        st.info("📊 Aucune donnée de performance disponible. Entraînez d'abord le modèle.")
        return

    history = model_stats.get("history", [])
    if not history:
        st.info("📊 Pas assez de données pour établir des statistiques.")
        return

    total_pred = model_stats.get("total_predictions", len(history))
    correct_pred = model_stats.get(
        "correct_predictions", sum(1 for h in history if h.get("correct"))
    )
    global_acc = (correct_pred / max(1, total_pred)) * 100

    col1, col2, col3 = st.columns(3)
    col1.metric("📊 Prédictions totales", f"{total_pred:,}")
    col2.metric("🎯 Précision globale", f"{global_acc:.1f}%")
    col3.metric("✅ Correctes", f"{correct_pred:,} / {total_pred:,}")

    st.markdown("---")

    # --- Précision par tranche de confiance ---
    st.markdown("### 🎯 Précision par tranche de confiance")
    buckets = {"0-45%": [], "45-60%": [], "60-75%": [], "75-90%": [], "90-100%": []}
    for h in history:
        conf = (h.get("confidence") or 0) * 100
        correct = 1 if h.get("correct") else 0
        if conf < 45:
            buckets["0-45%"].append(correct)
        elif conf < 60:
            buckets["45-60%"].append(correct)
        elif conf < 75:
            buckets["60-75%"].append(correct)
        elif conf < 90:
            buckets["75-90%"].append(correct)
        else:
            buckets["90-100%"].append(correct)

    labels = list(buckets.keys())
    accuracies = [
        (sum(v) / len(v) * 100) if v else 0 for v in buckets.values()
    ]
    counts = [len(v) for v in buckets.values()]

    fig1 = go.Figure()
    fig1.add_trace(
        go.Bar(
            x=labels,
            y=accuracies,
            text=[f"{a:.0f}% (n={c})" for a, c in zip(accuracies, counts)],
            textposition="auto",
            marker_color="#33c7ff",
        )
    )
    fig1.update_layout(
        yaxis=dict(title="Précision (%)", range=[0, 100]),
        xaxis_title="Tranche de confiance",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="rgba(232,236,255,0.6)"),
        height=350,
    )
    st.plotly_chart(fig1, width='stretch')

    st.caption(
        "💡 Si la précision ne progresse pas avec la confiance, le modèle est mal calibré : "
        "il faut revoir ses features ou son entraînement."
    )

    st.markdown("---")

    # --- Précision par ligue (donnée déjà trackée par le modèle, jamais affichée jusqu'ici) ---
    league_accuracy = model_stats.get("league_accuracy", {})
    league_rows = [
        (league, stats["correct"], stats["total"])
        for league, stats in league_accuracy.items()
        if stats.get("total", 0) >= 5
    ]
    if league_rows:
        st.markdown("### 🏆 Précision par ligue")
        league_rows.sort(key=lambda r: r[1] / r[2], reverse=True)
        league_names = [r[0] for r in league_rows]
        league_accs = [r[1] / r[2] * 100 for r in league_rows]
        league_totals = [r[2] for r in league_rows]

        fig3 = go.Figure()
        fig3.add_trace(
            go.Bar(
                x=league_accs,
                y=league_names,
                orientation="h",
                text=[f"{a:.0f}% (n={t})" for a, t in zip(league_accs, league_totals)],
                textposition="auto",
                marker_color="#f5c451",
            )
        )
        fig3.update_layout(
            xaxis=dict(title="Précision (%)", range=[0, 100]),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="rgba(232,236,255,0.6)"),
            height=max(250, 40 * len(league_names)),
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig3, width="stretch")
        st.caption("Ligues avec au moins 5 matchs analysés uniquement (sinon peu significatif).")
        st.markdown("---")

    # --- Poids actuels de l'ensemble ML (auto-évaluation en direct) ---
    try:
        from ml_models import ensemble as ml_ensemble
        ens_status = ml_ensemble.status()
        weights = ens_status.get("weights", {})
        if weights:
            st.markdown("### 🧠 Poids actuels de l'ensemble ML")
            st.caption(
                "Recalculés après chaque entraînement, proportionnellement à la précision "
                "de validation récente de chaque sous-modèle (auto-évaluation)."
            )
            fig4 = go.Figure()
            fig4.add_trace(
                go.Pie(
                    labels=[k.upper() for k in weights.keys()],
                    values=list(weights.values()),
                    hole=0.5,
                    marker=dict(colors=["#33c7ff", "#f5c451", "#2ecc87", "#ff6b57", "#8bc93c"]),
                    textinfo="label+percent",
                )
            )
            fig4.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="rgba(232,236,255,0.6)"),
                height=320,
                showlegend=False,
                margin=dict(l=10, r=10, t=10, b=10),
            )
            st.plotly_chart(fig4, width="stretch")
            st.markdown("---")
    except Exception:
        pass

    # --- Courbes d'évolution de chaque modèle dans le temps ---
    try:
        from ml_models.ensemble import load_weights_history
        history_entries = load_weights_history(limit=200)
        if len(history_entries) >= 2:
            st.markdown("### 📈 Évolution des modèles dans le temps")
            st.caption(
                "Précision de validation mesurée à chaque cycle d'entraînement — "
                "permet de voir quel modèle progresse et lequel stagne ou régresse."
            )
            all_model_names = sorted({name for e in history_entries for name in e.get("accuracies", {})})
            fig5 = go.Figure()
            palette = ["#33c7ff", "#f5c451", "#2ecc87", "#ff6b57", "#8bc93c", "#c77dff",
                       "#ff9f40", "#4dd0e1", "#e57373", "#ba68c8", "#aed581"]
            for i, model_name in enumerate(all_model_names):
                x_vals, y_vals = [], []
                for e in history_entries:
                    acc = e.get("accuracies", {}).get(model_name)
                    if acc is not None:
                        x_vals.append(e.get("timestamp", ""))
                        y_vals.append(acc)
                if len(x_vals) >= 2:
                    fig5.add_trace(go.Scatter(
                        x=x_vals, y=y_vals, mode="lines+markers",
                        name=model_name.upper(),
                        line=dict(color=palette[i % len(palette)], width=2),
                        marker=dict(size=5),
                    ))
            fig5.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="rgba(232,236,255,0.6)"),
                height=420,
                margin=dict(l=10, r=10, t=30, b=10),
                yaxis=dict(title="Précision de validation", tickformat=".0%", gridcolor="rgba(232,236,255,0.1)"),
                xaxis=dict(title="Cycle d'entraînement", gridcolor="rgba(232,236,255,0.1)"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig5, width="stretch")
            st.caption(
                f"{len(history_entries)} cycles d'entraînement enregistrés. "
                "Une courbe qui monte = le modèle s'améliore avec plus de données ; "
                "une courbe plate = le modèle a atteint son plafond avec les features actuelles."
            )
        else:
            st.caption(
                "ℹ️ Pas encore assez de cycles d'entraînement enregistrés pour tracer une "
                "évolution (minimum 2). Cet historique se construit automatiquement à "
                "chaque cycle auto — reviens dans quelques heures/jours."
            )
        st.markdown("---")
    except Exception:
        pass

    # --- Distribution des pronostics 1 / X / 2 ---
    st.markdown("### ⚖️ Répartition des pronostics émis")
    pred_counts = {"1": 0, "X": 0, "2": 0}
    for h in history:
        p = h.get("prediction")
        if p in pred_counts:
            pred_counts[p] += 1

    if sum(pred_counts.values()) > 0:
        fig2 = go.Figure(
            data=[
                go.Bar(
                    x=list(pred_counts.keys()),
                    y=list(pred_counts.values()),
                    marker_color=["#2ecc87", "#f5c451", "#ff6b57"],
                    text=list(pred_counts.values()),
                    textposition="auto",
                )
            ]
        )
        fig2.update_layout(
            xaxis_title="Pronostic",
            yaxis_title="Nombre de fois émis",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="rgba(232,236,255,0.6)"),
            height=320,
        )
        st.plotly_chart(fig2, width='stretch')
    else:
        st.info("Pas de détail de pronostic ('1'/'X'/'2') disponible dans l'historique.")

    st.markdown("---")

    # --- Série récente ---
    st.markdown("### 🕒 Résultats des 20 dernières prédictions")
    recent = history[-20:]
    icons = "".join("🟢" if h.get("correct") else "🔴" for h in recent)
    st.markdown(f"<div style='font-size:22px; letter-spacing:4px;'>{icons}</div>", unsafe_allow_html=True)
    recent_acc = sum(1 for h in recent if h.get("correct")) / len(recent) * 100 if recent else 0
    st.caption(f"Précision sur cette série : {recent_acc:.1f}%")
