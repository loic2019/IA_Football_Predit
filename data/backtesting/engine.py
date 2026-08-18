"""
backtesting/engine.py — Moteur de backtesting enterprise
==========================================================
Walk-forward validation, simulation multi-saisons, Monte Carlo.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable

from monitoring.metrics import accuracy, brier_score, log_loss, roi, yield_metric
from security.logger import get_logger

log = get_logger("congobet.backtest")


@dataclass
class BacktestResult:
    """Résultat agrégé d'un backtest."""

    n_matches: int = 0
    accuracy: float = 0.0
    brier: float = 0.0
    logloss: float = 0.0
    roi_simulated: float = 0.0
    yield_pct: float = 0.0
    by_league: dict = field(default_factory=dict)
    walk_forward_scores: list = field(default_factory=list)
    monte_carlo: dict = field(default_factory=dict)


def walk_forward_validation(
    matches: list[dict],
    predict_fn: Callable[[dict], dict],
    train_fn: Callable[[list[dict]], None] | None = None,
    min_train: int = 100,
    step: int = 50,
) -> list[dict]:
    """
    Validation chronologique walk-forward.

    Args:
        matches: Matchs triés chronologiquement.
        predict_fn: Fonction match → prédiction.
        train_fn: Réentraînement optionnel à chaque step.
        min_train: Matchs minimum avant première prédiction.
        step: Taille du pas glissant.

    Returns:
        Liste de scores par fenêtre {window, accuracy, n}.
    """
    def sort_key(m):
        return m.get("start_time") or m.get("utc_date") or ""

    ordered = sorted(matches, key=sort_key)
    from predictor import normalize_result

    scores = []
    for start in range(min_train, len(ordered), step):
        train_set = ordered[:start]
        test_set = ordered[start:start + step]
        if train_fn:
            try:
                train_fn(train_set)
            except Exception as e:
                log.debug("Walk-forward train skip: %s", e)

        y_true, y_pred, probs = [], [], []
        for m in test_set:
            actual = normalize_result(m.get("result"))
            if not actual:
                continue
            pred = predict_fn(m)
            y_true.append(actual)
            y_pred.append(pred.get("prediction", "?"))
            probs.append(pred.get("probabilities", {"1": 0.33, "X": 0.34, "2": 0.33}))

        if y_true:
            scores.append({
                "window": start,
                "accuracy": accuracy(y_true, y_pred),
                "brier": brier_score(probs, y_true),
                "n": len(y_true),
            })

    return scores


def monte_carlo_simulation(
    history: list[dict],
    n_iterations: int = 1000,
    stake: float = 10.0,
    seed: int = 42,
) -> dict:
    """
    Simulation Monte Carlo du bankroll sur l'historique.

    Args:
        history: Prédictions avec correct, cote, confidence.
        n_iterations: Nombre de simulations.
        stake: Mise unitaire.
        seed: Graine aléatoire.

    Returns:
        Dict avec percentiles profit, ruine, etc.
    """
    rng = random.Random(seed)
    profits = []

    for _ in range(n_iterations):
        shuffled = history[:]
        rng.shuffle(shuffled)
        bankroll = 1000.0
        for h in shuffled:
            if bankroll <= 0:
                break
            bet = min(stake, bankroll)
            if h.get("correct"):
                cote = float(h.get("cote") or 2.0)
                bankroll += bet * (cote - 1)
            else:
                bankroll -= bet
        profits.append(bankroll - 1000.0)

    profits.sort()
    n = len(profits)
    return {
        "iterations": n_iterations,
        "median_profit": profits[n // 2],
        "p5_profit": profits[int(n * 0.05)],
        "p95_profit": profits[int(n * 0.95)],
        "prob_ruin": sum(1 for p in profits if p <= -900) / n,
        "mean_profit": sum(profits) / n,
    }


def run_backtest(
    matches: list[dict],
    predictor,
    stake: float = 10.0,
) -> BacktestResult:
    """
    Backtest complet sur une liste de matchs terminés.

    Args:
        matches: Matchs avec résultats connus.
        predictor: Instance Predictor.
        stake: Mise simulée par pari.

    Returns:
        BacktestResult agrégé.
    """
    from predictor import normalize_result

    y_true, y_pred, probs = [], [], []
    stakes_list, returns_list = [], []
    by_league: dict[str, list] = {}

    for m in matches:
        actual = normalize_result(m.get("result"))
        if not actual:
            continue
        tm = dict(m)
        tm["home_score"] = None
        tm["away_score"] = None
        pred = predictor.predict(tm)
        y_true.append(actual)
        y_pred.append(pred["prediction"])
        probs.append(pred.get("probabilities", {}))

        league = m.get("league", "unknown")
        by_league.setdefault(league, {"correct": 0, "total": 0})
        by_league[league]["total"] += 1
        if pred["prediction"] == actual:
            by_league[league]["correct"] += 1

        cote = float(pred.get("cote") or 0)
        if cote > 1.0 and pred.get("confidence", 0) >= 0.5:
            stakes_list.append(stake)
            returns_list.append(stake * cote if pred["prediction"] == actual else 0.0)

    result = BacktestResult(n_matches=len(y_true))
    if not y_true:
        return result

    result.accuracy = accuracy(y_true, y_pred)
    result.brier = brier_score(probs, y_true)
    result.logloss = log_loss(probs, y_true)
    result.roi_simulated = roi(stakes_list, returns_list)
    result.yield_pct = yield_metric(sum(returns_list) - sum(stakes_list), sum(stakes_list))
    result.by_league = {
        k: v["correct"] / v["total"] for k, v in by_league.items() if v["total"] >= 3
    }
    return result
