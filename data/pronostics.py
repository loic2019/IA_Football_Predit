"""Page Pronostics : donnees live et predictions via predictor.py.

MODIFICATIONS :
- Le toggle "Auto-refresh 30s" utilisait un <meta http-equiv="refresh"> qui
  force un rechargement COMPLET de la page toutes les 60s (pas 30s, et pas un
  simple rerun). Ca casse la session Streamlit -- c'est une des causes du bug
  "l'app se ferme apres quelques minutes". Remplace par un simple bouton
  d'actualisation manuelle (le cache de 30s sur load_predictions garantit deja
  des donnees fraiches sans reload agressif).
- Ajout : bouton "Suivre ce pronostic" (necessite d'etre connecte, voir
  profil.py) qui enregistre le pick dans community.db pour calcul du taux de
  reussite personnel sur la page Profil.
"""

from datetime import datetime

import json
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from common import (
    DB_PATH,
    format_date,
    load_automation_state,
    run_prediction_pipeline,
    seconds_until_next_cycle,
)
import community_db


PREDICTION_LABELS = {
    "1": "Victoire domicile",
    "X": "Match nul",
    "2": "Victoire exterieur",
}


@st.cache_data(ttl=30, show_spinner=False)
def load_predictions(limit, min_confidence, min_cote=1.30):
    snapshot = run_prediction_pipeline(limit=int(limit), min_confidence=float(min_confidence), min_cote=float(min_cote))
    return snapshot


def _prediction_rows(predictions):
    rows = []
    for pred in predictions:
        probs = pred.get("probabilities", {})
        scores = ", ".join(
            f"{s['score']} ({s['probability']:.0%})"
            for s in pred.get("exact_score_top3", [])
        )
        live_label = ""
        if pred.get("is_live"):
            live_label = f"🔴 LIVE {pred.get('live_score', '')}".strip()
        rows.append(
            {
                "Statut": live_label or "À venir",
                "Match": f"{pred.get('home', '')} - {pred.get('away', '')}",
                "Ligue": pred.get("league", ""),
                "Date": format_date(pred.get("start_time", "")),
                "Pronostic": f"{pred.get('prediction', '')} - {PREDICTION_LABELS.get(pred.get('prediction'), '')}",
                "Confiance": pred.get("confidence", 0),
                "Cote": pred.get("cote", 0),
                "Value bet": pred.get("is_value_bet", False),
                "P(1)": probs.get("1", 0),
                "P(X)": probs.get("X", 0),
                "P(2)": probs.get("2", 0),
                "Scores probables": scores,
                "Commentaire": pred.get("comment", ""),
            }
        )
    return pd.DataFrame(rows)


def _render_prediction_details(predictions):
    """Détails complets d'une prédiction (raisons, probabilités, xG, value bet)."""
    if not predictions:
        return
    st.markdown("### 🔍 Détails d'une prédiction")
    labels = [
        f"{'🔴 ' if p.get('is_live') else ''}{p.get('home','')} vs {p.get('away','')} — {p.get('prediction','')} (conf. {p.get('confidence',0):.0%})"
        for p in predictions
    ]
    selected_label = st.selectbox("Choisir un match", labels, key="details_pick_select")
    selected = predictions[labels.index(selected_label)]
    details = selected.get("details", {})

    col1, col2, col3 = st.columns(3)
    col1.metric("Confiance", f"{details.get('confidence_pct', 0):.1f}%")
    col2.metric("Cote bookmaker", details.get("bookmaker_odds", 0))
    col3.metric("Value (EV)", f"{details.get('expected_value', 0):+.2f}")

    if details.get("is_live"):
        st.info(f"🔴 Match en direct — score actuel : {details.get('live_score', 'N/A')}")

    st.markdown("**Pourquoi ce pronostic ?**")
    for reason in details.get("reasons", []):
        st.markdown(f"- {reason}")

    with st.expander("Voir les probabilités brutes par modèle"):
        st.json({
            "probabilités cotes (dé-vigées)": details.get("odds_implied_probs"),
            "probabilités Poisson (xG)": details.get("poisson_probs"),
            "xG domicile": details.get("home_xg"),
            "xG extérieur": details.get("away_xg"),
        })

    _render_team_info(selected)


