"""
auto_learning/engine.py — Système d'auto-apprentissage post-match
===================================================================
Apprend après chaque match, détecte les dérives, ajuste les poids,
élimine les modèles peu performants, déclenche réentraînement.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import get_config
from core.paths import get_paths
from ensemble.meta_learner import record_model_outcome
from monitoring.metrics import accuracy, brier_score
from security.logger import get_logger

log = get_logger("congobet.autolearn")

STATE_PATH = get_paths().ml_weights / "auto_learning_state.json"


def _load_state() -> dict:
    """Charge l'état persisté de l'auto-learning."""
    if not STATE_PATH.exists():
        return {"cycles": 0, "drift_alerts": [], "disabled_models": [], "last_run": None}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"cycles": 0, "drift_alerts": [], "disabled_models": [], "last_run": None}


def _save_state(state: dict) -> None:
    """Persiste l'état auto-learning."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def detect_drift(model_data: dict, window: int | None = None) -> dict:
    """
    Détecte une dérive de performance sur la fenêtre récente.

    Args:
        model_data: Contenu model_data.json.
        window: Taille fenêtre ; défaut config.

    Returns:
        Dict {drift_detected, recent_accuracy, baseline_accuracy, message}.
    """
    window = window or get_config().drift_detection_window
    history = model_data.get("history", [])
    if len(history) < window * 2:
        return {"drift_detected": False, "message": "Pas assez de données"}

    recent = history[-window:]
    baseline = history[-window * 2:-window]

    recent_acc = sum(1 for h in recent if h.get("correct")) / len(recent)
    baseline_acc = sum(1 for h in baseline if h.get("correct")) / len(baseline)

    drift = baseline_acc - recent_acc > 0.08
    return {
        "drift_detected": drift,
        "recent_accuracy": round(recent_acc, 4),
        "baseline_accuracy": round(baseline_acc, 4),
        "message": f"Dérive détectée: {baseline_acc:.1%} → {recent_acc:.1%}" if drift else "Stable",
    }


def prune_underperforming_models(min_weight: float | None = None) -> list[str]:
    """
    Désactive les modèles dont le poids auto-évalué est sous le seuil.

    Args:
        min_weight: Seuil minimum ; défaut config.

    Returns:
        Liste des modèles désactivés.
    """
    min_weight = min_weight or get_config().min_model_weight
    from ml_models.ensemble import load_weights, save_weights

    weights = load_weights()
    disabled = [k for k, v in weights.items() if v < min_weight]
    if disabled:
        new_weights = {k: v for k, v in weights.items() if v >= min_weight}
        if new_weights:
            total = sum(new_weights.values())
            new_weights = {k: round(v / total, 4) for k, v in new_weights.items()}
            save_weights(new_weights, weights)
        state = _load_state()
        state["disabled_models"] = list(set(state.get("disabled_models", []) + disabled))
        _save_state(state)
        log.info("Modèles désactivés (poids faible): %s", disabled)
    return disabled


def learn_from_match(
    match: dict,
    prediction: dict,
    actual: str,
    model_data: dict,
) -> dict:
    """
    Met à jour le système après un match terminé (apprentissage incrémental).

    Args:
        match: Match source.
        prediction: Prédiction émise.
        actual: Résultat réel (1/X/2).
        model_data: ModelData.data dict.

    Returns:
        Rapport {updated, drift, meta_updates}.
    """
    cfg = get_config()
    if not cfg.auto_learn_enabled:
        return {"updated": False, "reason": "auto_learn disabled"}

    league = match.get("league", "unknown")
    breakdown = prediction.get("model_breakdown") or {}

    for model_name, info in breakdown.items():
        probs = info.get("probabilities", {})
        predicted = max(probs, key=probs.get) if probs else "?"
        record_model_outcome(league, model_name, predicted == actual)

    drift = detect_drift(model_data)
    state = _load_state()
    state["cycles"] = state.get("cycles", 0) + 1
    state["last_run"] = datetime.now().isoformat()
    if drift.get("drift_detected"):
        state.setdefault("drift_alerts", []).append({
            "at": state["last_run"],
            "message": drift["message"],
        })
        state["drift_alerts"] = state["drift_alerts"][-20:]
    _save_state(state)

    disabled = []
    if drift.get("drift_detected"):
        disabled = prune_underperforming_models()

    return {
        "updated": True,
        "drift": drift,
        "disabled_models": disabled,
        "cycle": state["cycles"],
    }


def run_auto_learning_cycle(predictor, matches: list[dict]) -> dict:
    """
    Cycle complet : entraîne, détecte dérive, ajuste poids.

    Args:
        predictor: Instance Predictor.
        matches: Matchs terminés disponibles.

    Returns:
        Rapport du cycle.
    """
    from predictor import normalize_result

    train_report = predictor.train_from_results(matches)
    drift = detect_drift(predictor.model.data)
    disabled = prune_underperforming_models() if drift.get("drift_detected") else []

    return {
        "training": train_report,
        "drift": drift,
        "disabled_models": disabled,
        "state": _load_state(),
    }
