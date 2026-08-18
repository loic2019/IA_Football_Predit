# -*- coding: utf-8 -*-
"""api/routers/challenge.py — Écran Challenge (comparaison des modèles + portefeuille virtuel).
Réutilise challenger_model.py, challenge_engine.py, common.py et community_db.py tels quels."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_current_user
from common import run_prediction_pipeline
import challenger_model
import challenge_engine
import community_db

router = APIRouter(prefix="/challenge", tags=["challenge"])


@router.get("/comparison")
def comparison(current: dict = Depends(get_current_user)):
    snapshot = run_prediction_pipeline(limit=100, min_confidence=0.0, min_cote=1.30)
    rows = challenge_engine.get_comparison_predictions(snapshot.get("predictions", [])[:30])
    challenger_coupon = challenge_engine.build_challenger_coupon(rows, size=8)

    return {
        "challenger_available": challenger_model.is_available(),
        "challenger_load_error": challenger_model.get_load_error(),
        "model_details": challenger_model.get_model_details(),
        "comparison": rows,
        "my_coupon": snapshot.get("coupon", {}),
        "challenger_coupon": challenger_coupon,
        "multi_coupons": snapshot.get("multi_coupons", []),
    }


@router.get("/wallet")
def wallet(current: dict = Depends(get_current_user)):
    return community_db.get_wallet_stats(current["id"])


@router.post("/wallet/reset")
def wallet_reset(current: dict = Depends(get_current_user)):
    community_db.reset_wallet(current["id"])
    return {"reset": True}


class SimpleBetPayload(BaseModel):
    engine: str
    match: dict
    prediction: str
    cote: float
    stake: float


@router.post("/wallet/bet")
def wallet_bet(payload: SimpleBetPayload, current: dict = Depends(get_current_user)):
    return community_db.place_wallet_bet(
        current["id"], payload.engine, payload.match, payload.prediction, payload.cote, payload.stake
    )


class CouponBetPayload(BaseModel):
    engine: str
    label: str
    selections: list[dict]
    total_cote: float
    stake: float


@router.post("/wallet/coupon-bet")
def wallet_coupon_bet(payload: CouponBetPayload, current: dict = Depends(get_current_user)):
    return community_db.place_wallet_coupon_bet(
        current["id"], payload.engine, payload.label, payload.selections, payload.total_cote, payload.stake
    )


@router.get("/wallet/history")
def wallet_history(limit: int = 30, current: dict = Depends(get_current_user)):
    return community_db.get_wallet_history(current["id"], limit=limit)


@router.get("/wallet/coupon-history")
def wallet_coupon_history(limit: int = 20, current: dict = Depends(get_current_user)):
    return community_db.get_wallet_coupon_history(current["id"], limit=limit)


@router.get("/wallet/leaderboard")
def wallet_leaderboard(limit: int = 10, current: dict = Depends(get_current_user)):
    return community_db.get_wallet_leaderboard(limit=limit)


@router.post("/wallet/settle")
def wallet_settle(current: dict = Depends(get_current_user)):
    simple = community_db.settle_wallet_bets()
    coupons = community_db.settle_wallet_coupon_bets()
    return {"simple": simple, "coupons": coupons}
