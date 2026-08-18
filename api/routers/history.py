# -*- coding: utf-8 -*-
"""api/routers/history.py — Écran Historique des Matchs.
Réutilise common.get_finished_matches tel quel."""

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from common import get_finished_matches

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/matches")
def matches(
    search: str = "",
    league: str = "",
    limit: int = 500,
    current: dict = Depends(get_current_user),
):
    finished = get_finished_matches(limit)

    filtered = []
    for m in finished:
        if league and league != "Toutes" and str(m.get("league", "N/A")) != league:
            continue
        if search:
            s = search.lower()
            if s not in str(m.get("home", "")).lower() and s not in str(m.get("away", "")).lower():
                continue
        filtered.append(m)

    home_wins = sum(1 for m in filtered if (m.get("home_score") or 0) > (m.get("away_score") or 0))
    draws = sum(1 for m in filtered if (m.get("home_score") or 0) == (m.get("away_score") or 0))
    away_wins = sum(1 for m in filtered if (m.get("home_score") or 0) < (m.get("away_score") or 0))

    leagues = sorted({str(m.get("league", "N/A")) for m in finished})

    return {
        "matches": filtered[:200],
        "total_filtered": len(filtered),
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": away_wins,
        "leagues": leagues,
    }
