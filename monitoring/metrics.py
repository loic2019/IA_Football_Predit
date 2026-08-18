"""
monitoring/metrics.py — Métriques ML production (Accuracy, ROI, Brier, etc.)
==============================================================================
Calculs utilisés par le dashboard, backtesting et auto-learning.
"""

import math
from typing import Sequence


def accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    """
    Précision classification 1/X/2.

    Args:
        y_true: Résultats réels.
        y_pred: Prédictions.

    Returns:
        Accuracy [0, 1].
    """
    if not y_true:
        return 0.0
    return sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)


def brier_score(probs: list[dict], y_true: Sequence[str]) -> float:
    """
    Brier Score multiclass (1/X/2) — plus bas = mieux calibré.

    Args:
        probs: Liste de dicts {"1","X","2"} probabilités.
        y_true: Labels réels.

    Returns:
        Brier score moyen.
    """
    labels = ("1", "X", "2")
    total = 0.0
    for prob, actual in zip(probs, y_true):
        for lbl in labels:
            o = 1.0 if actual == lbl else 0.0
            p = prob.get(lbl, 0.33)
            total += (p - o) ** 2
    return total / max(len(y_true) * 3, 1)


def log_loss(probs: list[dict], y_true: Sequence[str], eps: float = 1e-15) -> float:
    """
    Log Loss multiclass.

    Args:
        probs: Probabilités prédites.
        y_true: Labels réels.
        eps: Stabilisation numérique.

    Returns:
        Log loss moyen.
    """
    total = 0.0
    for prob, actual in zip(probs, y_true):
        p = max(prob.get(actual, eps), eps)
        total -= math.log(p)
    return total / max(len(y_true), 1)


def expected_value(prob: float, odds: float) -> float:
    """
    Expected Value d'un pari : EV = prob * cote - 1.

    Args:
        prob: Probabilité estimée [0,1].
        odds: Cote décimale.

    Returns:
        EV (positif = value bet).
    """
    if odds <= 1.0:
        return -1.0
    return prob * odds - 1.0


def roi(stakes: Sequence[float], returns: Sequence[float]) -> float:
    """
    Return On Investment historique.

    Args:
        stakes: Mises.
        returns: Gains.

    Returns:
        ROI (ex: 0.05 = +5%).
    """
    total_stake = sum(stakes)
    if total_stake <= 0:
        return 0.0
    return (sum(returns) - total_stake) / total_stake


def yield_metric(profit: float, total_stake: float) -> float:
    """
    Yield = profit / total_stake (standard paris sportifs).

    Args:
        profit: Profit net.
        total_stake: Mises totales.

    Returns:
        Yield.
    """
    if total_stake <= 0:
        return 0.0
    return profit / total_stake


def calibration_buckets(history: list[dict], n_buckets: int = 5) -> list[dict]:
    """
    Courbe de calibration par tranches de confiance.

    Args:
        history: Historique prédictions avec confidence et correct.
        n_buckets: Nombre de tranches.

    Returns:
        Liste {bucket, predicted, actual, count}.
    """
    buckets = [{"pred_sum": 0.0, "actual_sum": 0.0, "count": 0} for _ in range(n_buckets)]
    for h in history:
        conf = h.get("confidence", 0.5)
        idx = min(n_buckets - 1, int(conf * n_buckets))
        buckets[idx]["pred_sum"] += conf
        buckets[idx]["actual_sum"] += 1.0 if h.get("correct") else 0.0
        buckets[idx]["count"] += 1

    result = []
    for i, b in enumerate(buckets):
        if b["count"] == 0:
            continue
        result.append({
            "bucket": f"{i / n_buckets:.0%}-{(i + 1) / n_buckets:.0%}",
            "predicted": b["pred_sum"] / b["count"],
            "actual": b["actual_sum"] / b["count"],
            "count": b["count"],
        })
    return result


def confusion_matrix(y_true: Sequence[str], y_pred: Sequence[str], labels=("1", "X", "2")) -> dict:
    """
    Matrice de confusion pour la classification 1/X/2.

    Returns:
        {"labels": [...], "matrix": [[...]]} — matrix[i][j] = nb de fois où
        la classe réelle labels[i] a été prédite comme labels[j].
    """
    idx = {lbl: i for i, lbl in enumerate(labels)}
    matrix = [[0 for _ in labels] for _ in labels]
    for t, p in zip(y_true, y_pred):
        if t in idx and p in idx:
            matrix[idx[t]][idx[p]] += 1
    return {"labels": list(labels), "matrix": matrix}


def precision_recall_f1(y_true: Sequence[str], y_pred: Sequence[str], labels=("1", "X", "2")) -> dict:
    """
    Precision / Recall / F1 par classe + moyenne macro (moyenne simple entre
    classes, adaptée ici car aucune classe n'est structurellement rare comme
    dans un problème de fraude par exemple).
    """
    per_class = {}
    for lbl in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == lbl and p == lbl)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != lbl and p == lbl)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == lbl and p != lbl)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_class[lbl] = {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}

    macro_precision = sum(v["precision"] for v in per_class.values()) / len(labels)
    macro_recall = sum(v["recall"] for v in per_class.values()) / len(labels)
    macro_f1 = sum(v["f1"] for v in per_class.values()) / len(labels)
    return {
        "per_class": per_class,
        "macro_precision": round(macro_precision, 4),
        "macro_recall": round(macro_recall, 4),
        "macro_f1": round(macro_f1, 4),
    }


