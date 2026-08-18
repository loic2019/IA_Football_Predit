"""
Multi-sources scraping (CongoBet + 1xBet).

But:
- garder un JSON compatible avec predictor.py
- enrichir le champ "markets" par match (fusion fuzzy par home/away/start_time)
- Sauvegarde dans la base de données avec les bonnes colonnes

Note: pour l'instant, 1xBet fournit seulement 1X2 (market "Resultat du match").
"""

import sys
import io

# Forcer l'encodage UTF-8 sur la console Windows (voir scraper_api.py pour le detail)
try:
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import asyncio
import json
import sqlite3
import unicodedata
import difflib
import logging
from datetime import datetime, timedelta
from pathlib import Path

from scraper_api import scrape_all as scrape_congobet_all
from scraper_1xbet_api import scrape_1xbet_top_events

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("multi-scraper")

DB_PATH = Path("congobet.db")
JSON_PATH = Path("congobet_matches.json")

NON_DIGIT_TRANSLATE = str.maketrans("", "", "0123456789")


def norm_team(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    for ch in [".", ",", "'", "’", "-", "—"]:
        s = s.replace(ch, " ")
    s = " ".join(s.split())
    return s


def day_key(iso: str) -> str:
    if not iso:
        return ""
    return str(iso)[:10]


def init_db(path: str = "congobet.db") -> sqlite3.Connection:
    """Initialise la base de données avec les bonnes colonnes."""
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
    
    # Renommer les colonnes si nécessaire
    if 'home' in existing_cols and 'home_team' not in existing_cols:
        try:
            db.execute("ALTER TABLE matches RENAME COLUMN home TO home_team")
            log.info("🛠️ Colonne renommee: home -> home_team")
        except:
            pass
    
    if 'away' in existing_cols and 'away_team' not in existing_cols:
        try:
            db.execute("ALTER TABLE matches RENAME COLUMN away TO away_team")
            log.info("🛠️ Colonne renommee: away -> away_team")
        except:
            pass
    
    # Ajouter les colonnes manquantes
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
    
    for col, col_type in required_cols.items():
        if col not in existing_cols:
            try:
                db.execute(f"ALTER TABLE matches ADD COLUMN {col} {col_type}")
                log.info(f"🛠️ Colonne ajoutee: {col}")
                db.commit()
            except Exception as e:
                log.warning(f"⚠️ Erreur ajout colonne {col}: {e}")
    
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
    """Sauvegarde les matchs dans la base de données."""
    count = 0
    for m in matches:
        try:
            db.execute("""
                INSERT OR REPLACE INTO matches (
                    id, home_team, away_team, league, country, start_time, is_live,
                    state, state_details, home_score, away_score, result, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                m.get("id"),
                m.get("home", ""),
                m.get("away", ""),
                m.get("league", ""),
                m.get("country", ""),
                m.get("start_time", ""),
                int(m.get("is_live", False)),
                m.get("state", ""),
                m.get("state_details", ""),
                m.get("home_score"),
                m.get("away_score"),
                m.get("result"),
                m.get("scraped_at", datetime.now().isoformat())
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
            log.error(f"Erreur sauvegarde match {m.get('id')}: {e}")
    
    db.commit()
    return count


def merge_congobet_with_1xbet(congobet_matches: list[dict], xbet_matches: list[dict]) -> list[dict]:
    """Fusionne les matchs CongoBet et 1xBet."""
    # Index 1xBet
    idx_day = {}
    idx_pair = {}
    for m in xbet_matches:
        h = norm_team(m.get("home", ""))
        a = norm_team(m.get("away", ""))
        d = day_key(m.get("start_time", ""))
        idx_day.setdefault((h, a, d), []).append(m)
        idx_pair.setdefault((h, a), []).append(m)

    enriched = []
    for cm in congobet_matches:
        home = norm_team(cm.get("home", ""))
        away = norm_team(cm.get("away", ""))
        d = day_key(cm.get("start_time", ""))
        key = (home, away, d)
        merged = cm.copy()

        candidates = idx_day.get(key, [])
        xb = None
        if candidates:
            xb = candidates[0]
        else:
            candidates2 = idx_pair.get((home, away), [])
            if candidates2:
                if d:
                    exact = [c for c in candidates2 if day_key(c.get("start_time", "")) == d]
                    xb = (exact[0] if exact else candidates2[0])
                else:
                    xb = candidates2[0]

        # Fuzzy matching
        if xb is None and xbet_matches:
            def sim(a: str, b: str) -> float:
                return difflib.SequenceMatcher(None, a, b).ratio()

            best = None
            best_score = 0.0
            for cand in xbet_matches:
                ch = norm_team(cand.get("home", ""))
                ca = norm_team(cand.get("away", ""))
                score = (sim(home, ch) + sim(away, ca)) / 2.0
                if d and day_key(cand.get("start_time", "")) == d:
                    score += 0.05
                if score > best_score:
                    best_score = score
                    best = cand

            if best is not None and best_score >= 0.78:
                xb = best

        if xb:
            merged.setdefault("markets", {})
            for mk_name, odds in (xb.get("markets", {}) or {}).items():
                merged["markets"][mk_name] = odds

        enriched.append(merged)

    return enriched


async def scrape_all_multi(
    enable_congobet: bool = True,
    enable_1xbet: bool = True,
    xbet_count: int = 30,
) -> list[dict]:
    """Scrape les deux sources et fusionne."""
    congobet_matches = await scrape_congobet_all() if enable_congobet else []
    xbet_matches = scrape_1xbet_top_events(count=xbet_count) if enable_1xbet else []
    
    log.info(f"📊 CongoBet: {len(congobet_matches)} matchs")
    log.info(f"📊 1xBet: {len(xbet_matches)} matchs")
    
    if enable_congobet and enable_1xbet:
        return merge_congobet_with_1xbet(congobet_matches, xbet_matches)
    if enable_congobet:
        return congobet_matches
    return xbet_matches


async def run_and_export_multi(
    enable_congobet: bool = True,
    enable_1xbet: bool = True,
    xbet_count: int = 30,
):
    """Scrape, fusionne, sauvegarde en JSON et SQLite."""
    matches = await scrape_all_multi(
        enable_congobet=enable_congobet,
        enable_1xbet=enable_1xbet,
        xbet_count=xbet_count
    )
    
    # Sauvegarde JSON
    JSON_PATH.write_text(
        json.dumps({
            "scraped_at": datetime.now().isoformat(),
            "total": len(matches),
            "matches": matches
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"💾 JSON sauvegardé: {JSON_PATH}")
    
    # Sauvegarde SQLite
    db = init_db(str(DB_PATH))
    saved = save_to_db(db, matches)
    db.close()
    log.info(f"🗄️ SQLite: {saved} matchs sauvegardés")
    
    # Aperçu
    print(f"\n{'─'*55}")
    print(f"  ✅ {len(matches)} matchs fusionnés")
    print(f"  💾 JSON   → {JSON_PATH.resolve()}")
    print(f"  🗄️ SQLite → {DB_PATH.resolve()}")
    print(f"{'─'*55}\n")
    
    # Aperçu des 5 premiers matchs
    print("📋 Aperçu — 5 premiers matchs :\n")
    for m in matches[:5]:
        print(f"  {m.get('home', '')} vs {m.get('away', '')}")
        print(f"  📂 {m.get('league', '')} | ⏰ {m.get('start_time', 'N/A')[:16] if m.get('start_time') else 'N/A'}")
        for market, odds in list(m.get("markets", {}).items())[:1]:
            odds_str = "  ".join(f"{k}={v}" for k, v in odds.items())
            print(f"  💰 {market}: {odds_str}")
        print()
    
    return matches


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scraper multi-sources (CongoBet + 1xBet)")
    parser.add_argument("--congobet", action="store_true", help="Activer CongoBet")
    parser.add_argument("--xbet", action="store_true", help="Activer 1xBet")
    parser.add_argument("--xbet-count", type=int, default=30, help="Nombre d'events 1xBet (défaut: 30)")
    parser.add_argument("--loop", type=int, metavar="MINUTES", help="Scrape en boucle toutes les N minutes")
    args = parser.parse_args()

    enable_congobet = args.congobet or (not args.congobet and not args.xbet)
    enable_1xbet = args.xbet or (not args.congobet and not args.xbet)

    if args.loop:
        import time
        iteration = 0
        while True:
            iteration += 1
            print(f"\n{'='*50}")
            print(f"  CYCLE MULTI #{iteration}")
            print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*50}")
            
            asyncio.run(run_and_export_multi(
                enable_congobet=enable_congobet,
                enable_1xbet=enable_1xbet,
                xbet_count=args.xbet_count
            ))
            
            print(f"⏳ Prochain cycle dans {args.loop} minutes...")
            time.sleep(args.loop * 60)
    else:
        asyncio.run(run_and_export_multi(
            enable_congobet=enable_congobet,
            enable_1xbet=enable_1xbet,
            xbet_count=args.xbet_count
        ))