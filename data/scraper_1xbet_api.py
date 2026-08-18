"""
Scraper 1xBet (version v3 avec correction des colonnes).

Objectif:
- recuperer des evenements (matchs) + cotes 1X2
- via l'API JSON: /service-api/LiveFeed/Get1x2_VZip
- Sauvegarde automatique dans congobet.db et JSON
- Colonnes compatibles avec la base
"""

import datetime as dt
import json
import sqlite3
import logging
import argparse
import sys
import time
from typing import Any
from pathlib import Path

import requests

# ── Configuration ──────────────────────────────────────────────────────────────

# Forcer l'encodage UTF-8 pour la console Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE = "https://1xbet.cg"
OUTPUT_DIR = Path(".")
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"1xbet_scraper_{dt.datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("1xbet-api")

GET_1X2_VZIP = (
    BASE
    + "/service-api/LiveFeed/Get1x2_VZip"
    + "?count={count}&lng=fr&gr=1877&mode=4&country=93"
    + "&top=true&virtualSports=true&noFilterBlockEvent=true"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Origin": "https://1xbet.cg",
    "Referer": "https://1xbet.cg/",
}


# ── Fonctions utilitaires ────────────────────────────────────────────────────

def _norm_team(s: str) -> str:
    import unicodedata

    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    for ch in [".", ",", "'", "’", "-", "—", "  "]:
        s = s.replace(ch, " ")
    s = " ".join(s.split())
    return s


def _unix_to_iso(seconds: int | float | None) -> str:
    if not seconds:
        return ""
    try:
        seconds = float(seconds)
        if seconds > 10_000_000_000:  # ms
            seconds = seconds / 1000.0
        return dt.datetime.fromtimestamp(seconds).isoformat()
    except Exception:
        return ""


def _extract_1x2_from_E(ev: dict[str, Any]) -> dict[str, float]:
    """
    Mapping experimental (T -> 1/X/2) base sur observations:
    - T=4 => 1
    - T=2 => X
    - T=3 => 2
    """
    E = ev.get("E", []) or []
    t_to_c: dict[int, float] = {}
    for item in E:
        try:
            t = int(item.get("T"))
            c = item.get("C")
            if c is None:
                continue
            c = float(c)
            if c > 1.0:
                t_to_c[t] = c
        except Exception:
            continue

    odds = {}
    if 4 in t_to_c:
        odds["1"] = round(t_to_c[4], 2)
    if 2 in t_to_c:
        odds["X"] = round(t_to_c[2], 2)
    if 3 in t_to_c:
        odds["2"] = round(t_to_c[3], 2)

    return odds


# ── Scraping principal ──────────────────────────────────────────────────────

def scrape_1xbet_top_events(count: int = 30) -> list[dict]:
    """
    Retourne une liste de matches au format compatible avec congobet_matches.json:
    """
    url = GET_1X2_VZIP.format(count=int(count))
    log.info(f"[REQ] 1xBet: {url[:80]}...")
    
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        log.error(f"[ERROR] Requete: {e}")
        return []
    
    try:
        payload = r.json()
    except json.JSONDecodeError as e:
        log.error(f"[ERROR] JSON: {e}")
        return []
    
    matches = []
    values = payload.get("Value", [])
    log.info(f"[DATA] {len(values)} evenements recus")

    for ev in values:
        home = ev.get("O1", "") or ""
        away = ev.get("O2", "") or ""
        if not home or not away:
            continue

        league = ev.get("L", "") or ""
        country = ev.get("CE", "") or ""
        start_time = _unix_to_iso(ev.get("S"))

        odds_1x2 = _extract_1x2_from_E(ev)
        if not odds_1x2:
            continue

        if len(odds_1x2) < 3:
            continue

        # Générer un ID unique
        import hashlib
        raw_id = f"{home}_{away}_{start_time}_{league}"
        mid = hashlib.md5(raw_id.encode()).hexdigest()[:16]
        mid = f"1xbet_{mid}"

        matches.append({
            "id": mid,
            "home": home,
            "away": away,
            "league": league,
            "country": country,
            "start_time": start_time,
            "is_live": False,
            "markets": {
                "Resultat du match": odds_1x2,
            },
            "scraped_at": dt.datetime.now().isoformat(),
        })

    return matches


