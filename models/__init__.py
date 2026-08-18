"""models — Modèles statistiques et probabilistes."""

from models.poisson import poisson_match_probs, predict_from_match as poisson_predict
from models.dixon_coles import dixon_coles_probs, predict_from_match as dixon_coles_predict
from models.bayesian import bayesian_match_probs, predict_from_match as bayesian_predict

__all__ = [
    "poisson_match_probs", "poisson_predict",
    "dixon_coles_probs", "dixon_coles_predict",
    "bayesian_match_probs", "bayesian_predict",
]
