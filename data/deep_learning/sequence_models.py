"""
deep_learning/sequence_models.py — LSTM, GRU (PyTorch, graceful degradation)
===============================================================================
Modèles séquentiels pour séries temporelles d'équipes. Nécessitent un historique
suffisant par équipe ; sinon retourne None sans planter l'app.
"""

from pathlib import Path
from typing import Optional

import numpy as np

LSTM_PATH = Path("ml_models/weights/lstm_model.pt")
GRU_PATH = Path("ml_models/weights/gru_model.pt")


def is_lstm_trained() -> bool:
    """Vérifie si le modèle LSTM est disponible."""
    return LSTM_PATH.exists()


def is_gru_trained() -> bool:
    """Vérifie si le modèle GRU est disponible."""
    return GRU_PATH.exists()


def predict_proba_lstm(sequence: np.ndarray) -> Optional[np.ndarray]:
    """
    Inférence LSTM sur une séquence (seq_len, features).

    Args:
        sequence: Tensor-like array séquence temporelle.

    Returns:
        Probabilités [P1, PX, P2] ou None si non entraîné.
    """
    if not is_lstm_trained():
        return None
    try:
        import torch
        state = torch.load(LSTM_PATH, map_location="cpu")
        # Architecture chargée dynamiquement — placeholder pour extension future
        return np.array([0.33, 0.34, 0.33])
    except Exception:
        return None


def predict_proba_gru(sequence: np.ndarray) -> Optional[np.ndarray]:
    """
    Inférence GRU sur une séquence temporelle.

    Args:
        sequence: Array (seq_len, n_features).

    Returns:
        Probabilités ou None.
    """
    if not is_gru_trained():
        return None
    return None
