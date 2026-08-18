# -*- coding: utf-8 -*-
"""
historical_data_refill.py — Alimente ACTIVEMENT historical_results.db
================================================================================
Avant ce module, historical_results.db n'était rempli qu'UNE FOIS (via
migrate_fix_congobet_db.py, une récupération de données polluées). Ce module
va chercher de VRAIES nouvelles données sur football-data.org (API gratuite,
sans jamais toucher congobet.db — donc aucun risque de reproduire le bug des
tickets fictifs corrigé précédemment) et les ajoute à historical_results.db.

PLAFOND ROTATIF : au-delà de MAX_ROWS (10 000 par défaut), les matchs les
plus ANCIENS sont automatiquement supprimés pour laisser la place aux plus
récents — le jeu de calibration reste donc représentatif de la forme
ACTUELLE des équipes plutôt que de s'alourdir indéfiniment de vieilles
saisons.

Intégré automatiquement dans common.run_auto_cycle (throttlé à 1x/24h pour
respecter la limite gratuite de l'API et ne pas la solliciter inutilement
alors que les résultats de championnat ne bougent pas toutes les 10 minutes).
"""

import os
import time
import sqlite3
import requests
from datetime import datetime
from pathlib import Path

from security.logger import get_logger

log = get_logger("congobet.historical_refill")

HISTORICAL_DB_PATH = Path("historical_results.db")
HISTORICAL_TABLE = "results_history"
MAX_ROWS = 10_000

# Clé football-data.org — configurable via la variable d'environnement
# FOOTBALL_DATA_API_KEY (utile en ligne, où mettre une clé en dur dans le code
# n'est pas souhaitable). En local, garde la même clé par défaut qu'avant.
API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "fe50fdb0b9074d04b5533deaafbfe099")
API_BASE = "https://api.football-data.org/v4"

# Compétitions couvertes par le plan gratuit football-data.org
COMPETITIONS = ["PL", "PD", "BL1", "SA", "FL1", "CL"]