# ── Sauvegarde SQLite ──────────────────────────────────────────────────────

def init_db(path: str = "congobet.db") -> sqlite3.Connection:
    """Initialise la base de donnees."""
    db = sqlite3.connect(path)
    
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='matches'")
    table_exists = cursor.fetchone() is not None
    
    if not table_exists:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS matches (
            id         TEXT PRIMARY KEY,
            home_team  TEXT,
            away_team  TEXT,
            league     TEXT,
            country    TEXT,
            start_time TEXT,
            is_live    INTEGER DEFAULT 0,
            state      TEXT,
            state_details TEXT,
            home_score INTEGER,
            away_score INTEGER,
            result     TEXT,
            scraped_at TEXT
        );
        CREATE TABLE IF NOT EXISTS odds (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id   TEXT,
            market     TEXT,
            label      TEXT,
            value      REAL,
            scraped_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_odds_match ON odds(match_id);
        CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league);
        """)
        db.commit()
        return db
    
    # Vérifier les colonnes existantes
    cursor = db.execute("PRAGMA table_info(matches)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    
    # Créer les colonnes manquantes avec les bons noms
    required_cols = {
        "league": "TEXT", 
        "country": "TEXT", 
        "state": "TEXT",
        "state_details": "TEXT", 
        "home_score": "INTEGER",
        "away_score": "INTEGER", 
        "result": "TEXT",
        "is_live": "INTEGER", 
        "scraped_at": "TEXT"
    }
    
    # Si la table a des colonnes "home" et "away" sans "_team", les renommer
    if 'home' in existing_cols and 'home_team' not in existing_cols:
        try:
            db.execute("ALTER TABLE matches RENAME COLUMN home TO home_team")
            log.info("[DB] Colonne renommee: home -> home_team")
        except:
            pass
    
    if 'away' in existing_cols and 'away_team' not in existing_cols:
        try:
            db.execute("ALTER TABLE matches RENAME COLUMN away TO away_team")
            log.info("[DB] Colonne renommee: away -> away_team")
        except:
            pass
    
    # Ajouter les colonnes manquantes
    for col, col_type in required_cols.items():
        if col not in existing_cols:
            try:
                db.execute(f"ALTER TABLE matches ADD COLUMN {col} {col_type}")
                log.info(f"[DB] Colonne ajoutee: {col}")
                db.commit()
            except Exception as e:
                log.warning(f"[DB] Erreur ajout colonne {col}: {e}")
    
    # Créer la table odds si elle n'existe pas
    db.execute("""
    CREATE TABLE IF NOT EXISTS odds (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id   TEXT,
        market     TEXT,
        label      TEXT,
        value      REAL,
        scraped_at TEXT
    )
    """)
    
    # Créer les index
    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_odds_match ON odds(match_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league)")
    except Exception as e:
        log.debug(f"Index: {e}")
    
    db.commit()
    return db


def save_to_db(db: sqlite3.Connection, matches: list[dict]) -> int:
    """Sauvegarde les matchs dans la base avec les bonnes colonnes."""
    count = 0
    for m in matches:
        try:
            db.execute("""
                INSERT OR REPLACE INTO matches (
                    id, home_team, away_team, league, country, start_time, 
                    is_live, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                m.get("id"),
                m.get("home", ""),
                m.get("away", ""),
                m.get("league", ""),
                m.get("country", ""),
                m.get("start_time", ""),
                int(m.get("is_live", False)),
                m.get("scraped_at", dt.datetime.now().isoformat())
            ))

            # Sauvegarder les cotes
            for market, odds in m.get("markets", {}).items():
                for label, value in odds.items():
                    try:
                        db.execute(
                            "INSERT INTO odds (match_id, market, label, value, scraped_at) VALUES (?,?,?,?,?)",
                            (m.get("id"), market, label, float(value), m.get("scraped_at"))
                        )
                    except Exception as e:
                        log.debug(f"Erreur insertion cote: {e}")
            count += 1
        except Exception as e:
            log.error(f"[ERROR] Sauvegarde match {m.get('id')}: {e}")
    
    db.commit()
    return count


