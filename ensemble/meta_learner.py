"""
ensemble/meta_learner.py — Meta Learner contextuel
===================================================
Sélectionne dynamiquement les poids de chaque sous-modèle selon :
- championnat / ligue
- équipes (Elo, forme)
- qualité des données (cotes, météo, H2H)
- type de compétition (coupe vs championnat)
- historique de performance par modèle
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from core.paths import get_paths

META_WEIGHTS_PATH = get_paths().ml_weights / "meta_learner_weights.json"

# Poids de base par modèle (seront ajustés contextuellement)
BASE_MODEL_PRIORS: dict[str, float] = {
    "poisson": 0.12,
    "dixon_coles": 0.10,
    "elo": 0.10,
    "bayesian": 0.08,
    "logreg": 0.07,
    "rf": 0.08,
    "extra_trees": 0.07,
    "xgb": 0.10,
    "lgbm": 0.10,
    "catboost": 0.08,
    "gbc": 0.05,
    "deep": 0.05,
}


def _load_meta_state() -> dict:
    """Charge l'état persisté du meta-learner (accuracies par ligue/modèle)."""
    if not META_WEIGHTS_PATH.exists():
        return {"league_model_acc": {}, "global_acc": {}}
    try:
        with open(META_WEIGHTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"league_model_acc": {}, "global_acc": {}}


def _save_meta_state(state: dict) -> None:
    """Persiste l'état du meta-learner."""
    META_WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(META_WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def compute_context_features(match: dict, model) -> dict[str, float]:
    """
    Extrait le contexte pour la sélection de modèles.

    Args:
        match: Dict match.
        model: ModelData.

    Returns:
        Dict de features contextuelles normalisées.
    """
    league = match.get("league", "") or "unknown"
    markets = match.get("markets", {})
    league_stats = model.data.get("league_accuracy", {}).get(league, {})
    lt = league_stats.get("total", 0)
    la = league_stats.get("correct", 0) / lt if lt >= 5 else 0.4

    is_cup = 1.0 if any(k in league.upper() for k in ("CUP", "CL", "EL", "UCL", "FA")) else 0.0
    odds_quality = 1.0 if markets else 0.0
    weather = match.get("weather")
    weather_quality = 1.0 if weather else 0.0

    home_form = model.get_team_form_score(match.get("home", ""))
    away_form = model.get_team_form_score(match.get("away", ""))

    return {
        "league_accuracy": la,
        "league_sample_size": min(1.0, lt / 50.0),
        "is_cup": is_cup,
        "odds_quality": odds_quality,
        "weather_quality": weather_quality,
        "data_quality": (odds_quality + weather_quality) / 2.0,
        "form_delta": abs(home_form - away_form),
        "form_balance": 1.0 - abs(home_form - away_form),
    }


def select_model_weights(
    match: dict,
    model,
    available_models: list[str],
    base_weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """
    Calcule les poids finaux par modèle selon le contexte du match.

    Args:
        match: Dict match.
        model: ModelData.
        available_models: Modèles effectivement disponibles pour ce match.
        base_weights: Poids de validation récents (depuis ensemble_weights.json).

    Returns:
        Dict modèle → poids normalisé (somme = 1).
    """
    ctx = compute_context_features(match, model)
    meta = _load_meta_state()
    league = match.get("league", "") or "unknown"
    league_acc = meta.get("league_model_acc", {}).get(league, {})
    global_acc = meta.get("global_acc", {})

    raw: dict[str, float] = {}
    for name in available_models:
        w = BASE_MODEL_PRIORS.get(name, 0.05)

        # Fusion avec poids auto-évalués (validation)
        if base_weights and name in base_weights:
            w = 0.5 * w + 0.5 * base_weights[name]

        # Boost selon accuracy ligue-spécifique
        if name in league_acc and league_acc[name].get("total", 0) >= 5:
            acc = league_acc[name]["correct"] / league_acc[name]["total"]
            w *= 0.5 + acc

        # Boost global
        if name in global_acc:
            w *= 0.7 + global_acc[name] * 0.6

        # Ajustements contextuels
        if name in ("elo",) and ctx["odds_quality"] < 0.5:
            w *= 1.4  # Elo utile sans cotes fiables
        if name in ("poisson", "dixon_coles") and ctx["odds_quality"] > 0.8:
            w *= 1.15
        if name in ("bayesian",) and ctx["form_delta"] > 0.25:
            w *= 1.2
        if name in ("xgb", "lgbm", "catboost", "rf", "extra_trees", "deep") and ctx["data_quality"] > 0.7:
            w *= 1.1
        if name in ("dixon_coles",) and ctx["form_balance"] > 0.7:
            w *= 1.1  # Matchs serrés → correction scores bas
        if ctx["is_cup"] > 0.5 and name in ("bayesian", "elo"):
            w *= 1.15

        raw[name] = max(w, 0.01)

    total = sum(raw.values()) or 1.0
    return {k: round(v / total, 4) for k, v in raw.items()}


def record_model_outcome(
    league: str,
    model_name: str,
    correct: bool,
) -> None:
    """
    Enregistre le résultat d'un sous-modèle pour affiner le meta-learner.

    Args:
        league: Identifiant ligue.
        model_name: Nom du sous-modèle.
        correct: True si la prédiction du sous-modèle était correcte.
    """
    state = _load_meta_state()
    league_acc = state.setdefault("league_model_acc", {})
    la = league_acc.setdefault(league or "unknown", {})
    stats = la.setdefault(model_name, {"correct": 0, "total": 0})
    stats["total"] += 1
    if correct:
        stats["correct"] += 1

    ga = state.setdefault("global_acc", {})
    prev = ga.get(model_name, 0.4)
    ga[model_name] = round(prev * 0.95 + (1.0 if correct else 0.0) * 0.05, 4)

    _save_meta_state(state)


def probs_to_array(probs: dict) -> np.ndarray:
    """Convertit dict 1/X/2 en array numpy [P1, PX, P2]."""
    return np.array([probs.get("1", 0.33), probs.get("X", 0.34), probs.get("2", 0.33)], dtype=np.float64)
