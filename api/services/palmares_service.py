"""
Couche service pour le palmarès public (tickets vérifiés gagnés/perdus).

Logique reprise à l'identique de `palmares.py::render()` (série actuelle,
évolution cumulée, filtre gagnés/perdus) — seul le rendu Streamlit/HTML
est retiré.
"""
from common import get_model_stats


def _current_streak(recent_sorted: list[dict]) -> dict | None:
    streak_type = None
    current_streak = 0
    for e in recent_sorted:
        is_win = bool(e.get("correct"))
        if streak_type is None:
            streak_type = is_win
            current_streak = 1
        elif is_win == streak_type:
            current_streak += 1
        else:
            break
    if streak_type is None:
        return None
    return {"count": current_streak, "type": "win" if streak_type else "loss"}


def _evolution(history_sorted_by_date: list[dict]) -> list[dict]:
    cumulative_correct = 0
    points = []
    for i, entry in enumerate(history_sorted_by_date, start=1):
        if entry.get("correct"):
            cumulative_correct += 1
        points.append({"n": i, "cumulative_accuracy": round(cumulative_correct / i * 100, 1)})
    return points


def get_palmares(filter_choice: str = "all", limit: int = 30) -> dict:
    """filter_choice: 'all' | 'won' | 'lost'"""
    stats = get_model_stats()
    history = (stats or {}).get("history", [])
    if not history:
        return {"available": False}

    total = len(history)
    won = sum(1 for e in history if e.get("correct"))

    recent = sorted(history, key=lambda e: e.get("trained_at", ""), reverse=True)
    streak = _current_streak(recent)

    if filter_choice == "won":
        filtered = [e for e in recent if e.get("correct")]
    elif filter_choice == "lost":
        filtered = [e for e in recent if not e.get("correct")]
    else:
        filtered = recent

    sorted_asc = sorted(history, key=lambda e: e.get("trained_at", ""))

    return {
        "available": True,
        "total": total,
        "won": won,
        "win_rate": (won / total * 100) if total else 0,
        "streak": streak,
        "evolution": _evolution(sorted_asc) if len(sorted_asc) >= 2 else [],
        "tickets": filtered[:limit],
        "remaining": max(0, len(filtered) - limit),
    }
