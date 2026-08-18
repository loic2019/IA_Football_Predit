"""dashboard.py — Dashboard professionnel (métriques enterprise complètes).

Toutes les métriques listées par l'utilisateur : Accuracy, ROI, Yield, Brier
Score, Log Loss, Calibration, Courbe ROC, Precision, Recall, F1, Confusion
Matrix, Profit, Capital/Bankroll, Historique, Courbes, Heatmaps, temps réel.

S'appuie sur monitoring/metrics.py::compute_dashboard_metrics (déjà présent
dans le projet mais jamais affiché nulle part avant cette page).
"""

import plotly.graph_objects as go
import streamlit as st

from common import get_model_stats
from monitoring.metrics import compute_dashboard_metrics


ACCENT = "#33c7ff"
FONT_COLOR = "rgba(232,236,255,0.6)"


def _base_layout(height=350, **kwargs):
    layout = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=FONT_COLOR),
        height=height,
    )
    layout.update(kwargs)
    return layout


def render():
    st.title("📈 Dashboard Enterprise")
    st.caption("Vue d'ensemble complète des performances du modèle — mise à jour à chaque cycle automatique.")

    model_stats = get_model_stats()
    if not model_stats:
        st.info("📊 Aucune donnée de performance disponible. Entraînez d'abord le modèle.")
        return

    metrics = compute_dashboard_metrics(model_stats)

    if metrics["total_predictions"] == 0:
        st.info("📊 Pas assez de données pour établir des statistiques.")
        return

    # === KPIs temps réel =====================================================
    st.markdown("### ⚡ Statistiques temps réel")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("🎯 Accuracy", f"{metrics['accuracy']:.1%}")
    c2.metric("💰 ROI", f"{metrics['roi']:+.1%}")
    c3.metric("📈 Yield", f"{metrics['yield']:+.1%}")
    c4.metric("📉 Brier Score", f"{metrics['brier_score']:.3f}" if metrics["brier_score"] is not None else "N/A")
    c5.metric("📉 Log Loss", f"{metrics['log_loss']:.3f}" if metrics["log_loss"] is not None else "N/A")
    c6.metric("🔢 Prédictions", f"{metrics['total_predictions']:,}")

    prf = metrics.get("precision_recall_f1", {})
    if prf:
        c7, c8, c9 = st.columns(3)
        c7.metric("🎯 Precision (macro)", f"{prf.get('macro_precision', 0):.1%}")
        c8.metric("🔁 Recall (macro)", f"{prf.get('macro_recall', 0):.1%}")
        c9.metric("⚖️ F1 Score (macro)", f"{prf.get('macro_f1', 0):.1%}")

    st.markdown("---")

    # === Bankroll / Profit / Capital ========================================
    st.markdown("### 💰 Capital / Bankroll")
    bankroll = metrics.get("bankroll_curve", [])
    if not bankroll:
        st.caption(
            "Pas encore assez de paris avec cote connue pour tracer la courbe de bankroll "
            "(elle se remplit au fil des coupons réglés par le cycle automatique)."
        )
    else:
        fig_bank = go.Figure()
        fig_bank.add_trace(go.Scatter(
            x=[p["index"] for p in bankroll], y=[p["bankroll"] for p in bankroll],
            mode="lines", line=dict(color=ACCENT, width=2), fill="tozeroy",
            fillcolor="rgba(51,199,255,0.1)", name="Bankroll",
        ))
        fig_bank.update_layout(**_base_layout(
            height=320, xaxis_title="Paris réglés (chronologique)", yaxis_title="Capital (unités de mise)",
        ))
        st.plotly_chart(fig_bank, width="stretch")
        last = bankroll[-1]
        st.caption(f"💵 Profit cumulé actuel : **{last['profit_cumule']:+.2f}** unités sur {len(bankroll)} paris simulés (mise fixe 10).")

    st.markdown("---")

    # === Calibration + Confusion Matrix (côte à côte) =======================
    col_calib, col_cm = st.columns(2)

    with col_calib:
        st.markdown("### 🎯 Calibration")
        calib = metrics.get("calibration", [])
        if calib:
            fig_cal = go.Figure()
            fig_cal.add_trace(go.Scatter(
                x=[c["predicted"] for c in calib], y=[c["actual"] for c in calib],
                mode="markers+lines", marker=dict(size=10, color=ACCENT), name="Modèle",
            ))
            fig_cal.add_trace(go.Scatter(
                x=[0, 1], y=[0, 1], mode="lines",
                line=dict(color="rgba(232,236,255,0.3)", dash="dash"), name="Calibration parfaite",
            ))
            fig_cal.update_layout(**_base_layout(
                height=320, xaxis_title="Confiance prédite", yaxis_title="Taux de réussite réel",
                xaxis=dict(range=[0, 1]), yaxis=dict(range=[0, 1]),
            ))
            st.plotly_chart(fig_cal, width="stretch")
        else:
            st.caption("Pas assez de données.")

    with col_cm:
        st.markdown("### 🔲 Confusion Matrix")
        cm = metrics.get("confusion_matrix", {})
        if cm and cm.get("matrix"):
            fig_cm = go.Figure(data=go.Heatmap(
                z=cm["matrix"], x=cm["labels"], y=cm["labels"],
                colorscale=[[0, "rgba(51,199,255,0.05)"], [1, ACCENT]],
                text=cm["matrix"], texttemplate="%{text}", showscale=False,
            ))
            fig_cm.update_layout(**_base_layout(
                height=320, xaxis_title="Prédit", yaxis_title="Réel",
                yaxis=dict(autorange="reversed"),
            ))
            st.plotly_chart(fig_cm, width="stretch")
        else:
            st.caption("Pas assez de données.")

    st.markdown("---")

    # === Courbe ROC ==========================================================
    st.markdown("### 📉 Courbe ROC (one-vs-rest, par issue)")
    roc = metrics.get("roc", {})
    if roc:
        fig_roc = go.Figure()
        colors = {"1": "#33c7ff", "X": "#ffb443", "2": "#ff4d6d"}
        roc_labels = {"1": "Victoire domicile (1)", "X": "Match nul (X)", "2": "Victoire extérieur (2)"}
        any_data = False
        for lbl, data in roc.items():
            if not data.get("fpr"):
                continue
            any_data = True
            auc_txt = f"{data['auc']:.3f}" if data.get("auc") is not None else "N/A"
            fig_roc.add_trace(go.Scatter(
                x=data["fpr"], y=data["tpr"], mode="lines",
                line=dict(color=colors.get(lbl, ACCENT), width=2),
                name=f"{roc_labels.get(lbl, lbl)} (AUC={auc_txt})",
            ))
        if any_data:
            fig_roc.add_trace(go.Scatter(
                x=[0, 1], y=[0, 1], mode="lines",
                line=dict(color="rgba(232,236,255,0.25)", dash="dash"), name="Aléatoire",
            ))
            fig_roc.update_layout(**_base_layout(
                height=380, xaxis_title="Taux de faux positifs", yaxis_title="Taux de vrais positifs",
                xaxis=dict(range=[0, 1]), yaxis=dict(range=[0, 1]),
            ))
            st.plotly_chart(fig_roc, width="stretch")
        else:
            st.caption("Pas assez de données.")
    else:
        st.caption("Pas assez de données.")

    st.markdown("---")

    # === Precision / Recall / F1 par classe =================================
    if prf and prf.get("per_class"):
        st.markdown("### ⚖️ Precision / Recall / F1 par issue")
        rows = []
        labels_map = {"1": "Victoire domicile (1)", "X": "Match nul (X)", "2": "Victoire extérieur (2)"}
        for lbl, v in prf["per_class"].items():
            rows.append({
                "Issue": labels_map.get(lbl, lbl),
                "Precision": f"{v['precision']:.1%}",
                "Recall": f"{v['recall']:.1%}",
                "F1 Score": f"{v['f1']:.1%}",
            })
        st.dataframe(rows, width="stretch", hide_index=True)

    st.markdown("---")

    # === Précision par ligue (heatmap) ======================================
    league_acc = metrics.get("league_accuracy", {})
    if league_acc:
        st.markdown("### 🏆 Précision par ligue")
        leagues = [k for k, v in league_acc.items() if v.get("total", 0) >= 5]
        if leagues:
            accs = [league_acc[l]["correct"] / league_acc[l]["total"] * 100 for l in leagues]
            totals = [league_acc[l]["total"] for l in leagues]
            order = sorted(range(len(leagues)), key=lambda i: -accs[i])
            leagues = [leagues[i] for i in order]
            accs = [accs[i] for i in order]
            totals = [totals[i] for i in order]

            fig_league = go.Figure()
            fig_league.add_trace(go.Bar(
                x=accs, y=leagues, orientation="h",
                marker_color=ACCENT,
                text=[f"{a:.0f}% (n={t})" for a, t in zip(accs, totals)],
                textposition="auto",
            ))
            fig_league.update_layout(**_base_layout(
                height=max(300, len(leagues) * 28), xaxis_title="Précision (%)",
                xaxis=dict(range=[0, 100]),
            ))
            st.plotly_chart(fig_league, width="stretch")
        else:
            st.caption("Pas assez de matchs par ligue (minimum 5) pour une comparaison fiable.")

    st.markdown("---")

    # === Mes coupons réels (résultats effectifs, pas de l'entraînement) ====
    st.markdown("### 🎟️ Mes coupons réels")
    st.caption("Les coupons que tu as effectivement générés/sauvegardés, avec leur résultat une fois les matchs terminés.")
    try:
        from coupon_tracker import get_coupon_history, get_global_stats
        real_stats = get_global_stats()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Coupons réglés", real_stats.get("coupons_settled") or 0)
        c2.metric("Taux de réussite réel", f"{real_stats['accuracy']:.0%}" if real_stats.get("accuracy") is not None else "N/A")
        c3.metric("Matchs corrects", f"{real_stats.get('matches_correct') or 0} / {real_stats.get('matches_total') or 0}")
        c4.metric("ROI moyen / coupon", f"{real_stats['avg_roi']:+.2f}" if real_stats.get("avg_roi") is not None else "N/A")

        real_history = get_coupon_history(limit=10)
        if real_history:
            rows = [{
                "Date": h.get("generated_at", "")[:16].replace("T", " "),
                "Statut": "✅ Réglé" if h["status"] == "settled" else "⏳ En attente",
                "Taille": h.get("total", 0),
                "Bons pronostics": h.get("hits") if h.get("hits") is not None else "—",
                "ROI": f"{h['roi']:+.2f}" if h.get("roi") is not None else "—",
            } for h in real_history]
            st.dataframe(rows, width="stretch", hide_index=True)
            st.caption("💡 Le détail match par match de chaque coupon (bon/mauvais pronostic) est sur la page **Pronostics**, section \"Historique des coupons\".")
        else:
            st.info("Aucun coupon sauvegardé pour l'instant — utilise le bouton \"Sauvegarder ce coupon\" sur la page Pronostics.")
    except Exception as e:
        st.caption(f"Suivi des coupons indisponible : {e}")

    st.markdown("---")

    # === Historique d'entraînement (backtesting, PAS tes paris réels) ======
    st.markdown("### 🕓 Historique d'entraînement (données de calibration)")
    st.caption(
        "⚠️ Ceci N'EST PAS l'historique de tes paris réels — ce sont des matchs historiques "
        "(grandes ligues européennes, via historical_results.db) utilisés pour entraîner et "
        "calibrer le modèle en arrière-plan. Pour tes vrais coupons, voir la section "
        "\"🎟️ Mes coupons réels\" ci-dessus."
    )
    history = model_stats.get("history", [])
    if history:
        recent = list(reversed(history))[:50]
        rows = [{
            "Date": h.get("trained_at", "")[:16].replace("T", " "),
            "Match": f"{h.get('home','')} - {h.get('away','')}",
            "Ligue": h.get("league", ""),
            "Prédit": h.get("prediction", ""),
            "Réel": h.get("actual", ""),
            "Confiance": f"{h.get('confidence', 0):.0%}",
            "Correct": "✅" if h.get("correct") else "❌",
        } for h in recent]
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.caption("Aucun historique pour l'instant.")
