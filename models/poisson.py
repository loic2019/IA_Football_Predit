"""
models/poisson.py — Modèle de Poisson pour scores de match
===========================================================
Réutilise la logique éprouvée de predictor.py (compatibilité totale).
"""

import math
from typing import Tuple


def poisson_prob(lam: float, k: int) -> float:
    """
    Probabilité Poisson P(X=k) pour un lambda donné.

    Args:
        lam: Paramètre lambda (taux de buts attendus).
        k: Nombre de buts.

    Returns:
        Probabilité P(X=k).
    """
    return (math.exp(-lam) * (lam ** k)) / math.factorial(k)


def poisson_match_probs(home_xg: float, away_xg: float, max_goals: int = 8) -> dict[str, float]:
    """
    Calcule les probabilités 1/X/2 via matrice de scores Poisson.

    Args:
        home_xg: xG équipe domicile.
        away_xg: xG équipe extérieur.
        max_goals: Buts maximum considérés par équipe.

    Returns:
        Dict {"1", "X", "2"} avec probabilités normalisées.
    """
    p1, px, p2 = 0.0, 0.0, 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson_prob(home_xg, h) * poisson_prob(away_xg, a)
            if h > a:
                p1 += p
            elif h == a:
                px += p
            else:
                p2 += p
    return {"1": round(p1, 4), "X": round(px, 4), "2": round(p2, 4)}


def estimate_xg_from_odds(probs: dict) -> Tuple[float, float]:
    """
    Estime home_xg et away_xg à partir des probabilités implicites des cotes.

    Args:
        probs: Dict probabilités {"1", "X", "2"}.

    Returns:
        Tuple (home_xg, away_xg) arrondis à 2 décimales.
    """
    p1 = probs.get("1", 0.33)
    p2 = probs.get("2", 0.33)
    home_xg = max(0.3, 1.2 + math.log(max(p1, 0.05)) * 0.8)
    away_xg = max(0.3, 1.2 + math.log(max(p2, 0.05)) * 0.8)
    return round(home_xg, 2), round(away_xg, 2)


def predict_from_match(match: dict) -> dict[str, float]:
    """
    Prédiction Poisson complète pour un match (via cotes).

    Args:
        match: Dict match avec markets.

    Returns:
        Probabilités 1/X/2.
    """
    from predictor import extract_probs_from_odds

    probs = extract_probs_from_odds(match.get("markets", {}))
    hxg, axg = estimate_xg_from_odds(probs)
    return poisson_match_probs(hxg, axg)
