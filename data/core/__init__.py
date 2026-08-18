"""
core — Noyau de l'architecture enterprise CongoBet AI
======================================================
Point d'entrée central pour la configuration et les chemins du projet.
Conserve la compatibilité avec les imports existants (predictor.py, ml_models/).
"""

from core.config import AppConfig, get_config
from core.paths import ProjectPaths, get_paths

__all__ = ["AppConfig", "get_config", "ProjectPaths", "get_paths"]
