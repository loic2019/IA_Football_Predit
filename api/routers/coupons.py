# -*- coding: utf-8 -*-
"""api/routers/coupons.py — Sauvegarde, règlement, historique des coupons.
Réutilise coupon_tracker.py tel quel, aucune logique dupliquée."""

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_current_user
from coupon_tracker import (
    save_daily_coupon,
    settle_pending_coupons,
    get_coupon_history,
    get_global_stats,
    _connect,
    _lookup_result,
)

router = APIRouter(prefix="/coupons", tags=["coupons"])


class CouponPayload(BaseModel):
    coupon: dict
    force: bool = True


@router.get("/history")
def history(limit: int = 30, current: dict = Depends(get_current_user)):
    return get_coupon_history(limit=limit)


@router.get("/stats")
def stats(current: dict = Depends(get_current_user)):
    return get_global_stats()


@router.post("/save")
def save(payload: CouponPayload, current: dict = Depends(get_current_user)):
    return save_daily_coupon(payload.coupon, force=payload.force)


@router.post("/settle")
def settle(current: dict = Depends(get_current_user)):
    return settle_pending_coupons()


@router.get("/pending/diagnose")
def diagnose_pending(current: dict = Depends(get_current_user)):
    """Pour chaque coupon en attente, indique quels matchs bloquent le règlement."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM coupon_history WHERE status = 'pending'").fetchall()
    out = []
    for row in rows:
        matches = json.loads(row["matches_json"])
        details = []
        for m in matches:
            res = _lookup_result(conn, m["match_id"], m.get("home", ""), m.get("away", ""), m.get("start_time", ""))
            details.append({
                "home": m.get("home"), "away": m.get("away"),
                "resolved": res is not None,
                "result": res.get("result") if res else None,
            })
        out.append({"coupon_id": row["id"], "coupon_date": row["coupon_date"], "matches": details})
    conn.close()
    return out
