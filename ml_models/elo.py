"""
ml_models/elo.py — Rating Elo pour le football
====================================================
Contrairement aux autres sous-modèles (XGBoost, LightGBM, réseau de
neurones), Elo ne dépend PAS des cotes du marché — seulement de l'historique
des résultats. C'est un signal complémentaire utile en particulier pour les
matchs à venir dont les cotes ne sont pas encore disponibles ou fiables.

Méthode : rating Elo classique (mise à jour K=20 après chaque match), et
conversion du différentiel de rating en probabilités 1/X/2 via un modèle
logit ordonné à 2 seuils (technique standard en analyse de paris sportifs
pour dériver une probabilité de match nul à partir d'un score continu).
"""

import json
import math
from pathlib import Path

from ml_models.model_cache import get_cached

RATINGS_PATH = Path("ml_models/weights/elo_ratings.json")
DEFAULT_RATING = 1500.0
K_FACTOR = 20.0
HOME_ADVANTAGE = 60.0  # points Elo, avantage terrain classique
DRAW_THRESHOLD = 0.24  # en unites logit ; plus grand = plus de nuls prédits


def _load_ratings() -> dict:
    if not RATINGS_PATH.exists():
        return {}
    try:
        return get_cached(RATINGS_PATH, _read_ratings_file)
    except Exception:
        return {}


def _read_ratings_file() -> dict:
    with open(RATINGS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_ratings(ratings: dict) -> None:
    RATINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RATINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(ratings, f, ensure_ascii=False, indent=2)


def get_rating(team: str, ratings: dict = None) -> float:
    ratings = ratings if ratings is not None else _load_ratings()
    return ratings.get(team, DEFAULT_RATING)


def _sigmoid(x: float) -> float:
    x = max(-30, min(30, x))  # évite l'overflow de math.exp
    return 1.0 / (1.0 + math.exp(-x))


def probs_from_ratings(elo_home: float, elo_away: float) -> dict:
    """Convertit un différentiel de rating Elo en probabilités 1/X/2
    (logit ordonné à 2 seuils, cf. docstring du module)."""
    z = (elo_home + HOME_ADVANTAGE - elo_away) / 400.0

    p_not_loss = _sigmoid(z + DRAW_THRESHOLD)   # P(pas une défaite domicile)
    p_win = _sigmoid(z - DRAW_THRESHOLD)        # P(victoire domicile nette)
    p_draw = max(0.01, p_not_loss - p_win)
    p_loss = max(0.01, 1.0 - p_not_loss)
    p_win = max(0.01, p_win)

    total = p_win + p_draw + p_loss
    return {"1": p_win / total, "X": p_draw / total, "2": p_loss / total}


def predict_proba_elo(home: str, away: str) -> dict:
    """Renvoie {"1":..,"X":..,"2":..} pour un match donné, à partir des ratings actuels."""
    ratings = _load_ratings()
    return probs_from_ratings(get_rating(home, ratings), get_rating(away, ratings))


def _update_pair(ratings: dict, home: str, away: str, result: str) -> None:
    """result: '1' (victoire domicile), 'X' (nul), '2' (victoire exterieur)."""
    elo_home = ratings.get(home, DEFAULT_RATING)
    elo_away = ratings.get(away, DEFAULT_RATING)

    expected_home = _sigmoid((elo_home + HOME_ADVANTAGE - elo_away) / 400.0)
    actual_home = {"1": 1.0, "X": 0.5, "2": 0.0}.get(result, 0.5)

    delta = K_FACTOR * (actual_home - expected_home)
    ratings[home] = elo_home + delta
    ratings[away] = elo_away - delta


def train_from_matches(matches: list[dict]) -> dict:
    """
    Rejoue l'historique dans l'ordre CHRONOLOGIQUE (essentiel pour Elo,
    contrairement aux autres sous-modèles) et met à jour les ratings.
    `matches` doit contenir 'home', 'away', 'result' (déjà normalisé en 1/X/2
    ou H/D/A — les deux formats sont acceptés) et idéalement 'start_time'
    pour le tri chronologique.
    """
    from predictor import normalize_result

    def sort_key(m):
        return m.get("start_time") or m.get("date") or m.get("scraped_at") or ""

    ordered = sorted(matches, key=sort_key)

    ratings = _load_ratings()
    processed = 0
    for m in ordered:
        result = normalize_result(m.get("result"))
        home, away = m.get("home", ""), m.get("away", "")
        if not result or not home or not away:
            continue
        _update_pair(ratings, home, away, result)
        processed += 1

    _save_ratings(ratings)
    return {"trained": True, "matches_processed": processed, "teams_rated": len(ratings)}


def is_trained() -> bool:
    return RATINGS_PATH.exists()


def top_teams(limit: int = 10) -> list[tuple]:
    """Pour affichage (page Statistiques/Admin) : classement Elo actuel."""
    ratings = _load_ratings()
    return sorted(ratings.items(), key=lambda kv: kv[1], reverse=True)[:limit]