def roc_curve_points(probs: list[dict], y_true: Sequence[str], label: str, n_thresholds: int = 30) -> dict:
    """
    Courbe ROC en "un contre tous" (one-vs-rest) pour UNE classe (ex: label="1").
    Un problème 1/X/2 n'a pas de ROC unique — on en calcule une par classe,
    l'appelant choisit laquelle afficher (ou les 3).

    Returns:
        {"fpr": [...], "tpr": [...], "auc": float, "label": label}
    """
    y_bin = [1 if t == label else 0 for t in y_true]
    scores = [p.get(label, 0.0) for p in probs]
    n_pos = sum(y_bin)
    n_neg = len(y_bin) - n_pos
    if n_pos == 0 or n_neg == 0:
        return {"fpr": [], "tpr": [], "auc": None, "label": label}

    thresholds = [i / n_thresholds for i in range(n_thresholds + 1)]
    fpr_list, tpr_list = [], []
    for thr in thresholds:
        tp = sum(1 for s, y in zip(scores, y_bin) if s >= thr and y == 1)
        fp = sum(1 for s, y in zip(scores, y_bin) if s >= thr and y == 0)
        tpr_list.append(tp / n_pos)
        fpr_list.append(fp / n_neg)

    # AUC par intégration trapézoïdale (points triés par fpr croissant)
    pts = sorted(zip(fpr_list, tpr_list))
    auc = 0.0
    for i in range(1, len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        auc += (x1 - x0) * (y0 + y1) / 2

    return {"fpr": fpr_list, "tpr": tpr_list, "auc": round(auc, 4), "label": label}


def bankroll_curve(history: list[dict], stake: float = 10.0, start_bankroll: float = 1000.0) -> list[dict]:
    """
    Courbe d'évolution du capital/bankroll match après match (mise fixe),
    dans l'ordre chronologique de `history` (déjà chronologique dans
    model_data.json — les entrées sont ajoutées au fil de l'eau).

    Returns:
        Liste de points {index, date, bankroll, profit_cumule}.
    """
    bankroll = start_bankroll
    points = []
    for i, h in enumerate(history):
        cote = float(h.get("cote") or 0)
        if h.get("correct") and cote > 1.0:
            bankroll += stake * (cote - 1)
        elif cote > 0:
            bankroll -= stake
        else:
            continue  # pas de cote connue = pas de pari simulable
        points.append({
            "index": i,
            "date": h.get("trained_at", ""),
            "bankroll": round(bankroll, 2),
            "profit_cumule": round(bankroll - start_bankroll, 2),
        })
    return points


def _reconstruct_probs(history: list[dict]) -> list[dict]:
    """
    Renvoie les probabilités [1,X,2] par entrée d'historique. Utilise les
    vraies probabilités stockées si disponibles (voir predictor.py::
    record_training_match) ; pour les entrées plus anciennes qui n'en ont
    pas, reconstruit une approximation à partir de la seule confidence
    stockée (attribuée à la classe prédite, reste réparti également) —
    de vraie distribution, mais évite le pire (probs
    uniformes 0.33/0.33/0.33 qui annulaient tout signal de calibration).
    """
    labels = ("1", "X", "2")
    result = []
    for h in history:
        real_probs = h.get("probabilities")
        if real_probs:
            result.append(real_probs)
            continue
        conf = h.get("confidence", 0.4)
        pred = h.get("prediction", "1")
        remaining = (1 - conf) / 2
        result.append({lbl: (conf if lbl == pred else remaining) for lbl in labels})
    return result


def compute_dashboard_metrics(model_data: dict) -> dict:
    """
    Agrège toutes les métriques pour le dashboard enterprise.

    Args:
        model_data: Contenu de model_data.json.

    Returns:
        Dict métriques prêtes pour affichage.
    """
    history = model_data.get("history", [])
    total = model_data.get("total_predictions", len(history))
    correct = model_data.get("correct_predictions", sum(1 for h in history if h.get("correct")))

    y_true = [h.get("actual", "") for h in history if h.get("actual")]
    y_pred = [h.get("prediction", "") for h in history if h.get("actual")]
    probs = _reconstruct_probs([h for h in history if h.get("actual")])

    prf = precision_recall_f1(y_true, y_pred) if y_true else {}
    cm = confusion_matrix(y_true, y_pred) if y_true else {}
    roc = {lbl: roc_curve_points(probs, y_true, lbl) for lbl in ("1", "X", "2")} if y_true else {}

    stakes = [10.0 for h in history if h.get("cote")]
    returns = [10.0 * float(h["cote"]) if h.get("correct") else 0.0 for h in history if h.get("cote")]

    return {
        "accuracy": correct / max(total, 1),
        "total_predictions": total,
        "correct_predictions": correct,
        "brier_score": brier_score(probs, y_true) if y_true else None,
        "log_loss": log_loss(probs, y_true) if y_true else None,
        "precision_recall_f1": prf,
        "confusion_matrix": cm,
        "roc": roc,
        "roi": roi(stakes, returns) if stakes else 0.0,
        "yield": yield_metric(sum(returns) - sum(stakes), sum(stakes)) if stakes else 0.0,
        "bankroll_curve": bankroll_curve(history),
        "calibration": calibration_buckets(history),
        "league_accuracy": model_data.get("league_accuracy", {}),
    }
