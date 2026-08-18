"""
historical_data.py — Lecture de historical_results.db pour enrichir l'entraînement
======================================================================================
Base et table totalement séparées de congobet.db : aucune collision de schéma possible.
Importé par common.py (voir instructions d'intégration).
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

HISTORICAL_DB_PATH = Path("historical_results.db")
HISTORICAL_TABLE = "results_history"


def _normalize_result(result: str) -> str:
    mapping = {"H": "1", "D": "X", "A": "2", "1": "1", "X": "X", "2": "2"}
    return mapping.get(str(result or "").upper(), "")


def get_historical_training_matches(limit: int = 2000, max_age_days: int = 365) -> list[dict]:
    """
    Renvoie une liste de matchs terminés issus de historical_results.db,
    normalisée dans le même format que common.get_training_matches(), pour
    pouvoir être passée telle quelle à Predictor.train_from_results().

    Ces matchs n'ont pas de cotes réelles (markets={}), donc le prédicteur
    se rabat sur ses probabilités par défaut (33/34/33) + la forme des équipes
    pour ces lignes-là : c'est un signal d'entraînement complémentaire, pas
    un substitut aux vrais matchs CongoBet/1xBet avec cotes (voir
    common.get_training_matches(), qui inclut maintenant aussi les matchs
    récents réels via coupon_tracker.get_recent_matches_with_results()).

    max_age_days limite l'ancienneté (365j par défaut) : sans ça, des
    matchs vieux de 2 ans pesaient exactement autant que des matchs de la
    semaine dans l'entraînement (aucune pondération par récence n'existe),
    ce qui diluait la capacité du modèle à refléter la forme ACTUELLE des
    équipes (rosters/forme qui changent d'une saison à l'autre).
    """
    if not HISTORICAL_DB_PATH.exists():
        return []

    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{HISTORICAL_TABLE}'")
        if not cur.fetchone():
            return []

        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        rows = conn.execute(f"""
            SELECT match_id as id, home_team_name as home, away_team_name as away,
                   competition_id as league, home_score, away_score, result, utc_date as start_time
            FROM {HISTORICAL_TABLE}
            WHERE home_score IS NOT NULL AND away_score IS NOT NULL
              AND utc_date >= ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (cutoff, int(limit))).fetchall()
    except Exception:
        return []
    finally:
        conn.close()

    prepared = []
    for row in rows:
        d = dict(row)
        normalized = _normalize_result(d.get("result"))
        if not normalized:
            continue
        d["result"] = normalized
        d["markets"] = {}
        d["id"] = f"hist_{d['id']}"  # préfixe pour ne jamais collisionner avec les ids CongoBet/1xBet
        prepared.append(d)

    return prepared
