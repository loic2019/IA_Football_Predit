# -*- coding: utf-8 -*-
"""
challenge_engine.py — Compare l'ensemble complet au réseau de neurones seul
================================================================================
Ne remplace RIEN : les deux moteurs de prédiction tournent en parallèle.
Pour chaque match, on compare le pronostic de l'ensemble complet (Poisson +
cotes + forme + XGBoost/LightGBM/CatBoost/Elo + 30% de réseau de neurones) à
celui du réseau de neurones utilisé SEUL, à partir des mêmes nn_features déjà
calculées par predictor.Predictor.predict() — aucun recalcul.
"""

import challenger_model


def get_comparison_predictions(ensemble_predictions: list[dict]) -> list[dict]:
    """Prend la liste de prédictions déjà calculées par ton pipeline (voir
    common.run_prediction_pipeline) et ajoute, pour chaque match, le
    pronostic du réseau de neurones interne utilisé seul, à côté."""
    rows = []
    for pred in ensemble_predictions:
        home, away = pred.get("home", ""), pred.get("away", "")
        cote = pred.get("cote", 0)

        challenger_pred = challenger_model.predict_from_nn_features(pred.get("nn_features"))

        row = {
            "match_id": pred.get("match_id"),
            "home": home,
            "away": away,
            "league": pred.get("league"),
            "cote": cote,
            "ensemble_prediction": pred.get("prediction"),
            "ensemble_confidence": pred.get("confidence"),
            "challenger_prediction": challenger_pred["prediction"] if challenger_pred else None,
            "challenger_confidence": challenger_pred["confidence"] if challenger_pred else None,
            "challenger_available": challenger_pred is not None,
        }

        if challenger_pred is None:
            row["best"] = "ensemble"  # seul disponible
        elif row["ensemble_confidence"] >= challenger_pred["confidence"]:
            row["best"] = "ensemble"
        else:
            row["best"] = "challenger"

        rows.append(row)

    return rows


def build_challenger_coupon(comparison_rows: list[dict], size: int = 8) -> dict:
    """Construit le coupon du challenger (réseau de neurones seul) de façon
    totalement indépendante de celui de ton modèle maison : ses propres
    pronostics, ses propres confiances, ses propres cotes — pas de mélange
    entre les deux."""
    eligible = [r for r in comparison_rows if r["challenger_available"] and r.get("cote")]
    eligible.sort(key=lambda r: r["challenger_confidence"], reverse=True)
    selected = eligible[:size]

    total_cote = 1.0
    for r in selected:
        total_cote *= r["cote"] or 1.0

    return {
        "size": len(selected),
        "total_cote": round(total_cote, 2),
        "selections": [
            {
                "match_id": r["match_id"], "home": r["home"], "away": r["away"], "league": r["league"],
                "prediction": r["challenger_prediction"], "confidence": r["challenger_confidence"], "cote": r["cote"],
            }
            for r in selected
        ],
    }