def _render_team_info(selected: dict):
    """Forme récente (scores des derniers matchs) + enrichissement (blessures,
    arbitre, météo, entraîneurs) pour les 2 équipes du match sélectionné."""
    from common import get_team_info_panel

    home, away = selected.get("home", ""), selected.get("away", "")
    match_id = selected.get("id") or selected.get("match_id")
    panel = get_team_info_panel(match_id, home, away)

    st.markdown("### 🏟️ Infos équipes")
    col_home, col_away = st.columns(2)

    for col, team, recent in (
        (col_home, home, panel["home_recent"]),
        (col_away, away, panel["away_recent"]),
    ):
        with col:
            st.markdown(f"**{team}** — 5 derniers matchs")
            if not recent:
                st.caption("Aucun match passé trouvé en base pour cette équipe (équipe nouvelle, ou pas encore assez de données scrapées/enrichies).")
            else:
                for m in recent:
                    icon = {"V": "🟢", "N": "🟡", "D": "🔴"}.get(m["result"], "⚪")
                    lieu = "🏠" if m["domicile"] else "✈️"
                    st.markdown(f"{icon} {lieu} vs {m['opponent']} — **{m['score']}** _{format_date(m['date'])}_")

    enrichment = panel.get("enrichment")
    with st.expander("🩹 Blessures / arbitre / météo (API-Football)"):
        if not enrichment or not enrichment.get("referee") and not enrichment.get("injuries") and not enrichment.get("weather"):
            st.caption(
                "Pas encore de données enrichies pour ce match. Ces données ne sont récupérées "
                "qu'une fois par jour pour les 8 matchs du coupon du jour (quota API-Football "
                "gratuit limité à 100 requêtes/jour) — via le cycle automatique, pas à la demande. "
                "Si ce match fait partie du coupon du jour, réessaie après le prochain cycle."
            )
        else:
            if enrichment.get("referee"):
                st.markdown(f"**Arbitre :** {enrichment['referee']}")
            if enrichment.get("coach_home") or enrichment.get("coach_away"):
                st.markdown(f"**Entraîneurs :** {enrichment.get('coach_home', '?')} vs {enrichment.get('coach_away', '?')}")
            weather = enrichment.get("weather") or {}
            if weather:
                st.markdown(
                    f"**Météo :** {weather.get('temp', '?')}°C, "
                    f"humidité {weather.get('humidity', '?')}%, "
                    f"vent {weather.get('wind', '?')} km/h, "
                    f"pluie {weather.get('rain_prob', 0):.0%}"
                )
            injuries = enrichment.get("injuries") or []
            if injuries:
                st.markdown(f"**Blessures/absences signalées :** {len(injuries)}")
                for inj in injuries[:6]:
                    player = inj.get("player", {}).get("name", "?")
                    team_name = inj.get("team", {}).get("name", "?")
                    reason = inj.get("player", {}).get("reason", inj.get("type", ""))
                    st.caption(f"- {player} ({team_name}) — {reason}")


@st.cache_data(ttl=300, show_spinner=False)
def _load_combo_analysis():
    from congobet_combos import get_best_combo_ticket
    return get_best_combo_ticket()


