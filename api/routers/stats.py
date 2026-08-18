# -*- coding: utf-8 -*-
"""api/routers/stats.py — Écran Statistiques détaillées.
Réutilise common.get_model_stats et ml_models/ensemble.py tels quels."""

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from common import get_model_stats

router = APIRouter(prefix="/stats", tags=["stats"])

CONFIDENCE_BUCKETS = [(0, 45, "0-45%"), (45, 60, "45-60%"), (60, 75, "60-75%"), (75, 90, "75-90%"), (90, 101, "90-100%")]


@router.get("/overview")
def overview(current: dict = Depends(get_current_user)):
    model_stats = get_model_stats()
    if not model_stats or not model_stats.get("history"):
        return {"available": False}

    history = model_stats["history"]
    total = model_stats.get("total_predictions", len(history))
    correct = model_stats.get("correct_predictions", sum(1 for h in history if h.get("correct")))

    confidence_buckets = []
    for lo, hi, label in CONFIDENCE_BUCKETS:
        bucket = [h for h in history if lo <= (h.get("confidence") or 0) * 100 < hi]
        acc = (sum(1 for h in bucket if h.get("correct")) / len(bucket) * 100) if bucket else 0
        confidence_buckets.append({"label": label, "accuracy": acc, "count": len(bucket)})

    league_accuracy = model_stats.get("league_accuracy", {})
    league_rows = [
        {"league": league, "accuracy": stats["correct"] / stats["total"] * 100, "total": stats["total"]}
        for league, stats in league_accuracy.items()
        if stats.get("total", 0) >= 5
    ]
    league_rows.sort(key=lambda r: r["accuracy"], reverse=True)

    pred_counts = {"1": 0, "X": 0, "2": 0}
    for h in history:
        p = h.get("prediction")
        if p in pred_counts:
            pred_counts[p] += 1

    ensemble_weights = {}
    weights_history = []
    try:
        from ml_models import ensemble as ml_ensemble
        ensemble_weights = ml_ensemble.status().get("weights", {})
        weights_history = ml_ensemble.load_weights_history(limit=200)
    except Exception:
        pass

    recent = history[-20:]
    recent_accuracy = (sum(1 for h in recent if h.get("correct")) / len(recent) * 100) if recent else 0

    return {
        "available": True,
        "total_predictions": total,
        "correct_predictions": correct,
        "accuracy": (correct / max(1, total)) * 100,
        "confidence_buckets": confidence_buckets,
        "league_accuracy": league_rows,
        "prediction_distribution": pred_counts,
        "ensemble_weights": ensemble_weights,
        "weights_history": weights_history,
        "recent_results": [bool(h.get("correct")) for h in recent],
        "recent_accuracy": recent_accuracy,
    }
