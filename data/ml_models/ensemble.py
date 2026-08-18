"""
ml_models/ensemble.py — Combine Poisson + réseau de neurones + XGBoost + LightGBM
======================================================================================
Principe de l'auto-évaluation (honnête, pas de magie) :
- Après chaque cycle d'entraînement, on mesure l'accuracy récente de CHAQUE
  sous-modèle sur un jeu de validation glissant.
- Le poids de chaque sous-modèle dans la moyenne pondérée est proportionnel à
  sa précision récente (normalisée) — un modèle qui performe mal voit son
  poids diminuer automatiquement, sans intervention manuelle.
- Tant qu'un sous-modèle n'est pas encore entraîné (pas assez de données),
  il est simplement exclu de la moyenne — l'ensemble se dégrade proprement
  vers les modèles disponibles (jamais de plantage si un modèle manque).

Fichier de poids : ml_models/weights/ensemble_weights.json
"""

import json
from pathlib import Path

import numpy as np

from feature_engineering.builder import build_feature_vector, build_training_matrix

LABEL_TO_RESULT = {0: "1", 1: "X", 2: "2"}  # cohérent avec feature_engineering.builder
from ml_models import deep_model, tree_models

WEIGHTS_PATH = Path("ml_models/weights/ensemble_weights.json")
WEIGHTS_HISTORY_PATH = Path("ml_models/weights/weights_history.jsonl")
DEFAULT_WEIGHTS = {"poisson": 1.0, "deep": 1.0, "xgb": 1.0, "lgbm": 1.0, "rf": 1.0}