# ── Affichage ──────────────────────────────────────────────────────────────

def print_matches_preview(matches: list[dict], title: str = "Apercu"):
    """Affiche un apercu des matchs."""
    print(f"\n{'-'*55}")
    print(f"  {title} — {len(matches)} matchs")
    print(f"{'-'*55}\n")
    
    for i, m in enumerate(matches[:5], 1):
        odds = m.get("markets", {}).get("Resultat du match", {})
        print(f"  {i}. {m.get('home')} vs {m.get('away')}")
        print(f"     League: {m.get('league')} | Time: {m.get('start_time', 'N/A')[:16]}")
        if odds:
            print(f"     Odds: 1={odds.get('1')}  X={odds.get('X')}  2={odds.get('2')}")
        print()


def countdown(seconds: int, message: str = "Prochain cycle dans"):
    """Affiche un compte a rebours."""
    for remaining in range(seconds, 0, -1):
        mins = remaining // 60
        secs = remaining % 60
        if mins > 0:
            print(f"\r[WAIT] {message} {mins}m{secs:02d}s   ", end="")
        else:
            print(f"\r[WAIT] {message} {secs:02d}s   ", end="")
        sys.stdout.flush()
        time.sleep(1)
    print("\r[WAIT] Cycle suivant !   ")


# ── Point d'entrée ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scraper 1xBet API")
    parser.add_argument("--count", type=int, default=30, help="Nombre d'evenements a recuperer")
    parser.add_argument("--loop", type=int, metavar="MINUTES", help="Scrape en boucle toutes les N minutes")
    args = parser.parse_args()

    if args.loop:
        iteration = 0
        while True:
            iteration += 1
            print(f"\n{'='*50}")
            print(f"  CYCLE 1xBET #{iteration}")
            print(f"  {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*50}")
            
            matches = scrape_1xbet_top_events(args.count)
            
            if matches:
                # Sauvegarde JSON
                json_path = OUTPUT_DIR / "1xbet_matches.json"
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "scraped_at": dt.datetime.now().isoformat(),
                        "source": "1xBet",
                        "total": len(matches),
                        "matches": matches
                    }, f, ensure_ascii=False, indent=2)
                log.info(f"[SAVE] JSON: {json_path}")

                # Sauvegarde SQLite
                db = init_db(str(OUTPUT_DIR / "congobet.db"))
                saved = save_to_db(db, matches)
                db.close()
                log.info(f"[SAVE] {saved} matchs 1xBet sauvegardes")
                
                print_matches_preview(matches, f"1xBet - Cycle #{iteration}")
            else:
                log.warning("[WARN] Aucun match 1xBet recupere")
            
            # Compte a rebours
            wait_seconds = args.loop * 60
            countdown(wait_seconds, "Prochain 1xBet dans")
            
    else:
        # Execution simple
        print(f"\n{'='*55}")
        print(f"  1XBET SCRAPER")
        print(f"  {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*55}\n")
        
        matches = scrape_1xbet_top_events(args.count)
        
        if matches:
            # Sauvegarde JSON
            json_path = OUTPUT_DIR / "1xbet_matches.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({
                    "scraped_at": dt.datetime.now().isoformat(),
                    "source": "1xBet",
                    "total": len(matches),
                    "matches": matches
                }, f, ensure_ascii=False, indent=2)
            log.info(f"[SAVE] JSON: {json_path}")

            # Sauvegarde SQLite
            db = init_db(str(OUTPUT_DIR / "congobet.db"))
            saved = save_to_db(db, matches)
            db.close()
            log.info(f"[SAVE] {saved} matchs 1xBet sauvegardes")
            
            print_matches_preview(matches, "1xBet - Apercu")
            
            print(f"{'─'*55}")
            print(f"  TOTAL: {len(matches)} matchs 1xBet")
            print(f"{'─'*55}\n")
        else:
            print("[ERROR] Aucun match 1xBet recupere")


if __name__ == "__main__":
    main()