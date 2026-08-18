"""
tests/test_enterprise_architecture.py — Tests unitaires architecture enterprise
=================================================================================
Vérifie compatibilité predictor.py, feature count 300+, ensemble, métriques.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestFeatureEngineering:
    """Tests feature engineering 300+."""

    def test_feature_count_at_least_300(self):
        from feature_engineering.registry import FEATURE_COUNT, ALL_FEATURE_NAMES
        assert FEATURE_COUNT >= 300
        assert len(ALL_FEATURE_NAMES) == FEATURE_COUNT
        assert len(set(ALL_FEATURE_NAMES)) == FEATURE_COUNT

    def test_legacy_features_unchanged_order(self):
        from feature_engineering.registry import LEGACY_FEATURE_NAMES
        from ml_models.feature_engineering import FEATURE_NAMES
        assert LEGACY_FEATURE_NAMES == FEATURE_NAMES

    def test_build_feature_vector_shape(self):
        from feature_engineering.builder import build_feature_vector
        from feature_engineering.registry import FEATURE_COUNT, LEGACY_FEATURE_NAMES
        from predictor import ModelData

        model = ModelData()
        match = {
            "home": "Team A", "away": "Team B", "league": "PL",
            "markets": {"Résultat du match": {"1": 2.0, "X": 3.5, "2": 3.0}},
        }
        legacy = build_feature_vector(match, model, extended=False)
        assert legacy.shape == (len(LEGACY_FEATURE_NAMES),)
        full = build_feature_vector(match, model, extended=True)
        assert full.shape == (FEATURE_COUNT,)


class TestStatisticalModels:
    """Tests modèles Poisson, Dixon-Coles, Bayesian."""

    def test_poisson_probs_sum_to_one(self):
        from models.poisson import poisson_match_probs
        probs = poisson_match_probs(1.5, 1.1)
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_dixon_coles_probs_sum_to_one(self):
        from models.dixon_coles import dixon_coles_probs
        probs = dixon_coles_probs(1.5, 1.1)
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_bayesian_predict(self):
        from models.bayesian import bayesian_match_probs
        probs = bayesian_match_probs({"1": 0.5, "X": 0.25, "2": 0.25}, 0.7, 0.4)
        assert abs(sum(probs.values()) - 1.0) < 0.01


class TestEnsemble:
    """Tests ensemble orchestrator."""

    def test_predict_ensemble_compatible(self):
        from predictor import Predictor, poisson_match_probs, extract_probs_from_odds, estimate_xg_from_odds

        predictor = Predictor()
        match = {
            "id": "test_1", "home": "Arsenal", "away": "Chelsea", "league": "PL",
            "markets": {"Résultat du match": {"1": 2.1, "X": 3.4, "2": 3.2}},
        }
        pred = predictor.predict(match)
        assert pred["prediction"] in ("1", "X", "2")
        assert 0 < pred["confidence"] <= 1
        assert "models_used" in pred
        assert "probabilities" in pred

    def test_ensemble_status(self):
        from ml_models import ensemble as ens
        status = ens.status()
        assert "weights" in status


class TestMonitoring:
    """Tests métriques."""

    def test_accuracy(self):
        from monitoring.metrics import accuracy, brier_score, log_loss
        y = ["1", "X", "2", "1"]
        p = ["1", "2", "2", "1"]
        assert accuracy(y, p) == 0.5
        probs = [{"1": 0.5, "X": 0.25, "2": 0.25}] * 4
        assert brier_score(probs, y) >= 0
        assert log_loss(probs, y) >= 0


class TestPredictorCompatibility:
    """Tests non-régression predictor.py CLI API."""

    def test_model_data_loads(self):
        from predictor import ModelData
        m = ModelData()
        assert "total_predictions" in m.data

    def test_build_coupon(self):
        from predictor import Predictor
        p = Predictor()
        preds = [
            {"confidence": 0.6, "prediction": "1", "cote": 2.0, "home": "A", "away": "B"},
            {"confidence": 0.55, "prediction": "2", "cote": 1.8, "home": "C", "away": "D"},
        ]
        coupon = p.build_coupon(preds, size=2)
        assert coupon["size"] == 2
        assert coupon["total_cote"] > 1
