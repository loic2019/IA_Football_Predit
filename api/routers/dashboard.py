# -*- coding: utf-8 -*-
"""api/routers/dashboard.py — Données de l'écran Accueil/Dashboard.
Réutilise common.py, monitoring/metrics.py et historical_data_refill.py tels quels."""

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from common import (
    get_live_matches,
    get_all_matches,
    get_live_matches_count,
    get_future_matches_count,
    get_finished_matches_count,
    get_model_stats,
)
from monitoring.metrics import compute_dashboard_metrics
from historical_data_refill import get_stats as get_historical_stats

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(current: dict = Depends(get_current_user)):
    return {
        "total_matches": get_all_matches(),
        "live_count": get_live_matches_count(),
        "future_count": get_future_matches_count(),
        "finished_count": get_finished_matches_count(),
        "live_matches": get_live_matches(limit=6),
    }


@router.get("/metrics")
def metrics(current: dict = Depends(get_current_user)):
    model_stats = get_model_stats()
    if not model_stats:
        return {"available": False}
    computed = compute_dashboard_metrics(model_stats)
    return {"available": True, **computed}


@router.get("/training-history")
def training_history(current: dict = Depends(get_current_user)):
    return get_historical_stats()
