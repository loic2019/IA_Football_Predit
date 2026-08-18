"""
CongoBet API Scraper — Direct HTTP (pas besoin de Playwright !)
Tape directement sur l'API sporty-tech découverte par l'inspector.

Usage:
    python scraper_api.py              # scrape + affiche apercu
    python scraper_api.py --loop 15    # boucle toutes les 15 min
"""

import sys
import io

# Forcer l'encodage UTF-8 sur la console Windows : sans ça, tout print()
# contenant un caractère hors cp1252 (═, █, ✅, 📊...) plante avec
# "UnicodeEncodeError: 'charmap' codec can't encode character".
try:
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import asyncio
import aiohttp
import json
import sqlite3
import logging
import argparse
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("congobet-api")

# ── Config ────────────────────────────────────────────────────────────────────

BASE_EVENT_API = "https://hg-event-api-prod.sporty-tech.net/api"
LANG = "fr"
OUTPUT_DIR = Path(".")   # tout dans le dossier courant (compatible Windows)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Origin": "https://www.congobet.net",
    "Referer": "https://www.congobet.net/",
}

ENDPOINTS = {
    "categories":  f"{BASE_EVENT_API}/eventcategories/101?{LANG}",
    "entrypoints": f"{BASE_EVENT_API}/eventcategories/entrypoints?{LANG}",
    "mostplayed":  f"{BASE_EVENT_API}/events/sports/mostplayed?{LANG}",
    "popular":     f"{BASE_EVENT_API}/events/sports/popular?take=50&entryPointId=101&betTypeId=10001&l={LANG}",
    "top_combos":  f"{BASE_EVENT_API}/events/sports/top-combos",
    "favorites":   f"{BASE_EVENT_API}/eventcategories/sports/favorites?{LANG}",
}


# ── Parsers ───────────────────────────────────────────────────────────────────

def parse_event(event: dict) -> dict | None:
    """Transforme un event brut API en structure propre."""
    try:
        home = event.get("homeTeamName", "")
        away = event.get("awayTeamName", "")
        if not home or not away:
            return None

        markets = {}
        for bt in event.get("eventBetTypes", []):
            market_name = bt.get("name", "")
            odds = {}
            for item in bt.get("eventBetTypeItems", []):
                label = item.get("name") or item.get("shortName") or ""
                value = item.get("odds")
                if label and value:
                    odds[label] = round(float(value), 2)
            if odds:
                markets[market_name] = odds

        categories = event.get("categories", []) or []
        league = event.get("eventCategoryName") or (categories[0] if categories else "")
        country = event.get("countryName") or (categories[1] if len(categories) > 1 else "")
        start_time = event.get("startDate") or event.get("expectedStart") or ""
        home_score, away_score = extract_scores(event)
        result = extract_result(event, home_score, away_score)

        return {
            "id": str(event.get("id", "")),
            "home": home,
            "away": away,
            "league": league,
            "country": country,
            "start_time": start_time,
            "is_live": bool(event.get("isLive", False)),
            "state": event.get("state", ""),
            "state_details": event.get("stateDetails", ""),
            "home_score": home_score,
            "away_score": away_score,
            "result": result,  # "1", "X", "2" quand connu
            "markets": markets,
            "scraped_at": datetime.now().isoformat(),
        }
    except Exception as e:
        log.debug(f"parse_event error: {e}")
        return None


def extract_scores(event: dict) -> tuple[int | None, int | None]:
    """Extrait le score final/actuel depuis les formats API possibles."""
    score_candidates = event.get("scores", []) or event.get("goals", []) or []
    home_score = None
    away_score = None

    # Format liste d'objets
    for row in score_candidates:
        if not isinstance(row, dict):
            continue
        team_type = str(row.get("teamType", "")).lower()
        value = row.get("value")
        if value is None:
            value = row.get("score")
        if value is None:
            continue
        try:
            score_value = int(value)
        except Exception:
            continue
        if "home" in team_type:
            home_score = score_value
        elif "away" in team_type:
            away_score = score_value

    # Format objet data plus compact
    data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
    for key in ("homeScore", "home_score"):
        if home_score is None and key in data:
            try:
                home_score = int(data[key])
            except Exception:
                pass
    for key in ("awayScore", "away_score"):
        if away_score is None and key in data:
            try:
                away_score = int(data[key])
            except Exception:
                pass

    return home_score, away_score