def _render_congobet_combos():
    if st.button("🔄 Analyser les tickets CongoBet", key="refresh_combos"):
        _load_combo_analysis.clear()

    with st.spinner("Récupération et analyse des tickets CongoBet..."):
        try:
            result = _load_combo_analysis()
        except Exception as e:
            st.error(f"Impossible de récupérer les tickets CongoBet pour le moment : {e}")
            return

    tickets = result.get("tickets", [])
    if not tickets:
        st.info(
            "Aucun ticket combiné récupéré pour le moment. Réessaie dans quelques minutes, "
            "ou vérifie logs/congobet_combos_*.log si ça persiste."
        )
        return

    recommended = result.get("recommended")
    if recommended:
        st.success(
            f"⭐ **Ticket #{recommended['ticket_rank']} recommandé** — {recommended['n_selections']} sélections, "
            f"cote totale {recommended.get('total_cote') or '?'}, confiance moyenne "
            f"{recommended['avg_leg_confidence']:.0%} par sélection "
            f"({recommended['n_legs_estimated']}/{recommended['n_legs_total']} évaluées par notre modèle)."
        )
    else:
        st.warning("Pas assez de sélections évaluables par le modèle pour recommander un ticket en confiance.")

    st.caption(
        "Classement basé sur la **confiance moyenne par sélection** (comparable entre tickets de "
        "tailles différentes) — pas sur la probabilité brute du ticket entier, qui s'effondre "
        "mécaniquement dès qu'il y a beaucoup de sélections et favoriserait toujours les tickets courts."
    )

    # Grille responsive : 3 cartes par ligne max, plus lisible que N colonnes tassées.
    tickets_sorted = sorted(
        tickets,
        key=lambda t: (t["avg_leg_confidence"] if t["avg_leg_confidence"] is not None else -1),
        reverse=True,
    )
    n_cols = 3
    for row_start in range(0, len(tickets_sorted), n_cols):
        row_tickets = tickets_sorted[row_start:row_start + n_cols]
        cols = st.columns(n_cols)
        for col, ticket in zip(cols, row_tickets):
            is_reco = recommended and ticket["ticket_rank"] == recommended["ticket_rank"]
            avg_conf = ticket.get("avg_leg_confidence")
            avg_txt = f"{avg_conf:.0%}" if avg_conf is not None else "N/A"
            win_prob = ticket.get("estimated_win_prob")
            # Une proba brute de gain d'un ticket à 20 sélections est souvent
            # < 0.01% — l'afficher avec plus de décimales évite le "0%" opaque.
            win_txt = (f"{win_prob:.2%}" if win_prob is not None and win_prob >= 0.0001
                       else f"{win_prob:.4%}" if win_prob is not None else "N/A")
            border_color = "var(--success)" if is_reco else "var(--border)"
            coverage = f"{ticket['n_legs_estimated']}/{ticket['n_legs_total']}"

            with col:
                with st.container(border=True):
                    header_col1, header_col2 = st.columns([2, 1])
                    header_col1.markdown(f"**🎫 Ticket #{ticket['ticket_rank']}**")
                    if is_reco:
                        header_col2.markdown(":green[**⭐ À JOUER**]")
                    st.caption(f"{ticket['n_selections']} sélections — cote totale {ticket.get('total_cote') or '?'}")
                    if avg_conf is not None:
                        st.metric("Confiance moyenne / sélection", avg_txt, help=f"{coverage} sélections évaluées par le modèle")
                    else:
                        st.metric("Confiance moyenne / sélection", "N/A")
                    st.caption(f"Proba de gain du ticket entier : **{win_txt}**")

                with st.expander("Voir le détail des sélections"):
                    for leg in ticket["leg_analysis"]:
                        mp = leg.get("model_prob")
                        mp_txt = f" — notre proba : {mp:.0%}" if mp is not None else " — marché non évalué par le modèle"
                        st.caption(f"{leg['home']} vs {leg['away']} — {leg['market']} : {leg['selection']} (cote {leg.get('odds')}){mp_txt}")

    st.caption(
        "⚠️ Seules les sélections de type 1X2 et BTTS (les deux équipes marquent) sont évaluées "
        "par le modèle actuel — les autres marchés (corners, handicap...) comptent dans la "
        "couverture affichée mais pas dans le calcul de confiance, faute de données/modèle dédiés."
    )


