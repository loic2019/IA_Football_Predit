# -*- coding: utf-8 -*-
"""api/routers/palmares.py — Palmarès public.
Réutilise common.get_model_stats tel quel."""

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from common import get_model_stats

router = APIRouter(prefix="/palmares", tags=["palmares"])


@router.get("")
def palmares(filter: str = "all", limit: int = 30, current: dict = Depends(get_current_user)):
    stats = get_model_stats()
    if not stats or not stats.get("history"):
        return {"available": False}

    history = stats["history"]
    total = len(history)
    won = sum(1 for e in history if e.get("correct"))
    win_rate = (won / total * 100) if total else 0

    recent = sorted(history, key=lambda e: e.get("trained_at", ""), reverse=True)

    current_streak = 0
    streak_type = None
    for e in recent:
        is_win = bool(e.get("correct"))
        if streak_type is None:
            streak_type = is_win
            current_streak = 1
        elif is_win == streak_type:
            current_streak += 1
        else:
            break

    # Courbe d'évolution de la précision cumulée
    sorted_asc = sorted(history, key=lambda e: e.get("trained_at", ""))
    cumulative_correct = 0
    evolution = []
    for i, entry in enumerate(sorted_asc, start=1):
        if entry.get("correct"):
            cumulative_correct += 1
        evolution.append({"n": i, "accuracy": round(cumulative_correct / i * 100, 1)})

    if filter == "won":
        filtered = [e for e in recent if e.get("correct")]
    elif filter == "lost":
        filtered = [e for e in recent if not e.get("correct")]
    else:
        filtered = recent

    return {
        "available": True,
        "total": total,
        "won": won,
        "win_rate": win_rate,
        "current_streak": current_streak,
        "streak_is_win": streak_type,
        "evolution": evolution,
        "tickets": filtered[:limit],
        "tickets_total": len(filtered),
    }
