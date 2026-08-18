"""
deep_learning/transformer_models.py — Transformer / TFT (extension future)
===========================================================================
Stubs production-ready : activés automatiquement quand les poids et données
séquentielles suffisantes sont disponibles. Mixed precision et ONNX export
prévus via deep_learning/inference.py.
"""

from pathlib import Path
from typing import Optional

import numpy as np

TFT_PATH = Path("ml_models/weights/tft_model.pt")
TRANSFORMER_PATH = Path("ml_models/weights/transformer_model.pt")


def is_transformer_trained() -> bool:
    """Vérifie disponibilité du Transformer."""
    return TRANSFORMER_PATH.exists()


def is_tft_trained() -> bool:
    """Vérifie disponibilité du Temporal Fusion Transformer."""
    return TFT_PATH.exists()


def predict_proba_transformer(features: np.ndarray) -> Optional[np.ndarray]:
    """
    Inférence Transformer (stub — active quand poids présents).

    Args:
        features: Vecteur ou séquence de features.

    Returns:
        Probabilités 1/X/2 ou None.
    """
    if not is_transformer_trained():
        return None
    return None


def predict_proba_tft(features: np.ndarray) -> Optional[np.ndarray]:
    """
    Inférence Temporal Fusion Transformer.

    Args:
        features: Features temporelles multi-horizon.

    Returns:
        Probabilités ou None.
    """
    if not is_tft_trained():
        return None
    return None