def _render_follow_section(predictions):
    """Permet de suivre un pronostic pour le retrouver dans son profil."""
    st.markdown("### 🎯 Suivre un pronostic")

    logged_in = bool(st.session_state.get("auth_user") and st.session_state.get("user_profile"))
    if not logged_in:
        st.info("🔒 Connecte-toi depuis la page **Profil** pour suivre tes pronostics et calculer ton taux de reussite.")
        return

    if not predictions:
        return

    labels = [
        f"{p.get('home','')} vs {p.get('away','')} — {p.get('prediction','')} (conf. {p.get('confidence',0):.0%})"
        for p in predictions
    ]
    selected_label = st.selectbox("Choisir un match", labels, key="follow_pick_select")
    selected = predictions[labels.index(selected_label)]

    if st.button("➕ Suivre ce pronostic", key="follow_pick_btn"):
        profile = st.session_state.user_profile
        added = community_db.follow_pick(
            user_id=profile["id"],
            match_id=str(selected.get("match_id", "")),
            home=selected.get("home", ""),
            away=selected.get("away", ""),
            prediction=selected.get("prediction", ""),
            confidence=selected.get("confidence", 0),
            cote=selected.get("cote", 0),
        )
        if added:
            st.success("✅ Pronostic ajoute a ton profil. Le resultat sera verifie automatiquement une fois le match termine.")
        else:
            st.warning("ℹ️ Tu suis deja ce pronostic.")


