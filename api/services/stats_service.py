"""
Couche service pour les statistiques détaillées du modèle.

Le calcul (buckets de confiance, précision par ligue, distribution des
pronostics, série récente) est repris À L'IDENTIQUE de
`statistiques.py::render()` — seule la partie `st.*` (rendu
Streamlit/Plotly) est retirée, remplacée par un retour JSON. Aucune
formule n'est modifiée.
"""
from common import get_model_stats


def _confidence_buckets(history: list[dict]) -> dict:
    buckets = {"0-45%": [], "45-60%": [], "60-75%": [], "75-90%": [], "90-100%": []}
    for h in history:
        conf = (h.get("confidence") or 0) * 100
        correct = 1 if h.get("correct") else 0
        if conf < 45:
            buckets["0-45%"].append(correct)
        elif conf < 60:
            buckets["45-60%"].append(correct)
        elif conf < 75:
            buckets["60-75%"].append(correct)
        elif conf < 90:
            buckets["75-90%"].append(correct)
        else:
            buckets["90-100%"].append(correct)

    return {
        "labels": list(buckets.keys()),
        "accuracy": [(sum(v) / len(v) * 100) if v else 0 for v in buckets.values()],
        "count": [len(v) for v in buckets.values()],
    }


def _league_accuracy(model_stats: dict) -> list[dict]:
    league_accuracy = model_stats.get("league_accuracy", {})
    rows = [
        {"league": league, "accuracy": stats["correct"] / stats["total"] * 100, "total": stats["total"]}
        for league, stats in league_accuracy.items()
        if stats.get("total", 0) >= 5
    ]
    rows.sort(key=lambda r: r["accuracy"], reverse=True)
    return rows


def _ensemble_weights() -> dict | None:
    try:
        from ml_models import ensemble as ml_ensemble

        weights = ml_ensemble.status().get("weights", {})
        return weights or None
    except Exception:
        return None


def _weights_history() -> list[dict]:
    try:
        from ml_models.ensemble import load_weights_history

        return load_weights_history(limit=200)
    except Exception:
        return []


def _prediction_distribution(history: list[dict]) -> dict:
    counts = {"1": 0, "X": 0, "2": 0}
    for h in history:
        p = h.get("prediction")
        if p in counts:
            counts[p] += 1
    return counts


def get_full_stats() -> dict:
    model_stats = get_model_stats()
    if not model_stats:
        return {"available": False}

    history = model_stats.get("history", [])
    if not history:
        return {"available": False}

    total_pred = model_stats.get("total_predictions", len(history))
    correct_pred = model_stats.get("correct_predictions", sum(1 for h in history if h.get("correct")))
    recent = history[-20:]

    return {
        "available": True,
        "total_predictions": total_pred,
        "correct_predictions": correct_pred,
        "global_accuracy": (correct_pred / max(1, total_pred)) * 100,
        "confidence_buckets": _confidence_buckets(history),
        "league_accuracy": _league_accuracy(model_stats),
        "ensemble_weights": _ensemble_weights(),
        "weights_history": _weights_history(),
        "prediction_distribution": _prediction_distribution(history),
        "recent_results": [bool(h.get("correct")) for h in recent],
        "recent_accuracy": (sum(1 for h in recent if h.get("correct")) / len(recent) * 100) if recent else 0,
    }
