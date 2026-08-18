"""feature_engineering — Ingénierie des features (300+ variables)."""

from feature_engineering.registry import ALL_FEATURE_NAMES, FEATURE_COUNT, LEGACY_FEATURE_NAMES
from feature_engineering.builder import build_feature_vector, build_training_matrix, build_legacy_features

__all__ = [
    "ALL_FEATURE_NAMES", "FEATURE_COUNT", "LEGACY_FEATURE_NAMES",
    "build_feature_vector", "build_training_matrix", "build_legacy_features",
]
