"""
ml_models/feature_engineering.py — Construction des features pour l'ensemble ML
====================================================================================
Toutes les features viennent de calculs déjà utilisés par predictor.py (cotes,
xG estimé, forme d'équipe, poids de ligue) — rien n'est inventé, tout est
dérivé de vraies données (cotes réelles ou, à défaut, probabilités par défaut
33/34/33 déjà utilisées ailleurs dans le projet).

FEATURE_NAMES documente l'ordre exact des colonnes du vecteur — à ne jamais
changer sans réentraîner tous les modèles (l'ordre est un contrat implicite).
"""

import numpy as np

FEATURE_NAMES = [
    "odds_prob_1", "odds_prob_x", "odds_prob_2",
    "poisson_prob_1", "poisson_prob_x", "poisson_prob_2",
    "home_xg", "away_xg",
    "home_form", "away_form", "form_delta",
    "league_boost",
]

RESULT_TO_LABEL = {"1": 0, "X": 1, "2": 2}
LABEL_TO_RESULT = {0: "1", 1: "X", 2: "2"}


def build_feature_vector(match: dict, model) -> np.ndarray:
    """
    Construit le vecteur de features pour UN match, en réutilisant les
    fonctions de predictor.py. `model` est une instance de predictor.ModelData
    (pour la forme d'équipe et le boost de ligue).
    """
    from predictor import extract_probs_from_odds, estimate_xg_from_odds, poisson_match_probs

    home = match.get("home", "")
    away = match.get("away", "")
    league = match.get("league", "")
    markets = match.get("markets", {})

    odds_probs = extract_probs_from_odds(markets)
    home_xg, away_xg = estimate_xg_from_odds(odds_probs)
    poisson_probs = poisson_match_probs(home_xg, away_xg)

    home_form = model.get_team_form_score(home)
    away_form = model.get_team_form_score(away)
    league_boost = model.get_league_boost(league)

    return np.array([
        odds_probs.get("1", 0.33), odds_probs.get("X", 0.34), odds_probs.get("2", 0.33),
        poisson_probs.get("1", 0.33), poisson_probs.get("X", 0.34), poisson_probs.get("2", 0.33),
        home_xg, away_xg,
        home_form, away_form, home_form - away_form,
        league_boost,
    ], dtype=np.float32)


def build_training_matrix(matches: list[dict], model) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """
    Construit (X, y, meta) à partir d'une liste de matchs terminés avec résultat connu.
    `meta` garde home/away/league/match_id pour le suivi/debug.
    Les matchs sans résultat exploitable (normalize_result vide) sont ignorés.
    """
    from predictor import normalize_result

    X_rows, y_rows, meta_rows = [], [], []
    for match in matches:
        label_str = normalize_result(match.get("result"))
        if not label_str or label_str not in RESULT_TO_LABEL:
            continue
        try:
            features = build_feature_vector(match, model)
        except Exception:
            continue
        X_rows.append(features)
        y_rows.append(RESULT_TO_LABEL[label_str])
        meta_rows.append({
            "match_id": match.get("id", ""),
            "home": match.get("home", ""),
            "away": match.get("away", ""),
            "league": match.get("league", ""),
        })

    if not X_rows:
        return np.empty((0, len(FEATURE_NAMES)), dtype=np.float32), np.empty((0,), dtype=np.int64), []

    return np.vstack(X_rows), np.array(y_rows, dtype=np.int64), meta_rows
