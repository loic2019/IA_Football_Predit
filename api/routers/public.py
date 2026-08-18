# -*- coding: utf-8 -*-
"""api/routers/public.py — Vitrine publique (SANS authentification).
Affichée sur l'écran de connexion : preuve de résultats réels avant même
de se connecter. Réutilise common.get_model_stats tel quel, lecture seule,
aucune donnée personnelle exposée."""

from fastapi import APIRouter

from common import get_model_stats

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/showcase")
def showcase():
    stats = get_model_stats()
    if not stats or not stats.get("history"):
        return {"available": False}

    history = stats["history"]
    total = len(history)
    won = sum(1 for h in history if h.get("correct"))
    win_rate = round(won / total * 100, 1) if total else 0

    recent_wins = [h for h in reversed(history) if h.get("correct")][:5]
    tickets = [
        {
            "home": h.get("home"),
            "away": h.get("away"),
            "league": h.get("league"),
            "prediction": h.get("prediction"),
            "cote": h.get("cote"),
        }
        for h in recent_wins
    ]

    return {
        "available": True,
        "total_predictions": total,
        "win_rate": win_rate,
        "tickets": tickets,
    }
