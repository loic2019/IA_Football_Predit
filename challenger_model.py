# -*- coding: utf-8 -*-
"""
challenger_model.py — Challenger interne : le réseau de neurones EN ISOLÉ
================================================================================
Remplace l'ancien challenger externe (Bettensor/podos_soccer_model, Hugging
Face) par le réseau de neurones déjà présent dans predictor.py (13→64→32→3,
~3075 poids), utilisé ici SEUL — sans le mélange à 30% qu'il a normalement
dans "Mon modèle" (voir predictor.NN_BLEND_WEIGHT). L'intérêt : voir si le
réseau, livré à lui-même, fait mieux ou moins bien que l'ensemble complet
(Poisson + cotes + forme + XGBoost/LightGBM/CatBoost/Elo + 30% de réseau).

Pourquoi ce remplacement :
- Le modèle Hugging Face ne reconnaissait que 569 équipes précises (grandes
  ligues européennes) — la quasi-totalité des matchs Congobet (compétitions
  africaines/mineures) tombait sur "équipe inconnue", rendant la comparaison
  inutilisable en pratique.
- Le réseau interne, lui, n'a AUCUN vocabulaire figé : il raisonne sur des
  features numériques (cotes, xG, forme, force de ligue) valables pour
  n'importe quel match, quelle que soit la compétition.
- Zéro dépendance supplémentaire (pas de torch/huggingface_hub/safetensors
  ni de téléchargement réseau au démarrage — la source du bug "I/O operation
  on closed file" observé précédemment).

predictor.Predictor.predict() calcule déjà `nn_features` pour CHAQUE match
(que le réseau soit entraîné ou non) — ce module se contente de réutiliser
ces features déjà calculées pour interroger le réseau isolément, sans rien
recalculer.
"""

_neural_net = None
_load_error = None


def _ensure_loaded():
    global _neural_net, _load_error
    if _neural_net is not None or _load_error is not None:
        return
    try:
        from predictor import NeuralNet, NN_WEIGHTS_PATH

        nn = NeuralNet.load(NN_WEIGHTS_PATH)
        if nn is None or nn.trained_epochs == 0:
            _load_error = (
                "Le réseau de neurones interne n'est pas encore entraîné. "
                "Lance : python predictor.py --train-nn 30"
            )
            return
        _neural_net = nn
    except Exception as e:
        _load_error = str(e)


def is_available() -> bool:
    _ensure_loaded()
    return _neural_net is not None


def get_load_error() -> str | None:
    _ensure_loaded()
    return _load_error


def get_model_details() -> dict:
    _ensure_loaded()
    from predictor import NN_INPUT_SIZE, NN_HIDDEN1, NN_HIDDEN2, NN_BLEND_WEIGHT

    if _neural_net is not None:
        epochs = _neural_net.trained_epochs
        samples = _neural_net.trained_samples
        accuracy = _neural_net.last_accuracy
        weights = _neural_net.total_weights()
    else:
        epochs = samples = weights = 0
        accuracy = None

    limitations = [
        "Volume d'entraînement modeste comparé aux standards ML (quelques "
        "milliers de matchs) — un vrai risque de sur-apprentissage à surveiller.",
        "Contribue déjà à 30% du blend de 'Mon modèle' (predictor.NN_BLEND_WEIGHT) "
        "— cette page compare s'il vaut mieux seul ou dilué dans l'ensemble complet.",
    ]
    if accuracy is not None:
        limitations.insert(
            0,
            f"Accuracy interne ({accuracy:.1%}) mesurée sur les données d'entraînement "
            "elles-mêmes, pas sur des matchs jamais vus — à prendre avec prudence.",
        )

    return {
        "name": "Réseau de neurones interne",
        "source": "predictor.py — entraîné directement sur tes données (aucune dépendance externe)",
        "architecture": f"Feedforward {NN_INPUT_SIZE} → {NN_HIDDEN1} → {NN_HIDDEN2} → 3 (~{weights:,} poids)".replace(",", " "),
        "training_data": f"{samples:,} matchs réels (Congobet + historique), {epochs} époque(s) cumulée(s)".replace(",", " "),
        "inputs": "cotes de marché, probabilités Poisson, xG dérivé, forme d'équipe, force de la ligue, statut live (13 features)",
        "limitations": limitations,
    }


def predict_from_nn_features(nn_features: list | None) -> dict | None:
    """
    Interroge le réseau de neurones SEUL (sans le blend à 30%), à partir des
    nn_features déjà calculées par predictor.Predictor.predict() pour ce
    match — aucun recalcul, aucune dépendance à une source externe.

    Retourne {"prediction": "1"|"X"|"2", "confidence": float, "probs": {...},
    "engine": "internal_nn"} ou None si le réseau n'est pas entraîné, ou si
    aucune feature n'a pu être calculée pour ce match (cas très rare — voir
    predictor.build_nn_features, qui a toujours une valeur de repli pour
    chaque champ).
    """
    _ensure_loaded()
    if _neural_net is None or not nn_features:
        return None

    probs_raw = _neural_net.predict_proba(nn_features)
    probs = {"1": probs_raw[0], "X": probs_raw[1], "2": probs_raw[2]}
    best = max(probs, key=probs.get)
    return {
        "prediction": best,
        "confidence": round(probs[best], 4),
        "probs": {k: round(v, 4) for k, v in probs.items()},
        "engine": "internal_nn",
    }