def extract_result(event: dict, home_score: int | None, away_score: int | None) -> str | None:
    """Retourne 1/X/2 si le match est terminé et score disponible."""
    state_details = str(event.get("stateDetails", "")).lower()
    is_finished = any(
        kw in state_details
        for kw in ("finished", "ended", "fulltime", "afterextratime", "afterpenalties")
    )
    if not is_finished or home_score is None or away_score is None:
        return None
    if home_score > away_score:
        return "1"
    if home_score < away_score:
        return "2"
    return "X"


def parse_response(data) -> list[dict]:
    """Extrait les matchs depuis différents formats de réponse API."""
    matches = []
    items = []

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("result", "events", "items", "data"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

    for item in items:
        # Format direct event
        if "eventBetTypes" in item:
            m = parse_event(item)
            if m: matches.append(m)
        # Format imbriqué {event: {...}}
        elif "event" in item and isinstance(item["event"], dict):
            m = parse_event(item["event"])
            if m: matches.append(m)
        # Format lines [{event:...}, ...]
        elif "lines" in item:
            for line in item.get("lines", []):
                event_obj = line.get("event")
                if not isinstance(event_obj, dict):
                    continue
                m = parse_event(event_obj)
                if not m:
                    continue

                # Certaines réponses (top-combos) exposent le marché dans line.eventBetType.
                event_bet_type = line.get("eventBetType", {})
                if isinstance(event_bet_type, dict):
                    market_name = event_bet_type.get("name", "")
                    market_items = event_bet_type.get("eventBetTypeItems", []) or []
                    odds = {}
                    for market_item in market_items:
                        label = market_item.get("name") or market_item.get("shortName") or ""
                        value = market_item.get("odds")
                        if label and value:
                            odds[label] = round(float(value), 2)
                    if market_name and odds:
                        m.setdefault("markets", {})
                        m["markets"][market_name] = odds

                matches.append(m)

    return matches


# ── HTTP fetcher ──────────────────────────────────────────────────────────────

async def fetch(session: aiohttp.ClientSession, url: str, name: str = ""):
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                data = await r.json(content_type=None)
                log.info(f"✅ {name or url[:60]}: OK ({r.status})")
                return data
            else:
                log.warning(f"⚠️  {name or url[:60]}: HTTP {r.status}")
                return None
    except Exception as e:
        log.error(f"❌ {name or url[:60]}: {e}")
        return None


# ── Scraping principal ────────────────────────────────────────────────────────

async def scrape_all() -> list[dict]:
    # On fusionne par id pour agréger tous les marchés (1X2, corners, buts, etc.)
    all_by_id: dict[str, dict] = {}

    def add_matches(new_matches: list[dict]):
        for m in new_matches:
            mid = m.get("id", "")
            if not mid:
                continue

            if mid not in all_by_id:
                all_by_id[mid] = m
                continue

            existing = all_by_id[mid]

            # Fusion champs "identité"
            for k in ("home", "away", "league", "country", "start_time", "state", "state_details"):
                if not existing.get(k) and m.get(k):
                    existing[k] = m.get(k)

            existing["is_live"] = bool(existing.get("is_live", False) or m.get("is_live", False))

            # Fusion marchés
            ex_markets = existing.setdefault("markets", {})
            new_markets = m.get("markets", {}) or {}
            for market_name, odds in new_markets.items():
                if not odds:
                    continue
                ex_markets.setdefault(market_name, {})
                for label, value in odds.items():
                    # overwrite récent si présent
                    ex_markets[market_name][label] = value

            # keep latest scraped_at
            if m.get("scraped_at"):
                existing["scraped_at"] = m.get("scraped_at")

    async with aiohttp.ClientSession() as session:

        # 1. Fetch tous les endpoints principaux en parallèle
        log.info("Fetch endpoints principaux...")
        tasks = [fetch(session, url, name) for name, url in ENDPOINTS.items()]
        results = await asyncio.gather(*tasks)

        for data in results:
            if data:
                add_matches(parse_response(data))

        # 2. Récupérer les catégories et fetch chacune
        cats_data = await fetch(session, ENDPOINTS["categories"], "categories")
        cat_ids = []
        if cats_data and isinstance(cats_data, list):
            cat_ids = [c["id"] for c in cats_data if "id" in c]
            log.info(f"📂 {len(cat_ids)} catégories — fetch des 15 premières")

        if cat_ids:
            cat_urls = [
                (f"cat_{cid}", f"{BASE_EVENT_API}/events/sports/popular?take=100&entryPointId={cid}&betTypeId=10001&l={LANG}")
                for cid in cat_ids[:15]
            ]
            cat_tasks = [fetch(session, url, name) for name, url in cat_urls]
            cat_results = await asyncio.gather(*cat_tasks)
            for data in cat_results:
                if data:
                    add_matches(parse_response(data))

        # 3. Fetch matchs live
        live_url = f"{BASE_EVENT_API}/events/sports/live?l={LANG}"
        live_data = await fetch(session, live_url, "live")
        if live_data:
            add_matches(parse_response(live_data))

    return list(all_by_id.values())


# ── SQLite ────────────────────────────────────────────────────────────────────

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
    """Sauvegarde les matchs dans la base de données avec les bonnes colonnes."""
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


# ── Point d'entrée ────────────────────────────────────────────────────────────

async def run_once():
    print(f"\n{'═'*55}")
    print(f"  🎯 CongoBet API Scraper")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*55}\n")

    matches = await scrape_all()

    if not matches:
        print("⚠️  Aucun match récupéré.")
        return []

    # JSON
    json_path = OUTPUT_DIR / "congobet_matches.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"scraped_at": datetime.now().isoformat(), "total": len(matches), "matches": matches},
                  f, ensure_ascii=False, indent=2)

    # SQLite
    db = init_db(str(OUTPUT_DIR / "congobet.db"))
    saved = save_to_db(db, matches)
    db.close()

    # Infère les matchs terminés (disparus du flux live) pour alimenter l'entraînement
    try:
        from live_match_inference import infer_finished_by_disappearance
        live_matches = [m for m in matches if m.get("is_live")]
        finished_inferred = infer_finished_by_disappearance(
            "congobet", live_matches, db_path=str(OUTPUT_DIR / "congobet.db")
        )
        if finished_inferred:
            print(f"  ✅ {finished_inferred} match(s) CongoBet marqué(s) terminé(s) (résultat inféré) pour l'entraînement.")
    except Exception as e:
        print(f"  ⚠️ Inférence fin de match indisponible : {e}")

    print(f"\n{'─'*55}")
    print(f"  ✅ {saved} matchs scrapés")
    print(f"  💾 JSON   → {json_path.resolve()}")
    print(f"  🗄️  SQLite → {(OUTPUT_DIR / 'congobet.db').resolve()}")
    print(f"{'─'*55}\n")

    # Aperçu
    print("📋 Aperçu — 5 premiers matchs :\n")
    for m in matches[:5]:
        live_tag = " 🔴 LIVE" if m.get("is_live") else ""
        print(f"  {m.get('home', '')} vs {m.get('away', '')}{live_tag}")
        print(f"  📂 {m.get('league', '')} | ⏰ {m.get('start_time', 'N/A')[:16] if m.get('start_time') else 'N/A'}")
        for market, odds in list(m.get("markets", {}).items())[:1]:
            odds_str = "  ".join(f"{k}={v}" for k, v in odds.items())
            print(f"  💰 {market}: {odds_str}")
        print()

    return matches


async def run_loop(interval_minutes: int):
    iteration = 0
    while True:
        iteration += 1
        log.info(f"\n{'═'*40}\n  Cycle #{iteration}\n{'═'*40}")
        await run_once()
        log.info(f"⏳ Prochain cycle dans {interval_minutes} min...")
        await asyncio.sleep(interval_minutes * 60)


async def main():
    parser = argparse.ArgumentParser(description="CongoBet API Scraper")
    parser.add_argument("--loop", type=int, metavar="MINUTES", help="Scrape en boucle toutes les N minutes")
    args = parser.parse_args()

    if args.loop:
        await run_loop(args.loop)
    else:
        await run_once()


if __name__ == "__main__":
    asyncio.run(main())