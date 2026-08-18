"""
core/config.py — Configuration centralisée de l'IA de pronostics
=================================================================
Paramètres production : seuils, limites cache, flags ensemble, performance.
Modifiable via variables d'environnement pour le déploiement MLOps.
"""

import os
from dataclasses import dataclass, field


@dataclass
class AppConfig:
    """Configuration applicative avec valeurs par défaut production."""

    # Ensemble & modèles
    use_ensemble: bool = True
    min_training_samples: int = 40
    max_goals_poisson: int = 8
    inference_target_ms: float = 100.0

    # Cache & base de données
    db_cache_ttl_seconds: int = 300
    prediction_cache_ttl_seconds: int = 60
    db_wal_mode: bool = True

    # Auto-learning
    auto_learn_enabled: bool = True
    drift_detection_window: int = 100
    min_model_weight: float = 0.02

    # Backtesting
    backtest_default_seasons: int = 3
    monte_carlo_iterations: int = 1000

    # Feature engineering
    extended_features_enabled: bool = True
    legacy_feature_count: int = 12

    # Sécurité & logs
    log_level: str = "INFO"
    validate_inputs: bool = True

    # Modèles activés (graceful degradation si dépendance absente)
    enabled_models: list[str] = field(default_factory=lambda: [
        "poisson", "dixon_coles", "elo", "bayesian",
        "logreg", "rf", "extra_trees", "xgb", "lgbm", "catboost",
        "gbc", "deep",
    ])

    # Enrichissement externe (blessures, arbitres, joueurs, entraîneurs, météo)
    # Clé gratuite sur https://www.api-football.com (100 req/jour sur le tier gratuit)
    api_football_key: str = "a262e9d7d651ca5d42847ae95076c98f"

    @classmethod
    def from_env(cls) -> "AppConfig":
        """
        Charge la configuration depuis les variables d'environnement.

        Returns:
            AppConfig avec overrides ENV appliqués.
        """
        cfg = cls()
        if os.environ.get("CONGOBET_USE_ENSEMBLE", "1") == "0":
            cfg.use_ensemble = False
        if os.environ.get("CONGOBET_EXTENDED_FEATURES", "1") == "0":
            cfg.extended_features_enabled = False
        if os.environ.get("CONGOBET_AUTO_LEARN", "1") == "0":
            cfg.auto_learn_enabled = False
        if lvl := os.environ.get("CONGOBET_LOG_LEVEL"):
            cfg.log_level = lvl.upper()
        if ttl := os.environ.get("CONGOBET_CACHE_TTL"):
            try:
                cfg.db_cache_ttl_seconds = int(ttl)
            except ValueError:
                pass
        if key := os.environ.get("API_FOOTBALL_KEY"):
            cfg.api_football_key = key
        return cfg


_config: AppConfig | None = None


def get_config() -> AppConfig:
    """
    Retourne la configuration singleton (lazy, depuis ENV).

    Returns:
        Instance AppConfig partagée.
    """
    global _config
    if _config is None:
        _config = AppConfig.from_env()
    return _config
