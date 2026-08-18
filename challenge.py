# -*- coding: utf-8 -*-
"""
challenge.py — Page "Challenge" : ton modèle vs le réseau de neurones seul,
+ portefeuille virtuel par utilisateur (gestion de budget, sans argent réel).
================================================================================
Ne remplace RIEN : les deux moteurs de prédiction (ton pipeline complet ET le
réseau de neurones interne utilisé seul) tournent en parallèle, comparés
côte à côte. Chaque utilisateur a son propre portefeuille virtuel (100 000
Frs de départ) pour s'entraîner à gérer un budget de paris sans risque réel.
"""

import streamlit as st

import challenger_model
import challenge_engine
import community_db
from common import run_prediction_pipeline, get_model_stats, is_logged_in, get_current_profile
from historical_data_refill import get_stats as get_historical_stats


def _require_login():
    if not is_logged_in():
        st.warning("Connecte-toi pour accéder au Challenge.")
        st.stop()
    return get_current_profile()


def render():
    profile = _require_login()
    st.title("🥊 Challenge — Ensemble complet vs réseau de neurones seul")

    st.caption(
        "Comparaison indicative entre ton pipeline complet (Poisson + cotes + forme + "
        "xgboost/lightgbm/catboost/Elo + 30% de réseau de neurones) et ce même réseau de "
        "neurones utilisé SEUL, sans le reste de l'ensemble. Aucun des deux ne remplace "
        "l'autre — c'est purement comparatif : est-ce que le réseau apporte plus dilué "
        "dans l'ensemble, ou livré à lui-même ?"
    )

    if not challenger_model.is_available():
        err = challenger_model.get_load_error()
        st.info("🧬 Réseau de neurones interne pas encore prêt pour cette comparaison.")
        if err:
            with st.expander("Détail"):
                st.code(err)

    st.markdown("---")

    # === Détails des 2 modèles ================================================
    st.markdown("### 🧠 Détails des modèles")
    d1, d2 = st.columns(2)

    with d1:
        st.markdown("#### 🏠 Mon modèle (maison)")
        hist_stats = get_historical_stats()
        model_stats = get_model_stats() or {}
        st.markdown(
            f"""
            - **Architecture** : xgboost + lightgbm + catboost + Elo + réseau de neurones (ensemble)
            - **Données d'entraînement** : matchs réels Congobet/1xBet/Premierbet + jusqu'à {hist_stats['capacity']:,} matchs historiques en rotation (actuellement {hist_stats['total']:,})
            - **Prédictions générées à ce jour** : {model_stats.get('total_predictions', 0)}
            - **Avantage** : entraîné spécifiquement sur les équipes/cotes qui apparaissent réellement sur Congobet
            """.replace(",", " ")
        )

    with d2:
        st.markdown("#### 🧬 Réseau de neurones (seul)")
        details = challenger_model.get_model_details()
        st.markdown(
            f"""
            - **Source** : {details['source']}
            - **Architecture** : {details['architecture']}
            - **Données d'entraînement** : {details['training_data']}
            - **Entrées** : {details['inputs']}
            """
        )
        with st.expander("⚠️ Limites connues"):
            for lim in details["limitations"]:
                st.caption(f"• {lim}")

    st.markdown("---")

    # === Les 2 coupons de 8 matchs, indépendants ==============================
    st.markdown("### 🎟️ Les 2 coupons de 8 matchs")
    with st.spinner("Génération des pronostics des deux modèles..."):
        snapshot = run_prediction_pipeline(limit=100, min_confidence=0.0, min_cote=1.30)
        comparison = challenge_engine.get_comparison_predictions(snapshot.get("predictions", [])[:30])
        challenger_coupon = challenge_engine.build_challenger_coupon(comparison, size=8)

    my_coupon = snapshot.get("coupon", {})

    coup1, coup2 = st.columns(2)
    with coup1:
        st.markdown(f"#### 🏠 Mon coupon — {my_coupon.get('size', 0)} matchs")
        st.metric("Cote totale", f"{my_coupon.get('total_cote', 0):.2f}")
        for sel in my_coupon.get("selections", []):
            st.markdown(
                f"**{sel.get('home')} vs {sel.get('away')}**  \n"
                f":gray[{sel.get('league', '')}] — {sel.get('prediction')} "
                f"(confiance {sel.get('confidence', 0):.0%}, cote {sel.get('cote', 0):.2f})"
            )

    with coup2:
        st.markdown(f"#### 🧬 Coupon Réseau de neurones (seul) — {challenger_coupon['size']} matchs")
        if challenger_coupon["size"] == 0:
            st.caption("Réseau de neurones pas encore entraîné, ou aucun match éligible actuellement.")
        else:
            st.metric("Cote totale", f"{challenger_coupon['total_cote']:.2f}")
            for sel in challenger_coupon["selections"]:
                st.markdown(
                    f"**{sel['home']} vs {sel['away']}**  \n"
                    f":gray[{sel['league'] or ''}]— {sel['prediction']} "
                    f"(confiance {sel['confidence']:.0%}, cote {sel['cote']:.2f})"
                )

    st.markdown("---")

    # === Comparaison détaillée match par match (repliée) ======================
    with st.expander("📊 Voir la comparaison détaillée match par match"):
        available_count = sum(1 for r in comparison if r["challenger_available"])
        st.caption(f"{available_count} / {len(comparison)} matchs évalués par le réseau de neurones seul.")
        for row in comparison:
            cols = st.columns([3, 2, 2, 1.2])
            cols[0].markdown(f"**{row['home']} vs {row['away']}**  \n:gray[{row['league'] or ''}]")
            best_ensemble = row["best"] == "ensemble"
            ens_label = f"{row['ensemble_prediction']} ({row['ensemble_confidence']:.0%})"
            cols[1].markdown(f"{'🏆 ' if best_ensemble else ''}**Mon modèle**  \n{ens_label}")
            if row["challenger_available"]:
                best_chal = row["best"] == "challenger"
                chal_label = f"{row['challenger_prediction']} ({row['challenger_confidence']:.0%})"
                cols[2].markdown(f"{'🏆 ' if best_chal else ''}**Réseau seul**  \n{chal_label}")
            else:
                cols[2].markdown("**Réseau seul**  \n:gray[indisponible]")
            cols[3].markdown(f"Cote  \n**{row['cote']:.2f}**" if row["cote"] else "—")

    st.markdown("---")

    # === Portefeuille virtuel ================================================
    st.markdown("### 💰 Mon portefeuille virtuel (gestion de budget)")
    stats = community_db.get_wallet_stats(profile["id"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Solde actuel", f"{stats['balance']:,.0f} Frs".replace(",", " "))
    c2.metric("Gains/pertes", f"{stats['pnl']:+,.0f} Frs".replace(",", " "))
    c3.metric("Paris réglés", f"{stats['won']}/{stats['won'] + stats['lost']}" if (stats['won'] + stats['lost']) else "0")
    c4.metric("Taux de réussite", f"{stats['win_rate']:.0f}%" if stats["win_rate"] is not None else "—")

    if stats["pending"]:
        st.caption(f"⏳ {stats['pending']} pari(s) en attente de résultat.")

    st.markdown("#### 🎟️ Parier sur un coupon ENTIER (recommandé)")
    st.caption(
        "Un seul pari sur plusieurs matchs combinés : la cote totale s'applique d'un coup, "
        "mais il faut que TOUS les matchs du ticket soient gagnants pour toucher le gain — "
        "comme un vrai coupon combiné."
    )

    coupon_options = {}
    if my_coupon.get("selections"):
        coupon_options[f"🏠 Mon coupon ({my_coupon['size']} matchs, cote {my_coupon.get('total_cote', 0):.2f})"] = (
            "ensemble", my_coupon["selections"], my_coupon.get("total_cote", 0)
        )
    if challenger_coupon["size"] > 0:
        coupon_options[f"🧬 Coupon réseau seul ({challenger_coupon['size']} matchs, cote {challenger_coupon['total_cote']:.2f})"] = (
            "challenger", challenger_coupon["selections"], challenger_coupon["total_cote"]
        )
    multi_coupons = snapshot.get("multi_coupons", [])
    for mc in multi_coupons:
        coupon_options[f"🎟️ {mc['label']} ({mc['size']} matchs, cote {mc['total_cote']:.2f})"] = (
            "ensemble", mc["selections"], mc["total_cote"]
        )

    if coupon_options:
        chosen_label = st.selectbox("Choisis le coupon à parier", list(coupon_options.keys()), key="coupon_bet_select")
        engine_key, selections, total_cote = coupon_options[chosen_label]

        with st.expander("Voir le détail des matchs de ce coupon"):
            for sel in selections:
                st.caption(f"{sel['home']} vs {sel['away']} — {sel['prediction']} (cote {sel.get('cote', 0):.2f})")

        coupon_stake = st.number_input(
            "Mise sur ce coupon (Frs)", min_value=100,
            max_value=int(stats["balance"]) if stats["balance"] > 0 else 100,
            value=min(5000, int(stats["balance"])) if stats["balance"] > 0 else 100, step=500, key="coupon_stake",
        )
        gain_potentiel = coupon_stake * total_cote
        st.caption(f"💵 Gain potentiel si TOUT le coupon est gagnant : **{gain_potentiel:,.0f} Frs**".replace(",", " "))

        if st.button("🎯 Placer ce coupon", type="primary", key="place_coupon_bet"):
            result = community_db.place_wallet_coupon_bet(
                profile["id"], engine_key, chosen_label, selections, total_cote, float(coupon_stake)
            )
            if result["placed"]:
                st.success(f"✅ Coupon placé — nouveau solde : {result['new_balance']:,.0f} Frs".replace(",", " "))
                st.rerun()
            else:
                st.error(result["reason"])
    else:
        st.caption("Aucun coupon disponible pour l'instant.")

    st.markdown("---")
    st.markdown("#### 🎯 Ou parier sur un seul match")
    options = [f"{r['home']} vs {r['away']}" for r in comparison]
    if options:
        idx = st.selectbox("Match", range(len(options)), format_func=lambda i: options[i])
        chosen = comparison[idx]

        engine_choices = ["Mon modèle"]
        if chosen["challenger_available"]:
            engine_choices.append("Réseau seul")
        engine_label = st.radio("Suivre le pronostic de :", engine_choices, horizontal=True)
        engine_key = "ensemble" if engine_label == "Mon modèle" else "challenger"
        prediction = chosen["ensemble_prediction"] if engine_key == "ensemble" else chosen["challenger_prediction"]

        stake = st.number_input("Mise (Frs)", min_value=100, max_value=int(stats["balance"]) if stats["balance"] > 0 else 100,
                                 value=min(2000, int(stats["balance"])) if stats["balance"] > 0 else 100, step=100)

        if st.button("🎯 Placer ce pari virtuel", type="primary"):
            result = community_db.place_wallet_bet(
                profile["id"], engine_key,
                {"id": chosen["match_id"], "home": chosen["home"], "away": chosen["away"], "league": chosen["league"]},
                prediction, chosen["cote"] or 1.5, float(stake),
            )
            if result["placed"]:
                st.success(f"✅ Pari placé — nouveau solde : {result['new_balance']:,.0f} Frs".replace(",", " "))
                st.rerun()
            else:
                st.error(result["reason"])
    else:
        st.caption("Aucun match disponible pour parier pour l'instant.")

    if st.button("🔄 Réinitialiser mon portefeuille (100 000 Frs)"):
        community_db.reset_wallet(profile["id"])
        st.rerun()

    st.markdown("---")

    # === Historique ===========================================================
    st.markdown("### 📜 Historique de mes coupons pariés")
    coupon_history = community_db.get_wallet_coupon_history(profile["id"], limit=20)
    if coupon_history:
        rows = [{
            "Date": h["placed_at"][:16].replace("T", " "),
            "Coupon": h["label"],
            "Matchs": len(h["legs"]),
            "Cote totale": h["total_cote"],
            "Mise": h["stake"],
            "Statut": {"won": "✅ Gagné", "lost": "❌ Perdu", "pending": "⏳ En attente"}.get(h["status"], h["status"]),
        } for h in coupon_history]
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.caption("Aucun coupon parié pour l'instant.")

    st.markdown("### 📜 Historique de mes paris simples")
    history = community_db.get_wallet_history(profile["id"], limit=30)
    if history:
        rows = [{
            "Date": h["placed_at"][:16].replace("T", " "),
            "Match": f"{h['home']} vs {h['away']}",
            "Modèle": "Mon modèle" if h["engine"] == "ensemble" else "Réseau seul",
            "Pronostic": h["prediction"],
            "Cote": h["cote"],
            "Mise": h["stake"],
            "Statut": {"won": "✅ Gagné", "lost": "❌ Perdu", "pending": "⏳ En attente"}.get(h["status"], h["status"]),
        } for h in history]
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.caption("Aucun pari virtuel pour l'instant.")

    st.markdown("---")
    st.markdown("### 🏆 Classement des meilleurs gestionnaires de budget")
    leaderboard = community_db.get_wallet_leaderboard(limit=10)
    if leaderboard:
        rows = [{
            "Joueur": f"{l['avatar_emoji']} {l['pseudo']}",
            "Solde": f"{l['balance']:,.0f} Frs".replace(",", " "),
            "Performance": f"{(l['balance'] - l['initial_balance']) / l['initial_balance'] * 100:+.1f}%",
        } for l in leaderboard]
        st.dataframe(rows, width="stretch", hide_index=True)
