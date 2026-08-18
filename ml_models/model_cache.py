"""
ml_models/model_cache.py — Cache mémoire pour les poids des modèles
======================================================================
Problème résolu : chaque predict_proba_* rechargeait son modèle depuis le
disque (joblib.load / xgb.load_model / torch.load / lecture JSON) à CHAQUE
appel — soit une fois par match analysé. Avec l'orchestrateur combinant
maintenant Elo + Dixon-Coles + jusqu'à 8 modèles ML, analyser plusieurs
centaines de matchs déclenchait des milliers de rechargements disque et
finissait par dépasser le timeout (ex. bouton "Analyser avec predictor").

Ce module fournit un cache process-local, invalidé automatiquement si le
fichier de poids change sur disque (mtime), donc un ré-entraînement est
toujours pris en compte sans redémarrer l'application.
"""

from pathlib import Path
from typing import Any, Callable

_CACHE: dict[str, tuple[float, Any]] = {}


def get_cached(path: Path, loader: Callable[[], Any]) -> Any:
    """
    Renvoie l'objet mis en cache pour `path`, en le (re)chargeant via
    `loader()` uniquement si absent du cache ou si le fichier a changé
    depuis le dernier chargement (mtime différent — donc un ré-entraînement
    est automatiquement détecté).
    """
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        # Fichier absent : pas de cache possible, on laisse l'appelant gérer
        # l'erreur (comportement inchangé par rapport à avant ce module).
        return loader()

    cached = _CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    obj = loader()
    _CACHE[key] = (mtime, obj)
    return obj


def clear_cache() -> None:
    """Vide le cache (utile en tests, ou après un ré-entraînement forcé)."""
    _CACHE.clear()
