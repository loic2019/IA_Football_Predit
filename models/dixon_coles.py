"""
models/dixon_coles.py — Modèle Dixon-Coles (corrélation des scores bas)
========================================================================
Extension du Poisson qui corrige la sous-estimation des scores 0-0, 1-0, 0-1, 1-1
via un paramètre rho. Standard en industrie des paris sportifs.
"""

import math
from typing import Tuple

from models.poisson import poisson_prob, estimate_xg_from_odds


def _tau(h: int, a: int, home_xg: float, away_xg: float, rho: float) -> float:
    """
    Facteur de correction Dixon-Coles tau(i,j) pour scores bas.

    Args:
        h, a: Buts domicile / extérieur.
        home_xg, away_xg: Paramètres lambda.
        rho: Paramètre de corrélation (typiquement -0.1 à 0.0).

    Returns:
        Multiplicateur tau.
    """
    if h == 0 and a == 0:
        return 1.0 - home_xg * away_xg * rho
    if h == 0 and a == 1:
        return 1.0 + home_xg * rho
    if h == 1 and a == 0:
        return 1.0 + away_xg * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def dixon_coles_probs(
    home_xg: float,
    away_xg: float,
    rho: float = -0.13,
    max_goals: int = 8,
) -> dict[str, float]:
    """
    Probabilités 1/X/2 avec correction Dixon-Coles.

    Args:
        home_xg: xG domicile.
        away_xg: xG extérieur.
        rho: Corrélation scores bas (calibré empiriquement).
        max_goals: Plafond buts.

    Returns:
        Dict probabilités {"1", "X", "2"}.
    """
    p1, px, p2 = 0.0, 0.0, 0.0
    total = 0.0

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            base = poisson_prob(home_xg, h) * poisson_prob(away_xg, a)
            p = base * _tau(h, a, home_xg, away_xg, rho)
            total += p
            if h > a:
                p1 += p
            elif h == a:
                px += p
            else:
                p2 += p

    if total > 0:
        p1, px, p2 = p1 / total, px / total, p2 / total

    return {"1": round(p1, 4), "X": round(px, 4), "2": round(p2, 4)}


def predict_from_match(match: dict, rho: float = -0.13) -> dict[str, float]:
    """
    Prédiction Dixon-Coles pour un match.

    Args:
        match: Dict match avec markets.
        rho: Paramètre de corrélation.

    Returns:
        Probabilités 1/X/2.
    """
    from predictor import extract_probs_from_odds

    probs = extract_probs_from_odds(match.get("markets", {}))
    hxg, axg = estimate_xg_from_odds(probs)
    return dixon_coles_probs(hxg, axg, rho=rho)
