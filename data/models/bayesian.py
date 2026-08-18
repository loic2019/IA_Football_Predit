"""
models/bayesian.py — Modèle bayésien Beta-Binomial pour 1X2
=============================================================
Combine prior du marché (cotes) avec evidence historique (forme, ligue)
via mise à jour bayésienne conjuguée. Rapide, interprétable, robuste.
"""

from typing import Dict


def _beta_update(alpha: float, beta: float, success: float, weight: float = 1.0) -> tuple[float, float]:
    """
    Met à jour une distribution Beta avec observation pondérée.

    Args:
        alpha, beta: Paramètres Beta prior.
        success: Observation [0, 1] (victoire=1, nul=0.5, défaite=0).
        weight: Poids de l'observation.

    Returns:
        Tuple (alpha_post, beta_post).
    """
    return alpha + success * weight, beta + (1 - success) * weight


def bayesian_match_probs(
    market_probs: dict,
    home_form: float,
    away_form: float,
    league_accuracy: float = 0.4,
) -> dict[str, float]:
    """
    Probabilités 1/X/2 par fusion bayésienne marché + forme.

    Args:
        market_probs: Probabilités implicites cotes {"1","X","2"}.
        home_form: Score forme domicile [0,1].
        away_form: Score forme extérieur [0,1].
        league_accuracy: Précision historique du modèle sur la ligue.

    Returns:
        Probabilités postérieures normalisées.
    """
    prior_strength = 5.0 + league_accuracy * 10.0

    p1 = market_probs.get("1", 0.33)
    px = market_probs.get("X", 0.34)
    p2 = market_probs.get("2", 0.33)

    # Prior depuis le marché
    a1, b1 = p1 * prior_strength, (1 - p1) * prior_strength
    ax, bx = px * prior_strength, (1 - px) * prior_strength
    a2, b2 = p2 * prior_strength, (1 - p2) * prior_strength

    # Evidence forme
    form_weight = 3.0
    a1, b1 = _beta_update(a1, b1, home_form, form_weight)
    a2, b2 = _beta_update(a2, b2, away_form, form_weight)
    ax, bx = _beta_update(ax, bx, 0.5 - abs(home_form - away_form), form_weight * 0.5)

    post1 = a1 / (a1 + b1)
    postx = ax / (ax + bx)
    post2 = a2 / (a2 + b2)

    total = post1 + postx + post2
    return {
        "1": round(post1 / total, 4),
        "X": round(postx / total, 4),
        "2": round(post2 / total, 4),
    }


def predict_from_match(match: dict, model) -> dict[str, float]:
    """
    Prédiction bayésienne pour un match.

    Args:
        match: Dict match.
        model: Instance ModelData (forme + ligue).

    Returns:
        Probabilités 1/X/2.
    """
    from predictor import extract_probs_from_odds

    home = match.get("home", "")
    away = match.get("away", "")
    league = match.get("league", "")
    market = extract_probs_from_odds(match.get("markets", {}))
    hf = model.get_team_form_score(home)
    af = model.get_team_form_score(away)
    league_stats = model.data.get("league_accuracy", {}).get(league, {})
    lt = league_stats.get("total", 0)
    la = league_stats.get("correct", 0) / lt if lt >= 5 else 0.4
    return bayesian_match_probs(market, hf, af, la)
