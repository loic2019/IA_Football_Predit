"""backtest_ui.py — Moteur de backtesting complet (interface).

S'appuie sur backtesting/engine.py (déjà présent : walk_forward_validation,
monte_carlo_simulation, run_backtest — jamais exposés dans l'interface avant
cette page) + ensemble/meta_learner.py pour la comparaison des modèles.
"""

import os
import tempfile
from contextlib import contextmanager

import plotly.graph_objects as go
import streamlit as st

from historical_data import get_historical_training_matches


@contextmanager
def _sandboxed_predictor():
    """
    predictor.py utilise des chemins RELATIFS (Path("model_data.json"),
    Path("nn_weights.json")) — un choix pratique pour le script CLI, mais
    dangereux ici : sans précaution, une Predictor() créée pendant un
    backtest lirait ET écrirait dans les VRAIS fichiers de production
    (model_data.json / nn_weights.json), les corrompant avec des données
    d'entraînement partielles propres au backtest.

    Ce context manager isole chaque Predictor() créée à l'intérieur dans un
    dossier temporaire vide : elle démarre neuve (aucun historique chargé)
    et tout ce qu'elle écrit disparaît à la sortie du `with`, sans jamais
    toucher aux fichiers réels de l'application.
    """
    prev_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.chdir(tmp_dir)
        try:
            yield
        finally:
            os.chdir(prev_cwd)


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
    st.title("🧪 Backtesting")
    st.caption(
        "Simulation sur plusieurs saisons, validation chronologique (walk-forward), "
        "Monte Carlo, comparaison des modèles et optimisation de stratégie — "
        "sur les matchs historiques réels (historical_results.db)."
    )

    tab_bt, tab_wf, tab_mc, tab_cmp, tab_strat = st.tabs([
        "📊 Backtest simple", "🚶 Walk-forward", "🎲 Monte Carlo",
        "⚖️ Comparaison modèles", "🎯 Optimisation stratégie",
    ])

    # ========================================================================
    with tab_bt:
        st.markdown("### Backtest sur plusieurs saisons")
        st.caption(
            "⚠️ Ce backtest utilise le modèle de PRODUCTION actuel (déjà entraîné sur tout "
            "l'historique disponible, y compris une partie des matchs testés ici) — les chiffres "
            "peuvent donc être optimistes par rapport à une vraie performance sur données jamais "
            "vues. Pour une mesure honnête, préfère l'onglet Walk-forward (ré-entraînement isolé "
            "par fenêtre, sans cette contamination)."
        )
        n_matches = st.slider("Nombre de matchs historiques à utiliser", 100, 4000, 1000, step=100, key="bt_n")
        if st.button("▶️ Lancer le backtest", key="run_bt"):
            with st.spinner("Backtest en cours (peut prendre 1-2 minutes selon le volume)..."):
                from backtesting.engine import run_backtest
                from predictor import Predictor

                matches = get_historical_training_matches(limit=n_matches)
                predictor = Predictor()
                result = run_backtest(matches, predictor, stake=10.0)
                st.session_state["_bt_result"] = result

        result = st.session_state.get("_bt_result")
        if result:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Matchs testés", f"{result.n_matches:,}")
            c2.metric("Accuracy", f"{result.accuracy:.1%}")
            c3.metric("Brier Score", f"{result.brier:.3f}")
            c4.metric("ROI simulé", f"{result.roi_simulated:+.1%}")
            c5.metric("Yield", f"{result.yield_pct:+.1%}")

            if result.by_league:
                st.markdown("#### Précision par ligue")
                leagues = sorted(result.by_league.items(), key=lambda x: -x[1])
                fig = go.Figure(go.Bar(
                    x=[v * 100 for _, v in leagues], y=[k for k, _ in leagues],
                    orientation="h", marker_color=ACCENT,
                    text=[f"{v:.0%}" for _, v in leagues], textposition="auto",
                ))
                fig.update_layout(**_base_layout(height=max(300, len(leagues) * 26), xaxis_title="Précision (%)"))
                st.plotly_chart(fig, width="stretch")

    # ========================================================================
    with tab_wf:
        st.markdown("### Validation chronologique (walk-forward)")
        st.caption(
            "Entraîne sur une fenêtre glissante et teste toujours sur les matchs "
            "SUIVANTS chronologiquement — la seule méthode de validation qui ne "
            "triche pas en paris sportifs (pas de fuite d'information du futur)."
        )
        col1, col2, col3 = st.columns(3)
        n_matches_wf = col1.slider("Matchs historiques", 200, 4000, 1500, step=100, key="wf_n")
        min_train = col2.number_input("Matchs min. avant 1ère prédiction", 50, 2000, 300, step=50)
        step = col3.number_input("Taille du pas glissant", 10, 500, 100, step=10)

        if st.button("▶️ Lancer walk-forward", key="run_wf"):
            with st.spinner("Walk-forward en cours (ré-entraînement à chaque fenêtre — plus lent qu'avant, mais honnête)..."):
                from backtesting.engine import walk_forward_validation
                from predictor import Predictor

                matches = get_historical_training_matches(limit=n_matches_wf)

                # CORRECTIF IMPORTANT : sans ceci, walk_forward_validation()
                # était appelée sans train_fn, donc predict_fn utilisait le
                # modèle de PRODUCTION déjà entraîné sur tout l'historique
                # (passé ET futur par rapport à chaque fenêtre de test) — ce
                # n'était pas un vrai walk-forward, juste l'accuracy du
                # modèle actuel découpée par date, ce qui surestime
                # systématiquement la performance réelle. Voir l'audit :
                # ce chantier a démarré après avoir trouvé et corrigé une
                # fuite équivalente dans common.py::run_training_pipeline.
                #
                # Chaque fenêtre entraîne maintenant une Predictor() ISOLÉE
                # (sandbox, voir _sandboxed_predictor ci-dessus) UNIQUEMENT
                # sur train_set (expanding window, comme demandé : la
                # fenêtre suivante réentraîne sur train_set + les nouveaux
                # matchs, jamais sur des données futures par rapport au test).
                #
                # use_ensemble/use_neural_net désactivés ici volontairement :
                # ré-entraîner XGBoost/LightGBM/le réseau de neurones à
                # chaque fenêtre serait beaucoup trop lent pour un outil de
                # diagnostic interactif. Ce walk-forward valide le cœur
                # Poisson + cotes + forme + Elo/Dixon-Coles/bayésien
                # statistiques, pas les modèles ML lourds.
                state = {"predictor": None}

                def train_fn(train_set):
                    with _sandboxed_predictor():
                        p = Predictor(use_ensemble=False, use_neural_net=False)
                        p.train_from_results(train_set, limit=len(train_set))
                        state["predictor"] = p

                def predict_fn(m):
                    tm = dict(m)
                    tm["home_score"] = None
                    tm["away_score"] = None
                    return state["predictor"].predict(tm)

                scores = walk_forward_validation(
                    matches, predict_fn, train_fn=train_fn, min_train=min_train, step=step
                )
                st.session_state["_wf_scores"] = scores

        scores = st.session_state.get("_wf_scores")
        if scores:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=[s["window"] for s in scores], y=[s["accuracy"] * 100 for s in scores],
                mode="lines+markers", line=dict(color=ACCENT, width=2), name="Accuracy",
            ))
            fig.update_layout(**_base_layout(
                height=350, xaxis_title="Position dans l'historique (matchs)", yaxis_title="Accuracy (%)",
            ))
            st.plotly_chart(fig, width="stretch")
            avg_acc = sum(s["accuracy"] for s in scores) / len(scores)
            st.metric("Accuracy moyenne (toutes fenêtres)", f"{avg_acc:.1%}")
            st.caption(
                "💡 Une accuracy qui baisse dans le temps indique une dérive : le marché ou les "
                "équipes évoluent plus vite que le modèle ne se ré-entraîne."
            )

    # ========================================================================
    with tab_mc:
        st.markdown("### Simulation Monte Carlo (robustesse du bankroll)")
        st.caption(
            "Rejoue ton historique de paris dans un ordre aléatoire des milliers de fois, "
            "pour voir la distribution des résultats possibles (pas juste LE résultat obtenu)."
        )
        col1, col2 = st.columns(2)
        n_iter = col1.number_input("Nombre de simulations", 100, 20000, 2000, step=100)
        stake_mc = col2.number_input("Mise unitaire simulée", 1.0, 1000.0, 10.0, step=1.0)

        if st.button("▶️ Lancer Monte Carlo", key="run_mc"):
            with st.spinner("Simulation en cours..."):
                from backtesting.engine import monte_carlo_simulation
                from common import get_model_stats

                model_stats = get_model_stats() or {}
                history = [h for h in model_stats.get("history", []) if h.get("cote")]
                if not history:
                    st.warning("Pas assez d'historique avec cote connue pour simuler.")
                else:
                    mc = monte_carlo_simulation(history, n_iterations=int(n_iter), stake=float(stake_mc))
                    st.session_state["_mc_result"] = mc

        mc = st.session_state.get("_mc_result")
        if mc:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Profit médian", f"{mc['median_profit']:+.0f}")
            c2.metric("Profit moyen", f"{mc['mean_profit']:+.0f}")
            c3.metric("P5 (pessimiste)", f"{mc['p5_profit']:+.0f}")
            c4.metric("P95 (optimiste)", f"{mc['p95_profit']:+.0f}")
            st.metric("⚠️ Probabilité de ruine", f"{mc['prob_ruin']:.1%}")
            st.caption(
                f"Sur {mc['iterations']:,} simulations, capital de départ 1000. "
                "P5/P95 = intervalle de confiance à 90% du profit final."
            )

    # ========================================================================
    with tab_cmp:
        st.markdown("### Comparaison des modèles")
        st.caption(
            "Précision de chaque sous-modèle (Poisson, Dixon-Coles, Elo, Bayésien, XGBoost...) "
            "suivie en continu par le meta-learner à chaque coupon réglé."
        )
        try:
            from ensemble.meta_learner import _load_meta_state
            state = _load_meta_state()
            global_acc = state.get("global_acc", {})
        except Exception:
            global_acc = {}

        if not global_acc:
            st.info("Pas encore de données de comparaison — se remplit au fil des coupons réglés par le cycle automatique.")
        else:
            items = sorted(global_acc.items(), key=lambda x: -x[1])
            fig = go.Figure(go.Bar(
                x=[v * 100 for _, v in items], y=[k for k, _ in items],
                orientation="h", marker_color=ACCENT,
                text=[f"{v:.1%}" for _, v in items], textposition="auto",
            ))
            fig.update_layout(**_base_layout(height=max(300, len(items) * 30), xaxis_title="Précision (moyenne mobile, %)"))
            st.plotly_chart(fig, width="stretch")
            st.caption("💡 Ces précisions pilotent directement la pondération dynamique du meta-learner (les meilleurs modèles pèsent plus lourd).")

    # ========================================================================
    with tab_strat:
        st.markdown("### Optimisation de stratégie (seuil de confiance)")
        st.caption(
            "Teste plusieurs seuils de confiance minimum pour le coupon et compare le ROI/yield "
            "résultant — pour trouver le seuil qui maximise la rentabilité, pas juste l'accuracy."
        )
        if st.button("▶️ Tester les seuils", key="run_strat"):
            with st.spinner("Test des seuils en cours..."):
                from common import get_model_stats
                from monitoring.metrics import roi as roi_fn, yield_metric

                model_stats = get_model_stats() or {}
                history = [h for h in model_stats.get("history", []) if h.get("cote")]
                thresholds = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]
                rows = []
                for thr in thresholds:
                    subset = [h for h in history if h.get("confidence", 0) >= thr]
                    if not subset:
                        rows.append({"Seuil": f"{thr:.0%}", "Paris": 0, "Accuracy": "N/A", "ROI": "N/A", "Yield": "N/A"})
                        continue
                    stakes = [10.0 for _ in subset]
                    returns = [10.0 * float(h["cote"]) if h.get("correct") else 0.0 for h in subset]
                    acc = sum(1 for h in subset if h.get("correct")) / len(subset)
                    r = roi_fn(stakes, returns)
                    y = yield_metric(sum(returns) - sum(stakes), sum(stakes))
                    rows.append({
                        "Seuil": f"{thr:.0%}", "Paris": len(subset),
                        "Accuracy": f"{acc:.1%}", "ROI": f"{r:+.1%}", "Yield": f"{y:+.1%}",
                    })
                st.session_state["_strat_rows"] = rows

        rows = st.session_state.get("_strat_rows")
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
            st.caption("💡 Un seuil trop haut réduit le nombre de paris (moins de volume) mais peut améliorer le ROI par pari — cherche le meilleur compromis pour ton usage.")
