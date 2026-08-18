"""
ml_models/tree_models.py — XGBoost et LightGBM
====================================================
Pour ~4000 lignes de données tabulaires, les modèles à base d'arbres
(gradient boosting) généralisent en général mieux qu'un deep net — c'est
pour ça qu'ils font partie de l'ensemble, pas juste le réseau de neurones.
"""

import json
from pathlib import Path

import numpy as np

from ml_models.model_cache import get_cached

XGB_PATH = Path("ml_models/weights/xgb_model.json")
LGBM_PATH = Path("ml_models/weights/lgbm_model.txt")
RF_PATH = Path("ml_models/weights/rf_model.joblib")
CATBOOST_PATH = Path("ml_models/weights/catboost_model.cbm")
EXTRA_TREES_PATH = Path("ml_models/weights/extra_trees_model.joblib")


def train_xgb(X: np.ndarray, y: np.ndarray) -> dict:
    import xgboost as xgb
    from sklearn.model_selection import train_test_split

    if len(X) < 40:
        return {"trained": False, "reason": "Pas assez de données (minimum 40 matchs)."}

    XGB_PATH.parent.mkdir(parents=True, exist_ok=True)
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None)

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="multi:softprob",
        num_class=3,
        eval_metric="mlogloss",
        early_stopping_rounds=20,
        random_state=42,
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    model.save_model(str(XGB_PATH))

    train_acc = model.score(X_train, y_train)
    val_acc = model.score(X_val, y_val)
    return {"trained": True, "train_acc": round(train_acc, 4), "val_acc": round(val_acc, 4), "n_samples": len(X)}


def train_lgbm(X: np.ndarray, y: np.ndarray) -> dict:
    import lightgbm as lgb
    from sklearn.model_selection import train_test_split

    if len(X) < 40:
        return {"trained": False, "reason": "Pas assez de données (minimum 40 matchs)."}

    LGBM_PATH.parent.mkdir(parents=True, exist_ok=True)
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None)

    model = lgb.LGBMClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="multiclass",
        num_class=3,
        random_state=42,
        verbosity=-1,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(20, verbose=False)],
    )
    model.booster_.save_model(str(LGBM_PATH))

    train_acc = model.score(X_train, y_train)
    val_acc = model.score(X_val, y_val)
    return {"trained": True, "train_acc": round(train_acc, 4), "val_acc": round(val_acc, 4), "n_samples": len(X)}


def train_catboost(X: np.ndarray, y: np.ndarray) -> dict:
    from catboost import CatBoostClassifier
    from sklearn.model_selection import train_test_split

    if len(X) < 40:
        return {"trained": False, "reason": "Pas assez de données (minimum 40 matchs)."}

    CATBOOST_PATH.parent.mkdir(parents=True, exist_ok=True)
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None)

    model = CatBoostClassifier(
        iterations=300,
        depth=4,
        learning_rate=0.05,
        loss_function="MultiClass",
        random_seed=42,
        verbose=False,
        early_stopping_rounds=20,
    )
    model.fit(X_train, y_train, eval_set=(X_val, y_val), verbose=False)
    model.save_model(str(CATBOOST_PATH))

    train_acc = model.score(X_train, y_train)
    val_acc = model.score(X_val, y_val)
    return {"trained": True, "train_acc": round(train_acc, 4), "val_acc": round(val_acc, 4), "n_samples": len(X)}


def is_catboost_trained() -> bool:
    return CATBOOST_PATH.exists()


def predict_proba_catboost(X: np.ndarray) -> np.ndarray:
    from catboost import CatBoostClassifier

    def _load():
        model = CatBoostClassifier()
        model.load_model(str(CATBOOST_PATH))
        return model

    model = get_cached(CATBOOST_PATH, _load)
    return model.predict_proba(X)


def train_rf(X: np.ndarray, y: np.ndarray) -> dict:
    """
    Random Forest — ajouté sur demande explicite (1 modèle ciblé, pas 6).
    Complémentaire à XGBoost/LightGBM : le bagging (RF, moyenne d'arbres
    indépendants) généralise différemment du boosting (arbres qui se
    corrigent séquentiellement), donc apporte une vraie diversité à
    l'ensemble plutôt qu'un doublon.
    """
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split

    if len(X) < 40:
        return {"trained": False, "reason": "Pas assez de données (minimum 40 matchs)."}

    RF_PATH.parent.mkdir(parents=True, exist_ok=True)
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None
    )

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=6,
        min_samples_leaf=5,
        max_features="sqrt",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    import joblib
    joblib.dump(model, RF_PATH)

    train_acc = model.score(X_train, y_train)
    val_acc = model.score(X_val, y_val)
    return {"trained": True, "train_acc": round(train_acc, 4), "val_acc": round(val_acc, 4), "n_samples": len(X)}


def is_rf_trained() -> bool:
    return RF_PATH.exists()


def predict_proba_rf(X: np.ndarray) -> np.ndarray:
    import joblib

    model = get_cached(RF_PATH, lambda: joblib.load(RF_PATH))
    return model.predict_proba(X)


def train_extra_trees(X: np.ndarray, y: np.ndarray) -> dict:
    """
    Extra Trees (Extremely Randomized Trees) — complémentaire au Random Forest :
    les seuils de coupure sont tirés aléatoirement (pas optimisés par split),
    ce qui réduit la variance et apporte une diversité supplémentaire à
    l'ensemble plutôt qu'un simple doublon du RF.
    """
    from sklearn.ensemble import ExtraTreesClassifier
    from sklearn.model_selection import train_test_split

    if len(X) < 40:
        return {"trained": False, "reason": "Pas assez de données (minimum 40 matchs)."}

    EXTRA_TREES_PATH.parent.mkdir(parents=True, exist_ok=True)
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None
    )

    model = ExtraTreesClassifier(
        n_estimators=300,
        max_depth=6,
        min_samples_leaf=5,
        max_features="sqrt",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    import joblib
    joblib.dump(model, EXTRA_TREES_PATH)

    train_acc = model.score(X_train, y_train)
    val_acc = model.score(X_val, y_val)
    return {"trained": True, "train_acc": round(train_acc, 4), "val_acc": round(val_acc, 4), "n_samples": len(X)}


def is_extra_trees_trained() -> bool:
    return EXTRA_TREES_PATH.exists()


def predict_proba_extra_trees(X: np.ndarray) -> np.ndarray:
    import joblib

    model = get_cached(EXTRA_TREES_PATH, lambda: joblib.load(EXTRA_TREES_PATH))
    return model.predict_proba(X)


def is_xgb_trained() -> bool:
    return XGB_PATH.exists()


def is_lgbm_trained() -> bool:
    return LGBM_PATH.exists()


def predict_proba_xgb(X: np.ndarray) -> np.ndarray:
    import xgboost as xgb

    def _load():
        model = xgb.XGBClassifier()
        model.load_model(str(XGB_PATH))
        return model

    model = get_cached(XGB_PATH, _load)
    return model.predict_proba(X)


def predict_proba_lgbm(X: np.ndarray) -> np.ndarray:
    import lightgbm as lgb

    booster = get_cached(LGBM_PATH, lambda: lgb.Booster(model_file=str(LGBM_PATH)))
    raw = booster.predict(X)
    return np.array(raw)
