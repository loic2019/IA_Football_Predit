"""
ml_models/classic_models.py — Logistic Regression, Random Forest, Gradient Boosting
========================================================================================
Modèles scikit-learn classiques, rapides à entraîner et raisonnables pour un
volume de données modeste. Ajoutent de la diversité à l'ensemble (une
régression logistique généralise différemment d'un arbre de boosting), ce
qui aide la moyenne pondérée à être plus robuste qu'un seul type de modèle.
"""

import joblib
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

from ml_models.model_cache import get_cached

WEIGHTS_DIR = Path("ml_models/weights")
LOGREG_PATH = WEIGHTS_DIR / "logreg_model.joblib"
RF_PATH = WEIGHTS_DIR / "rf_model.joblib"
GBC_PATH = WEIGHTS_DIR / "gbc_model.joblib"


def _split(X, y):
    return train_test_split(X, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None)


def train_logreg(X: np.ndarray, y: np.ndarray) -> dict:
    if len(X) < 40:
        return {"trained": False, "reason": "Pas assez de données (minimum 40 matchs)."}

    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    X_train, X_val, y_train, y_val = _split(X, y)

    scaler = StandardScaler().fit(X_train)
    model = LogisticRegression(max_iter=1000, C=1.0, multi_class="multinomial")
    model.fit(scaler.transform(X_train), y_train)

    joblib.dump({"model": model, "scaler": scaler}, LOGREG_PATH)
    return {
        "trained": True,
        "train_acc": round(model.score(scaler.transform(X_train), y_train), 4),
        "val_acc": round(model.score(scaler.transform(X_val), y_val), 4),
        "n_samples": len(X),
    }


def train_rf(X: np.ndarray, y: np.ndarray) -> dict:
    if len(X) < 40:
        return {"trained": False, "reason": "Pas assez de données (minimum 40 matchs)."}

    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    X_train, X_val, y_train, y_val = _split(X, y)

    model = RandomForestClassifier(
        n_estimators=200, max_depth=6, min_samples_leaf=5, random_state=42, n_jobs=-1
    )
    model.fit(X_train, y_train)

    joblib.dump(model, RF_PATH)
    return {
        "trained": True,
        "train_acc": round(model.score(X_train, y_train), 4),
        "val_acc": round(model.score(X_val, y_val), 4),
        "n_samples": len(X),
    }


def train_gbc(X: np.ndarray, y: np.ndarray) -> dict:
    if len(X) < 40:
        return {"trained": False, "reason": "Pas assez de données (minimum 40 matchs)."}

    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    X_train, X_val, y_train, y_val = _split(X, y)

    model = GradientBoostingClassifier(
        n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=42
    )
    model.fit(X_train, y_train)

    joblib.dump(model, GBC_PATH)
    return {
        "trained": True,
        "train_acc": round(model.score(X_train, y_train), 4),
        "val_acc": round(model.score(X_val, y_val), 4),
        "n_samples": len(X),
    }


def is_logreg_trained() -> bool:
    return LOGREG_PATH.exists()


def is_rf_trained() -> bool:
    return RF_PATH.exists()


def is_gbc_trained() -> bool:
    return GBC_PATH.exists()


def predict_proba_logreg(X: np.ndarray) -> np.ndarray:
    saved = get_cached(LOGREG_PATH, lambda: joblib.load(LOGREG_PATH))
    return saved["model"].predict_proba(saved["scaler"].transform(X))


def predict_proba_rf(X: np.ndarray) -> np.ndarray:
    model = get_cached(RF_PATH, lambda: joblib.load(RF_PATH))
    return model.predict_proba(X)


def predict_proba_gbc(X: np.ndarray) -> np.ndarray:
    model = get_cached(GBC_PATH, lambda: joblib.load(GBC_PATH))
    return model.predict_proba(X)
