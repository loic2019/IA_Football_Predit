"""
core/paths.py — Chemins centralisés du projet
===============================================
Évite la duplication de Path("congobet.db") etc. dans chaque module.
Tous les chemins sont relatifs à la racine du projet (où se trouve predictor.py).
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    """Regroupe tous les chemins persistants du projet."""

    root: Path
    db: Path
    historical_db: Path
    community_db: Path
    model_data: Path
    predictions_history: Path
    automation_state: Path
    ml_weights: Path
    logs: Path
    cache: Path
    exports: Path

    @classmethod
    def from_root(cls, root: Path | None = None) -> "ProjectPaths":
        """
        Construit les chemins à partir de la racine du projet.

        Args:
            root: Racine explicite ; si None, remonte depuis ce fichier.

        Returns:
            Instance ProjectPaths avec tous les chemins résolus.
        """
        base = root or Path(__file__).resolve().parent.parent
        return cls(
            root=base,
            db=base / "congobet.db",
            historical_db=base / "historical_results.db",
            community_db=base / "community.db",
            model_data=base / "model_data.json",
            predictions_history=base / "predictions_history.json",
            automation_state=base / "automation_state.json",
            ml_weights=base / "ml_models" / "weights",
            logs=base / "logs",
            cache=base / "cache",
            exports=base / "data_exports",
        )


_default_paths: ProjectPaths | None = None


def get_paths() -> ProjectPaths:
    """
    Retourne l'instance singleton des chemins projet.

    Returns:
        ProjectPaths configuré pour la racine courante.
    """
    global _default_paths
    if _default_paths is None:
        _default_paths = ProjectPaths.from_root()
    return _default_paths