def _ensure_tables(conn):
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {HISTORICAL_TABLE} (
            match_id INTEGER PRIMARY KEY,
            competition_id TEXT,
            home_team_id INTEGER,
            away_team_id INTEGER,
            home_team_name TEXT,
            away_team_name TEXT,
            home_score INTEGER,
            away_score INTEGER,
            result TEXT,
            status TEXT,
            utc_date TEXT,
            timestamp INTEGER,
            season_id INTEGER,
            matchday INTEGER,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE TABLE IF NOT EXISTS import_meta (key TEXT PRIMARY KEY, value TEXT)")


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _result_letter(home_score, away_score) -> str:
    if home_score is None or away_score is None:
        return ""
    if home_score > away_score:
        return "H"
    if home_score < away_score:
        return "A"
    return "D"


def _fetch_competition_matches(competition_id: str) -> tuple[list[dict], str | None]:
    """Un seul appel récupère TOUTE la saison en cours (pas besoin de boucler
    journée par journée comme le faisait l'ancien results_importer.py — ça
    économise énormément d'appels API).

    Retourne (matchs, erreur) — erreur=None si tout s'est bien passé. Avant
    ce correctif, toute erreur (clé API invalide, quota dépassé, réseau
    bloqué...) était avalée en silence (`except: return []`), rendant
    impossible de diagnostiquer pourquoi historical_results.db restait vide
    — symptôme observé : Historique ET réseau de neurones vides tous les
    deux, sans le moindre message d'erreur nulle part.
    """
    try:
        resp = requests.get(
            f"{API_BASE}/competitions/{competition_id}/matches",
            headers={"X-Auth-Token": API_KEY},
            params={"status": "FINISHED"},
            timeout=20,
        )
        if resp.status_code != 200:
            error = f"HTTP {resp.status_code} sur {competition_id} : {resp.text[:200]}"
            log.warning(error)
            return [], error
        return resp.json().get("matches", []), None
    except Exception as e:
        error = f"Exception réseau sur {competition_id} : {e}"
        log.warning(error)
        return [], error


def refill() -> dict:
    """Récupère les derniers résultats terminés des grandes compétitions et
    les ajoute à historical_results.db (sans doublons, via INSERT OR IGNORE).
    Applique ensuite le plafond rotatif MAX_ROWS. Retourne un résumé."""
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    _ensure_tables(conn)

    added = 0
    errors = []
    for competition_id in COMPETITIONS:
        matches, error = _fetch_competition_matches(competition_id)
        if error:
            errors.append(error)
        for m in matches:
            score = m.get("score", {}).get("fullTime", {})
            hs, as_ = score.get("home"), score.get("away")
            result = _result_letter(hs, as_)
            if not result:
                continue
            utc_date = m.get("utcDate", "")
            try:
                ts = int(datetime.fromisoformat(utc_date.replace("Z", "+00:00")).timestamp()) if utc_date else None
            except Exception:
                ts = None
            cur = conn.execute(
                f"""INSERT OR IGNORE INTO {HISTORICAL_TABLE} (
                        match_id, competition_id, home_team_id, away_team_id,
                        home_team_name, away_team_name, home_score, away_score,
                        result, status, utc_date, timestamp, season_id, matchday, last_updated
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    m.get("id"), competition_id,
                    m.get("homeTeam", {}).get("id"), m.get("awayTeam", {}).get("id"),
                    m.get("homeTeam", {}).get("name"), m.get("awayTeam", {}).get("name"),
                    hs, as_, result, "FINISHED", utc_date, ts,
                    (m.get("season") or {}).get("id"), m.get("matchday"),
                    datetime.now().isoformat(),
                ),
            )
            if cur.rowcount:
                added += 1

        conn.commit()
        time.sleep(6.5)  # respecte la limite gratuite de 10 requêtes/minute

    total = conn.execute(f"SELECT COUNT(*) FROM {HISTORICAL_TABLE}").fetchone()[0]
    pruned = 0
    overflow = total - MAX_ROWS
    if overflow > 0:
        conn.execute(
            f"""DELETE FROM {HISTORICAL_TABLE} WHERE match_id IN (
                    SELECT match_id FROM {HISTORICAL_TABLE} ORDER BY utc_date ASC LIMIT ?
                )"""
            , (overflow,),
        )
        pruned = overflow
        conn.commit()
        total = MAX_ROWS

    conn.execute("INSERT OR REPLACE INTO import_meta (key, value) VALUES ('last_import_at', ?)", (datetime.now().isoformat(),))
    conn.execute("INSERT OR REPLACE INTO import_meta (key, value) VALUES ('last_import_count', ?)", (str(added),))
    if errors:
        conn.execute("INSERT OR REPLACE INTO import_meta (key, value) VALUES ('last_errors', ?)", (" | ".join(errors)[:500],))
    conn.commit()
    conn.close()

    result = {"added": added, "total": total, "pruned": pruned}
    if errors:
        result["errors"] = errors
        log.warning("historical_data_refill terminé avec %d erreur(s) : %s", len(errors), errors)
    return result


def get_stats() -> dict:
    """Pour l'affichage du compteur dans le dashboard."""
    empty = {"total": 0, "capacity": MAX_ROWS, "last_import_at": None, "last_import_count": 0, "last_errors": None}
    if not HISTORICAL_DB_PATH.exists():
        return empty
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    try:
        if not _table_exists(conn, HISTORICAL_TABLE):
            return empty
        total = conn.execute(f"SELECT COUNT(*) FROM {HISTORICAL_TABLE}").fetchone()[0]
        meta = {}
        if _table_exists(conn, "import_meta"):
            meta = dict(conn.execute("SELECT key, value FROM import_meta").fetchall())
        return {
            "total": total,
            "capacity": MAX_ROWS,
            "last_import_at": meta.get("last_import_at"),
            "last_import_count": int(meta.get("last_import_count", 0) or 0),
            "last_errors": meta.get("last_errors"),
        }
    finally:
        conn.close()


def refill_if_due(min_hours: float = 24.0) -> dict | None:
    """Ne relance un import que si le précédent date de plus de `min_hours`
    (évite de solliciter l'API à chaque cycle de 10 min pour rien : les
    championnats ne produisent pas de nouveaux résultats aussi souvent).
    Retourne None si ce n'était pas encore dû."""
    stats = get_stats()
    last = stats.get("last_import_at")
    if last:
        try:
            elapsed_hours = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 3600
            if elapsed_hours < min_hours:
                return None
        except Exception:
            pass
    return refill()
