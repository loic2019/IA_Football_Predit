# -*- coding: utf-8 -*-
"""api/routers/predictions.py — Écran Pronostics.
Réutilise common.py et coupon_tracker.py tels quels, aucune logique dupliquée."""

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from common import run_prediction_pipeline

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("")
def get_predictions(
    limit: int = 200,
    min_confidence: float = 0.0,
    min_cote: float = 1.30,
    current: dict = Depends(get_current_user),
):
    """Génère (ou régénère) le snapshot complet : coupon conseillé, coupons
    combinés de 10 matchs, et la liste brute des prédictions."""
    return run_prediction_pipeline(limit=limit, min_confidence=min_confidence, min_cote=min_cote)