def render():
    from common import render_page_header
    render_page_header("🎯", "Pronostics en temps réel", "Généré par l'ensemble Poisson + XGBoost + LightGBM + réseau de neurones")

    col_ts, col_auto = st.columns([3, 1])
    with col_ts:
        st.caption(f"Derniere lecture locale : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    with col_auto:
        auto_refresh = st.toggle("🔄 Actualisation auto (30s)", value=False, key="pronostics_autorefresh",
                                  help="Rafraîchit la page toutes les 30s sans recharger — contrairement à l'ancien "
                                       "système (retiré), qui rechargeait toute la page et cassait la session.")
    if auto_refresh:
        st_autorefresh(interval=30_000, key="pronostics_autorefresh_timer")

    if not DB_PATH.exists():
        st.warning("Base de donnees non trouvee. Lance d'abord un scraping depuis la sidebar.")
        return

    with st.container(horizontal=True):
        limit = st.number_input("Matchs a analyser", min_value=10, max_value=500, value=100, step=10)
        min_confidence = st.slider(
            "Confiance minimale",
            0,
            100,
            st.session_state.get("conf_threshold", 45),
            5,
            format="%d%%",
        ) / 100
        min_cote = st.slider(
            "Cote minimale (coupon)",
            1.00, 3.00,
            st.session_state.get("min_cote_threshold", 1.30),
            0.05,
            format="%.2f",
            help="Exclut du coupon les sélections dont la cote est inférieure à ce seuil.",
        )
        st.session_state["min_cote_threshold"] = min_cote

    if st.button(":material/refresh: Recalculer les pronostics", width="stretch"):
        load_predictions.clear()

    with st.spinner("Generation des predictions..."):
        snapshot = load_predictions(int(limit), float(min_confidence), float(min_cote))

    predictions = snapshot["predictions"]
    coupon = snapshot["coupon"]
    source_mode = snapshot["source_mode"]
    state = load_automation_state()
    remaining = seconds_until_next_cycle(state)

    if source_mode == "recent":
        st.warning("Aucun match live ou futur detecte : analyse des matchs recents disponibles.")

    with st.container(horizontal=True):
        st.metric("Matchs live", f"{snapshot['live_count']:,}", border=True)
        st.metric("Matchs futurs", f"{snapshot['future_count']:,}", border=True)
        st.metric("Pronostics retenus", f"{len(predictions):,}", border=True)
        st.metric("Cote coupon", f"{coupon.get('total_cote', 0):.2f}", border=True)

    with st.container(border=True):
        st.markdown("**Cycle automatique**")
        st.caption(
            f"Derniere generation : {format_date(snapshot.get('generated_at', ''))} | "
            f"Statut cycle : {state.get('last_cycle_status', 'never')} | "
            f"Prochain cycle : {'maintenant' if remaining == 0 else str(remaining // 60) + 'm ' + str(remaining % 60) + 's'}"
        )

    st.markdown("### 🎟️ Coupon conseillé")
    if not coupon.get("selections"):
        st.info("Aucune selection ne passe le seuil de confiance actuel.")
    else:
        col_table, col_slip = st.columns([3, 1])
        with col_table:
            coupon_df = _prediction_rows(coupon["selections"])
            st.dataframe(
                coupon_df,
                hide_index=True,
                column_config={
                    "Confiance": st.column_config.ProgressColumn(
                        "Confiance", min_value=0, max_value=1, format="percent"
                    ),
                    "P(1)": st.column_config.NumberColumn("P(1)", format="percent"),
                    "P(X)": st.column_config.NumberColumn("P(X)", format="percent"),
                    "P(2)": st.column_config.NumberColumn("P(2)", format="percent"),
                    "Cote": st.column_config.NumberColumn("Cote", format="%.2f"),
                    "Value bet": st.column_config.CheckboxColumn("Value bet"),
                },
            )
        with col_slip:
            mise = st.number_input("Mise (EUR)", min_value=1.0, value=10.0, step=1.0, key="coupon_mise")
            total_cote = coupon.get("total_cote", 0)
            gain = mise * total_cote
            st.markdown(
                f"""
                <div class="match-card" style="border-left-color:var(--gold);">
                    <div style="font-size:12px;color:var(--text-muted);">Cote totale</div>
                    <div style="font-family:var(--font-display);font-size:28px;font-weight:700;color:var(--gold);">{total_cote:.2f}x</div>
                    <div style="margin-top:10px;font-size:12px;color:var(--text-muted);">Gain potentiel</div>
                    <div style="font-family:var(--font-display);font-size:22px;font-weight:700;color:var(--success);">{gain:.0f} €</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption("⚠️ Simulation à titre indicatif — aucun pari réel n'est placé ici.")

            if st.button("💾 Sauvegarder ce coupon", key="save_coupon_btn", width="stretch"):
                from coupon_tracker import save_daily_coupon
                result = save_daily_coupon(coupon, force=True)
                if result.get("saved"):
                    st.success(f"✅ Coupon sauvegardé (id {result['coupon_id']}). Il sera vérifié automatiquement une fois les matchs terminés.")
                else:
                    st.warning(f"ℹ️ {result.get('reason', 'Non sauvegardé')}")

        # Transparence : détail par sous-modèle pour la sélection la plus confiante
        top_pick = max(coupon["selections"], key=lambda p: p.get("confidence", 0))
        if top_pick.get("model_breakdown"):
            with st.expander(f"🧠 Pourquoi ce pronostic : {top_pick['home']} vs {top_pick['away']} ?"):
                st.caption(f"Modèles utilisés : {', '.join(top_pick.get('models_used', []))}")
                for model_name, detail in top_pick["model_breakdown"].items():
                    probs = detail["probabilities"]
                    st.markdown(
                        f"**{model_name.upper()}** (poids {detail['weight']:.0%}) — "
                        f"1: {probs['1']:.0%} · X: {probs['X']:.0%} · 2: {probs['2']:.0%}"
                    )

    st.markdown("### 🎫 Tickets CongoBet analysés")
    st.caption(
        "Les tickets combinés que CongoBet propose sur sa page d'accueil (\"Top paris\"), "
        "passés au crible de notre modèle pour estimer lequel a le plus de chances de gagner."
    )
    _render_congobet_combos()

    st.markdown("### Toutes les predictions")
    if not predictions:
        st.info("Aucun pronostic disponible pour les matchs actuels.")
        return

    df = _prediction_rows(predictions)
    st.dataframe(
        df,
        hide_index=True,
        column_config={
            "Confiance": st.column_config.ProgressColumn(
                "Confiance", min_value=0, max_value=1, format="percent"
            ),
            "P(1)": st.column_config.NumberColumn("P(1)", format="percent"),
            "P(X)": st.column_config.NumberColumn("P(X)", format="percent"),
            "P(2)": st.column_config.NumberColumn("P(2)", format="percent"),
            "Cote": st.column_config.NumberColumn("Cote", format="%.2f"),
            "Value bet": st.column_config.CheckboxColumn("Value bet"),
        },
    )

    st.markdown("---")
    _render_prediction_details(predictions)
    _render_follow_section(predictions)
    st.markdown("---")
    _render_coupon_history_section()


def _render_coupon_history_section():
    """Historique réel des coupons sauvegardés : ont-ils gagné une fois réglés ?
    Corrige le problème où predictions_history.json était écrasé à chaque
    cycle et où il était impossible de savoir si un coupon avait gagné."""
    st.markdown("### 📒 Historique des coupons & performance réelle")

    try:
        from coupon_tracker import get_coupon_history, get_global_stats, get_failure_analysis, settle_pending_coupons
    except Exception as e:
        st.caption(f"Module de suivi indisponible : {e}")
        return

    if st.button("🔄 Vérifier les coupons en attente maintenant", key="settle_now_btn"):
        with st.spinner("Vérification des résultats..."):
            result = settle_pending_coupons()
            st.success(f"✅ {result['settled']} coupon(s) réglé(s), {result['still_pending']} encore en attente.")

    stats = get_global_stats()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Coupons réglés", stats.get("coupons_settled") or 0)
    col2.metric(
        "Taux de réussite réel",
        f"{stats['accuracy']:.0%}" if stats.get("accuracy") is not None else "N/A",
    )
    col3.metric("Matchs corrects", f"{stats.get('matches_correct') or 0} / {stats.get('matches_total') or 0}")
    col4.metric(
        "ROI moyen / coupon",
        f"{stats['avg_roi']:+.2f}" if stats.get("avg_roi") is not None else "N/A",
    )

    history = get_coupon_history(limit=20)
    if history:
        rows = []
        for c in history:
            rows.append({
                "Date": format_date(c.get("generated_at", "")),
                "Statut": "✅ Réglé" if c["status"] == "settled" else "⏳ En attente",
                "Taille": c.get("total", 0),
                "Bons pronostics": c.get("hits") if c.get("hits") is not None else "—",
                "ROI": f"{c['roi']:+.2f}" if c.get("roi") is not None else "—",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        st.markdown("**Voir le détail des 8 matchs d'un coupon :**")
        coupon_labels = [
            f"{format_date(c.get('generated_at',''))} — {'✅ Réglé' if c['status']=='settled' else '⏳ En attente'} "
            f"({c.get('hits','?')}/{c.get('total',0)} bons)" if c["status"] == "settled"
            else f"{format_date(c.get('generated_at',''))} — ⏳ En attente ({c.get('total',0)} matchs)"
            for c in history
        ]
        selected_coupon_label = st.selectbox("Coupon", coupon_labels, key="coupon_detail_select")
        selected_coupon = history[coupon_labels.index(selected_coupon_label)]

        # Si réglé, on a les résultats détaillés (results_json) ; sinon juste les matchs prévus.
        if selected_coupon["status"] == "settled" and selected_coupon.get("results_json"):
            detail_matches = json.loads(selected_coupon["results_json"])
        else:
            detail_matches = json.loads(selected_coupon["matches_json"])

        detail_rows = []
        for m in detail_matches:
            row = {
                "Match": f"{m.get('home','')} - {m.get('away','')}",
                "Ligue": m.get("league", ""),
                "Pronostic": m.get("prediction", ""),
                "Cote": m.get("cote", 0),
                "Confiance": f"{m.get('confidence', 0):.0%}" if m.get("confidence") else "—",
            }
            if "result" in m:  # coupon réglé : on a le vrai résultat
                row["Résultat réel"] = m.get("result", "—")
                row["✓/✗"] = "✅" if m.get("correct") else "❌"
            detail_rows.append(row)
        st.dataframe(pd.DataFrame(detail_rows), hide_index=True, width="stretch")
        st.caption(f"{len(detail_matches)} match(s) dans ce coupon.")
    else:
        st.info("Aucun coupon sauvegardé pour l'instant. Clique sur 'Sauvegarder ce coupon' ci-dessus.")

    failures = get_failure_analysis()
    if failures.get("by_league"):
        with st.expander("🔍 Voir les failles du modèle (échecs par ligue)"):
            st.caption("Ligues où le modèle se trompe le plus souvent — utile pour cibler les améliorations.")
            st.dataframe(pd.DataFrame(failures["by_league"]), hide_index=True, width="stretch")
            if failures.get("recent_failures"):
                st.markdown("**Derniers échecs :**")
                for f in failures["recent_failures"][:10]:
                    st.caption(
                        f"❌ {f['home']} vs {f['away']} ({f.get('league','')}) — "
                        f"prédit {f['predicted']}, réel {f['actual']} (confiance {f.get('confidence',0):.0%})"
                    )
