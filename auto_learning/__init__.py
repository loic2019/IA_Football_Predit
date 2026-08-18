"""auto_learning — Apprentissage automatique post-match."""

from auto_learning.engine import (
    detect_drift, learn_from_match, run_auto_learning_cycle, prune_underperforming_models,
)

__all__ = [
    "detect_drift", "learn_from_match", "run_auto_learning_cycle", "prune_underperforming_models",
]
