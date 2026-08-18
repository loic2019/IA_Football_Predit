# -*- coding: utf-8 -*-
"""
migrate_fix_congobet_db.py — Réparation ponctuelle (à lancer UNE FOIS)
========================================================================
Si `congobet.db` a déjà été écrasé par l'ancien `auto_scraper_all_competitions.py`
(table `matches` avec les colonnes match_id/competition_id/home_team_name au lieu
du schéma id/home_team/away_team attendu par scraper_api.py, scraper_1xbet_api.py
et scraper_multi.py), ce script :

  1. Détecte cette situation avec certitude (signature de colonnes précise).
  2. Copie les données football-data existantes vers `historical_results.db`
     (table `results_history`), pour ne rien perdre.
  3. Renomme la table `matches` de congobet.db en `matches_legacy_backup`
     (elle N'EST JAMAIS SUPPRIMÉE).
  4. Laisse ensuite scraper_api.py / scraper_1xbet_api.py / scraper_multi.py
     recréer une table `matches` propre, avec le bon schéma, au prochain lancement.

Usage :
    python migrate_fix_congobet_db.py
"""

import sys
import io

# Forcer l'encodage UTF-8 sur la console Windows : sans ça, tout print()
# contenant un caractere hors cp1252 (emoji, box-drawing...) peut planter
# avec "UnicodeEncodeError: 'charmap' codec can't encode character".
try:
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import sqlite3
from pathlib import Path
from datetime import datetime

CONGOBET_DB = Path("congobet.db")
HISTORICAL_DB = Path("historical_results.db")
HISTORICAL_TABLE = "results_history"

LEGACY_SIGNATURE = {"match_id", "competition_id", "home_team_name", "away_team_name"}


def main():
    if not CONGOBET_DB.exists():
        print(f"ℹ️  {CONGOBET_DB} n'existe pas encore, rien à faire.")
        return

    conn = sqlite3.connect(CONGOBET_DB)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='matches'")
    if not cur.fetchone():
        print(f"✅ Aucune table 'matches' dans {CONGOBET_DB}. Rien à réparer.")
        conn.close()
        return

    cur.execute("PRAGMA table_info(matches)")
    columns = {row[1] for row in cur.fetchall()}

    if not LEGACY_SIGNATURE.issubset(columns):
        print(
            f"✅ La table 'matches' de {CONGOBET_DB} a le schéma attendu "
            "(scraper_api/1xbet/multi). Rien à réparer."
        )
        conn.close()
        return

    print(f"⚠️  Table 'matches' polluée par l'ancien schéma football-data détectée dans {CONGOBET_DB}.")

    rows = cur.execute("SELECT * FROM matches").fetchall()
    col_names = [d[1] for d in cur.execute("PRAGMA table_info(matches)").fetchall()]
    print(f"📦 {len(rows)} lignes trouvées avec les colonnes : {col_names}")

    # Préparer historical_results.db
    hconn = sqlite3.connect(HISTORICAL_DB)
    hconn.execute(f"""
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

    idx = {name: i for i, name in enumerate(col_names)}
    migrated = 0
    for row in rows:
        try:
            hconn.execute(f"""
                INSERT OR IGNORE INTO {HISTORICAL_TABLE} (
                    match_id, competition_id, home_team_id, away_team_id,
                    home_team_name, away_team_name, home_score, away_score,
                    result, status, utc_date, timestamp, season_id, matchday, last_updated
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                row[idx.get("match_id")] if "match_id" in idx else None,
                row[idx.get("competition_id")] if "competition_id" in idx else None,
                row[idx.get("home_team_id")] if "home_team_id" in idx else None,
                row[idx.get("away_team_id")] if "away_team_id" in idx else None,
                row[idx.get("home_team_name")] if "home_team_name" in idx else None,
                row[idx.get("away_team_name")] if "away_team_name" in idx else None,
                row[idx.get("home_score")] if "home_score" in idx else None,
                row[idx.get("away_score")] if "away_score" in idx else None,
                row[idx.get("result")] if "result" in idx else None,
                row[idx.get("status")] if "status" in idx else None,
                row[idx.get("utc_date")] if "utc_date" in idx else None,
                row[idx.get("timestamp")] if "timestamp" in idx else None,
                row[idx.get("season_id")] if "season_id" in idx else None,
                row[idx.get("matchday")] if "matchday" in idx else None,
                datetime.now().isoformat(),
            ))
            migrated += 1
        except Exception as e:
            print(f"  ⚠️ Ligne ignorée ({row[:2]}...): {e}")

    hconn.commit()
    hconn.close()
    print(f"✅ {migrated} lignes copiées vers {HISTORICAL_DB} (table `{HISTORICAL_TABLE}`).")

    # Renommer (ne jamais supprimer)
    backup_name = "matches_legacy_backup"
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (backup_name,))
    if cur.fetchone():
        backup_name = f"matches_legacy_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    cur.execute(f"ALTER TABLE matches RENAME TO {backup_name}")
    conn.commit()
    conn.close()

    print(f"✅ Table 'matches' de {CONGOBET_DB} renommée en '{backup_name}' (conservée, non supprimée).")
    print(
        "\n➡️  Prochaine étape : relance simplement scraper_api.py, "
        "scraper_1xbet_api.py ou scraper_multi.py — ils recréeront automatiquement "
        "une table 'matches' propre avec le bon schéma."
    )


if __name__ == "__main__":
    main()