def load_weights() -> dict:
    if not WEIGHTS_PATH.exists():
        return dict(DEFAULT_WEIGHTS)
    try:
        with open(WEIGHTS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("weights", dict(DEFAULT_WEIGHTS))
    except Exception:
        return dict(DEFAULT_WEIGHTS)


def save_weights(weights: dict, accuracies: dict) -> None:
    WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump({"weights": weights, "recent_accuracies": accuracies}, f, ensure_ascii=False, indent=2)

    # --- Historique persistant (append, jamais écrasé) pour tracer l'évolution
    # de chaque modèle dans le temps (précision + poids par cycle d'entraînement).
    try:
        from datetime import datetime
        entry = {
            "timestamp": datetime.now().isoformat(),
            "weights": weights,
            "accuracies": accuracies,
        }
        with open(WEIGHTS_HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # l'historique est un bonus, ne doit jamais faire planter l'entraînement


def load_weights_history(limit: int = 200) -> list[dict]:
    """Charge l'historique des poids/accuracies, un point par cycle d'entraînement."""
    if not WEIGHTS_HISTORY_PATH.exists():
        return []
    try:
        lines = WEIGHTS_HISTORY_PATH.read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(l) for l in lines if l.strip()]
        return entries[-limit:]
    except Exception:
        return []


def train_ensemble(matches: list[dict], model) -> dict:
    """
    Entraîne XGBoost, LightGBM et le réseau de neurones sur les matchs fournis
    (le modèle Poisson n'a pas de phase d'entraînement séparée — il est déjà
    utilisé nativement par predictor.Predictor.predict()).
    Met aussi à jour les poids de l'ensemble selon l'accuracy de validation de
    chaque sous-modèle.
    """
    X, y, meta = build_training_matrix(matches, model, extended=True)
    report = {"n_samples": len(X)}

    if len(X) < 40:
        report["status"] = "insufficient_data"
        report["message"] = (
            f"Seulement {len(X)} match(s) exploitable(s) — il en faut au moins 40 "
            "pour entraîner XGBoost/LightGBM/réseau de neurones. Le modèle Poisson "
            "reste utilisé seul en attendant plus de données."
        )
        return report

    try:
        report["deep"] = deep_model.train(X, y)
    except Exception as e:
        report["deep"] = {"trained": False, "reason": f"Indisponible ({e})"}

    try:
        report["xgb"] = tree_models.train_xgb(X, y)
    except Exception as e:
        report["xgb"] = {"trained": False, "reason": f"Indisponible ({e})"}

    try:
        report["lgbm"] = tree_models.train_lgbm(X, y)
    except Exception as e:
        report["lgbm"] = {"trained": False, "reason": f"Indisponible ({e})"}

    try:
        report["rf"] = tree_models.train_rf(X, y)
    except Exception as e:
        report["rf"] = {"trained": False, "reason": f"Indisponible ({e})"}

    # Auto-évaluation : pondération proportionnelle à l'accuracy de validation
    accuracies = {"poisson": 0.40}  # accuracy de référence connue (~40% sur 1X2, cf. historique)
    if report["deep"].get("trained"):
        accuracies["deep"] = report["deep"]["val_acc"]
    if report["xgb"].get("trained"):
        accuracies["xgb"] = report["xgb"]["val_acc"]
    if report["lgbm"].get("trained"):
        accuracies["lgbm"] = report["lgbm"]["val_acc"]
    if report["rf"].get("trained"):
        accuracies["rf"] = report["rf"]["val_acc"]

    total = sum(accuracies.values()) or 1.0
    weights = {k: round(v / total, 4) for k, v in accuracies.items()}
    save_weights(weights, accuracies)

    report["status"] = "trained"
    report["weights"] = weights
    return report


def predict_ensemble(match: dict, model, poisson_probs: dict) -> dict:
    """
    Combine les probabilités Poisson (déjà calculées par predictor.py) avec
    les sous-modèles ML disponibles, pondérées par leur accuracy récente.
    Renvoie {"probabilities": {...}, "model_breakdown": {...}, "models_used": [...]}.
    `poisson_probs` = dict {"1":.., "X":.., "2":..} déjà calculé par Predictor.predict().
    """
    weights = load_weights()
    available = {"poisson": np.array([poisson_probs.get("1", 0.33), poisson_probs.get("X", 0.34), poisson_probs.get("2", 0.33)])}

    try:
        features = build_feature_vector(match, model, extended=True).reshape(1, -1)
    except Exception:
        features = None

    if features is not None:
        if deep_model.is_trained():
            try:
                available["deep"] = deep_model.predict_proba(features)[0]
            except Exception:
                pass
        if tree_models.is_xgb_trained():
            try:
                available["xgb"] = tree_models.predict_proba_xgb(features)[0]
            except Exception:
                pass
        if tree_models.is_lgbm_trained():
            try:
                available["lgbm"] = tree_models.predict_proba_lgbm(features)[0]
            except Exception:
                pass
        if tree_models.is_rf_trained():
            try:
                available["rf"] = tree_models.predict_proba_rf(features)[0]
            except Exception:
                pass

    active_weights = {k: weights.get(k, 1.0) for k in available}
    total_weight = sum(active_weights.values()) or 1.0

    combined = np.zeros(3)
    breakdown = {}
    for name, probs in available.items():
        w = active_weights[name] / total_weight
        combined += w * probs
        breakdown[name] = {
            "probabilities": {"1": round(float(probs[0]), 4), "X": round(float(probs[1]), 4), "2": round(float(probs[2]), 4)},
            "weight": round(w, 4),
        }

    combined = combined / combined.sum()
    return {
        "probabilities": {"1": round(float(combined[0]), 4), "X": round(float(combined[1]), 4), "2": round(float(combined[2]), 4)},
        "model_breakdown": breakdown,
        "models_used": list(available.keys()),
    }


def status() -> dict:
    """Diagnostic rapide de l'état de l'ensemble (pour le panel admin)."""
    return {
        "deep_trained": deep_model.is_trained(),
        "xgb_trained": tree_models.is_xgb_trained(),
        "lgbm_trained": tree_models.is_lgbm_trained(),
        "rf_trained": tree_models.is_rf_trained(),
        "weights": load_weights(),
    }
