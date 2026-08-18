"""
ensemble/orchestrator.py — Orchestrateur Multi-Model Ensemble enterprise
=========================================================================
Coordonne tous les sous-modèles disponibles, applique le meta-learner,
gère la dégradation gracieuse et mesure les performances d'inférence.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from core.config import get_config
from ensemble.meta_learner import select_model_weights, probs_to_array, record_model_outcome
from security.logger import get_logger

log = get_logger("congobet.ensemble")


def _collect_statistical_probs(match: dict, model, poisson_probs: dict) -> dict[str, dict]:
    """
    Collecte les probabilités des modèles statistiques.

    Args:
        match: Dict match.
        model: ModelData.
        poisson_probs: Probas Poisson déjà calculées par predictor.

    Returns:
        Dict nom_modèle → probabilités.
    """
    available = {"poisson": poisson_probs}

    try:
        from models.dixon_coles import predict_from_match as dc_predict
        available["dixon_coles"] = dc_predict(match)
    except Exception:
        pass

    try:
        from ml_models import elo as elo_mod
        available["elo"] = elo_mod.predict_proba_elo(match.get("home", ""), match.get("away", ""))
    except Exception:
        pass

    try:
        from models.bayesian import predict_from_match as bayes_predict
        available["bayesian"] = bayes_predict(match, model)
    except Exception:
        pass

    return available


def _collect_ml_probs(match: dict, model) -> dict[str, np.ndarray]:
    """
    Collecte les probabilités des modèles ML entraînés.

    Args:
        match: Dict match.
        model: ModelData.

    Returns:
        Dict nom_modèle → array [P1, PX, P2].
    """
    from feature_engineering.builder import build_feature_vector

    result: dict[str, np.ndarray] = {}
    try:
        features = build_feature_vector(match, model, extended=True).reshape(1, -1)
    except Exception:
        return result

    from ml_models import deep_model, tree_models
    from ml_models import classic_models

    ml_checks = [
        ("deep", deep_model.is_trained, deep_model.predict_proba),
        ("xgb", tree_models.is_xgb_trained, tree_models.predict_proba_xgb),
        ("lgbm", tree_models.is_lgbm_trained, tree_models.predict_proba_lgbm),
        ("catboost", tree_models.is_catboost_trained, tree_models.predict_proba_catboost),
        ("rf", tree_models.is_rf_trained, tree_models.predict_proba_rf),
        ("extra_trees", tree_models.is_extra_trees_trained, tree_models.predict_proba_extra_trees),
        ("logreg", classic_models.is_logreg_trained, classic_models.predict_proba_logreg),
        ("gbc", classic_models.is_gbc_trained, classic_models.predict_proba_gbc),
    ]

    for name, is_trained_fn, predict_fn in ml_checks:
        try:
            if is_trained_fn():
                result[name] = predict_fn(features)[0]
        except Exception:
            continue

    return result


def predict_ensemble(
    match: dict,
    model,
    poisson_probs: dict,
    base_weights: dict | None = None,
) -> dict[str, Any]:
    """
    Prédiction ensemble complète avec meta-learner.

    Args:
        match: Dict match.
        model: ModelData.
        poisson_probs: Probas Poisson pré-calculées (compat predictor.py).
        base_weights: Poids validation depuis ensemble_weights.json.

    Returns:
        Dict avec probabilities, model_breakdown, models_used, inference_ms.
    """
    t0 = time.perf_counter()
    cfg = get_config()

    stat_probs = _collect_statistical_probs(match, model, poisson_probs)
    ml_probs = _collect_ml_probs(match, model)

    available: dict[str, np.ndarray] = {}
    for name, probs in stat_probs.items():
        available[name] = probs_to_array(probs)
    available.update(ml_probs)

    if not available:
        available["poisson"] = probs_to_array(poisson_probs)

    weights = select_model_weights(
        match, model, list(available.keys()), base_weights=base_weights
    )

    combined = np.zeros(3)
    breakdown = {}
    for name, probs in available.items():
        w = weights.get(name, 0.0)
        combined += w * probs
        breakdown[name] = {
            "probabilities": {
                "1": round(float(probs[0]), 4),
                "X": round(float(probs[1]), 4),
                "2": round(float(probs[2]), 4),
            },
            "weight": round(w, 4),
        }

    combined = combined / max(combined.sum(), 1e-9)
    inference_ms = (time.perf_counter() - t0) * 1000

    if inference_ms > cfg.inference_target_ms:
        log.debug("Inférence lente: %.1f ms (cible %.0f ms)", inference_ms, cfg.inference_target_ms)

    return {
        "probabilities": {
            "1": round(float(combined[0]), 4),
            "X": round(float(combined[1]), 4),
            "2": round(float(combined[2]), 4),
        },
        "model_breakdown": breakdown,
        "models_used": list(available.keys()),
        "inference_ms": round(inference_ms, 2),
        "meta_weights": weights,
    }


def train_ensemble(matches: list[dict], model) -> dict:
    """
    Entraîne tous les sous-modèles ML + Elo + met à jour les poids.

    Args:
        matches: Matchs historiques terminés.
        model: ModelData.

    Returns:
        Rapport d'entraînement complet.
    """
    from feature_engineering.builder import build_training_matrix
    from ml_models import deep_model, tree_models, classic_models
    from ml_models import elo as elo_mod
    from ml_models.ensemble import save_weights, DEFAULT_WEIGHTS

    X, y, meta = build_training_matrix(matches, model, extended=True)
    report: dict[str, Any] = {"n_samples": len(X)}

    if len(X) < get_config().min_training_samples:
        report["status"] = "insufficient_data"
        report["message"] = f"Seulement {len(X)} match(s) — minimum {get_config().min_training_samples}."
        return report

    # Elo (chronologique)
    try:
        report["elo"] = elo_mod.train_from_matches(matches)
    except Exception as e:
        report["elo"] = {"trained": False, "reason": str(e)}

    # ML models
    for label, train_fn in [
        ("deep", deep_model.train),
        ("xgb", tree_models.train_xgb),
        ("lgbm", tree_models.train_lgbm),
        ("catboost", tree_models.train_catboost),
        ("rf", tree_models.train_rf),
        ("extra_trees", tree_models.train_extra_trees),
        ("logreg", classic_models.train_logreg),
        ("gbc", classic_models.train_gbc),
    ]:
        try:
            report[label] = train_fn(X, y)
        except Exception as e:
            report[label] = {"trained": False, "reason": str(e)}

    # Auto-évaluation des poids : les 4 modèles statistiques utilisent leur
    # accuracy RÉELLE trackée par le meta-learner (via record_model_outcome,
    # alimenté par le règlement des coupons dans coupon_tracker.py) dès que
    # suffisamment de résultats ont été observés ; sinon repli sur une
    # estimation de départ raisonnable (~40%, précision typique 1X2).
    STAT_MODEL_BASELINE = {"poisson": 0.40, "dixon_coles": 0.41, "elo": 0.39, "bayesian": 0.40}
    accuracies = dict(STAT_MODEL_BASELINE)
    try:
        from ensemble.meta_learner import _load_meta_state
        global_acc = _load_meta_state().get("global_acc", {})
        for stat_model in STAT_MODEL_BASELINE:
            if stat_model in global_acc:
                accuracies[stat_model] = global_acc[stat_model]
    except Exception:
        pass
    for label in ("deep", "xgb", "lgbm", "catboost", "rf", "extra_trees", "logreg", "gbc"):
        if report.get(label, {}).get("trained"):
            accuracies[label] = report[label]["val_acc"]

    total = sum(accuracies.values()) or 1.0
    weights = {k: round(v / total, 4) for k, v in accuracies.items() if k in accuracies}
    save_weights(weights, accuracies)

    report["status"] = "trained"
    report["weights"] = weights
    return report


def status() -> dict:
    """
    Diagnostic de l'état de l'ensemble (pour dashboard/admin).

    Returns:
        Dict avec flags trained + poids.
    """
    from ml_models import deep_model, tree_models, classic_models, elo as elo_mod
    from ml_models.ensemble import load_weights

    return {
        "deep_trained": deep_model.is_trained(),
        "xgb_trained": tree_models.is_xgb_trained(),
        "lgbm_trained": tree_models.is_lgbm_trained(),
        "catboost_trained": tree_models.is_catboost_trained(),
        "rf_trained": tree_models.is_rf_trained(),
        "extra_trees_trained": tree_models.is_extra_trees_trained(),
        "logreg_trained": classic_models.is_logreg_trained(),
        "gbc_trained": classic_models.is_gbc_trained(),
        "elo_trained": elo_mod.is_trained(),
        "weights": load_weights(),
        "deep_profile": deep_model.get_chosen_profile(),
        "feature_count": 12,
        "extended_feature_count": 300,
    }
