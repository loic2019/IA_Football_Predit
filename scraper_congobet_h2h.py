# -*- coding: utf-8 -*-
"""
scraper_congobet_h2h.py — Historique des confrontations directement sur CongoBet
================================================================================
CONTEXTE
----------------------------------------------------------------
Remplace scraper_besoccer.py (supprimé) : au lieu d'aller chercher l'historique
sur un site tiers, ce scraper récupère directement, sur la page de chaque match
CongoBet (`congobet.net/sports/event/<id>`), le panneau "Confrontations" /
"5 dernières confrontations" affiché par le widget STATSCORE intégré par
CongoBet lui-même — exactement ce que montre la capture d'écran fournie :
classes DOM `STATSCOREWidget--partialEventHorizontalH2H`,
`...__eventParticipantContainer`, `...__eventParticipantContainer--away`.

ÉCRITURE EN BASE
----------------------------------------------------------------
Écrit dans la MÊME base que l'ancien historique (historical_results.db,
table `results_history`) — donc predictor.py / common.py continuent de
fonctionner sans aucune modification de schéma. Chaque ligne est préfixée
`congobet_h2h:` sur `competition_id`, pour ne jamais se mélanger aux autres
sources (CongoBet live, 1xBet, Premierbet) dans les statistiques.

LIMITE HONNÊTE — à valider en conditions réelles
----------------------------------------------------------------
Ce fichier a été écrit dans un environnement sans accès réseau sortant vers
congobet.net : les classes CSS ci-dessus proviennent de la capture DevTools
fournie (donc réelles), mais la structure exacte des LIGNES de résultat
("18/07/2023 Club Friendly ... 5:2 ...") n'a pas pu être vérifiée en direct.
Pour rester robuste même si CongoBet change ses classes CSS internes, le
parsing se base d'abord sur le TEXTE visible du panneau (regex sur les
formats "JJ/MM/AAAA ... Nom : Nom ... score:score"), pas uniquement sur des
noms de classes qui peuvent changer.

Si `extract_h2h_from_page()` ne trouve aucune confrontation alors qu'il
devrait y en avoir, il sauvegarde automatiquement la page dans
`logs/congobet_h2h_debug_*.html` pour ajuster rapidement le parsing —
lance `python scraper_congobet_h2h.py --event-id 75865182` une première fois
et partage ce fichier si besoin.

LANCEMENT
----------------------------------------------------------------
    pip install playwright && playwright install chromium

    # Un seul match (id visible dans l'URL congobet.net/sports/event/<id>) :
    python scraper_congobet_h2h.py --event-id 75865182

    # Tous les matchs déjà connus dans congobet_matches.json :
    python scraper_congobet_h2h.py --from-congobet-matches

    # En boucle, toutes les 60 minutes (les confrontations passées changent peu) :
    python scraper_congobet_h2h.py --from-congobet-matches --loop 60
"""

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("congobet-h2h")

BASE_URL = "https://www.congobet.net/sports/event/{event_id}"
DB_PATH = Path("historical_results.db")
TABLE_NAME = "results_history"
SOURCE_PREFIX = "congobet_h2h"
CONGOBET_MATCHES_PATH = Path("congobet_matches.json")
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Anchor CSS classes confirmées via capture DevTools réelle (voir docstring).
H2H_CONTAINER_SELECTOR = "[class*='STATSCOREWidget--partialEventHorizontalH2H']"

# "18/07/2023 Club Friendly" ou "30/01/2026 Serie A"
DATE_LINE_RE = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(.+)")
# "4 : 0" ou "4:0"
SCORE_RE = re.compile(r"(\d+)\s*:\s*(\d+)")


def _stable_match_id(home: str, away: str, date_str: str) -> int:
    """ID entier stable et déterministe (results_history.match_id est INTEGER
    PRIMARY KEY) — dérivé du contenu, pas d'un compteur, pour que deux scrapes
    du même historique produisent toujours la même ligne (pas de doublons)."""
    digest = hashlib.md5(f"{home}|{away}|{date_str}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _normalize_result(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "1"
    if home_score < away_score:
        return "2"
    return "X"


def parse_h2h_text(raw_text: str, team_a: str, team_b: str) -> list[dict]:
    """
    Parse le texte visible du panneau de confrontations. Repère chaque bloc
    "date + compétition" suivi d'un score "X : Y", en associant les deux
    noms d'équipe les plus proches dans le texte. Robuste aux changements
    de classes CSS puisqu'il ne s'appuie que sur le contenu affiché.
    """
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    results = []
    i = 0
    while i < len(lines):
        date_match = DATE_LINE_RE.match(lines[i])
        if not date_match:
            i += 1
            continue
        date_str, competition = date_match.groups()

        # Cherche le score et les deux noms d'équipe dans les lignes suivantes
        # (le widget les affiche généralement juste après la date).
        window = lines[i + 1:i + 6]
        score_match = None
        home_name, away_name = None, None
        for j, w in enumerate(window):
            sm = SCORE_RE.search(w)
            if sm:
                score_match = sm
                # Nom d'équipe juste avant / juste après le score, dans la fenêtre
                before = window[j - 1] if j > 0 else None
                after = window[j + 1] if j + 1 < len(window) else None
                home_name = before
                away_name = after
                break

        if score_match and home_name and away_name:
            try:
                home_score, away_score = int(score_match.group(1)), int(score_match.group(2))
            except ValueError:
                i += 1
                continue
            results.append({
                "date": date_str,
                "competition": competition.strip(),
                "home": home_name.strip(),
                "away": away_name.strip(),
                "home_score": home_score,
                "away_score": away_score,
            })
        i += 1

    return results


async def extract_h2h_from_page(page, event_id: str, team_a: str, team_b: str) -> list[dict]:
    url = BASE_URL.format(event_id=event_id)
    try:
        await page.goto(url, wait_until="networkidle", timeout=20000)
        await page.wait_for_selector(H2H_CONTAINER_SELECTOR, timeout=8000)
    except Exception as exc:
        log.warning(f"⚠️  Panneau H2H introuvable pour {event_id} ({exc}) — sauvegarde debug HTML")
        await _save_debug_html(page, event_id)
        return []

    try:
        container = await page.query_selector(H2H_CONTAINER_SELECTOR)
        raw_text = await container.inner_text() if container else ""
    except Exception:
        raw_text = ""

    if not raw_text:
        await _save_debug_html(page, event_id)
        return []

    parsed = parse_h2h_text(raw_text, team_a, team_b)
    if not parsed:
        log.warning(f"⚠️  Aucune confrontation extraite pour {event_id} — sauvegarde debug HTML")
        await _save_debug_html(page, event_id)
    return parsed


async def _save_debug_html(page, event_id: str):
    try:
        html = await page.content()
        path = LOG_DIR / f"congobet_h2h_debug_{event_id}_{int(time.time())}.html"
        path.write_text(html, encoding="utf-8")
        log.info(f"📝 Debug HTML sauvegardé : {path}")
    except Exception as exc:
        log.debug(f"Impossible de sauvegarder le debug HTML : {exc}")


def ensure_table():
    """Même schéma que scraper_sofascore.py (results_history) — créé s'il n'existe pas déjà."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
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
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_results_comp ON {TABLE_NAME}(competition_id)")
    conn.commit()
    conn.close()


def save_confrontations(confrontations: list[dict]) -> int:
    if not confrontations:
        return 0
    ensure_table()
    conn = sqlite3.connect(DB_PATH)
    saved = 0
    for c in confrontations:
        try:
            dt = datetime.strptime(c["date"], "%d/%m/%Y")
        except ValueError:
            continue
        match_id = _stable_match_id(c["home"], c["away"], c["date"])
        result = _normalize_result(c["home_score"], c["away_score"])
        cur = conn.execute(
            f"""INSERT OR IGNORE INTO {TABLE_NAME}
                (match_id, competition_id, home_team_name, away_team_name,
                 home_score, away_score, result, status, utc_date, timestamp, last_updated)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                match_id,
                f"{SOURCE_PREFIX}:{c['competition'].lower().replace(' ', '_')}",
                c["home"], c["away"],
                c["home_score"], c["away_score"], result,
                "FINISHED",
                dt.isoformat(),
                int(dt.timestamp()),
                datetime.now().isoformat(),
            ),
        )
        if cur.rowcount:
            saved += 1
    conn.commit()
    conn.close()
    return saved


async def scrape_event(event_id: str, team_a: str = "", team_b: str = ""):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="fr-FR",
        )
        try:
            confrontations = await extract_h2h_from_page(page, event_id, team_a, team_b)
        finally:
            await browser.close()

    n_saved = save_confrontations(confrontations)
    log.info(f"✅ {event_id}: {len(confrontations)} confrontation(s) trouvée(s), {n_saved} enregistrement(s) en base")
    return confrontations


async def scrape_from_congobet_matches(limit: Optional[int] = None):
    if not CONGOBET_MATCHES_PATH.exists():
        log.error(f"{CONGOBET_MATCHES_PATH} introuvable — lance d'abord scraper_api.py pour avoir des matchs à traiter.")
        return

    data = json.loads(CONGOBET_MATCHES_PATH.read_text(encoding="utf-8"))
    matches = data.get("matches", data if isinstance(data, list) else [])
    if limit:
        matches = matches[:limit]

    from playwright.async_api import async_playwright

    total = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="fr-FR",
        )
        for m in matches:
            event_id = str(m.get("id", ""))
            if not event_id:
                continue
            confrontations = await extract_h2h_from_page(page, event_id, m.get("home", ""), m.get("away", ""))
            n_saved = save_confrontations(confrontations)
            total += n_saved
            log.info(f"  {m.get('home','?')} vs {m.get('away','?')} ({event_id}): {len(confrontations)} confrontation(s)")
            await asyncio.sleep(1.5)  # anti-détection, comme les autres scrapers du projet
        await browser.close()

    log.info(f"✅ Terminé : {total} enregistrement(s) au total dans {DB_PATH} (table {TABLE_NAME})")


def main():
    parser = argparse.ArgumentParser(description="Scraper des confrontations (head-to-head) CongoBet")
    parser.add_argument("--event-id", type=str, help="ID d'un match précis (dans l'URL congobet.net/sports/event/<id>)")
    parser.add_argument("--from-congobet-matches", action="store_true",
                         help="Traite tous les matchs déjà connus dans congobet_matches.json")
    parser.add_argument("--limit", type=int, default=None, help="Limite le nombre de matchs traités (debug)")
    parser.add_argument("--loop", type=int, default=None, help="Relance toutes les N minutes")
    args = parser.parse_args()

    async def run_once():
        if args.event_id:
            await scrape_event(args.event_id)
        elif args.from_congobet_matches:
            await scrape_from_congobet_matches(limit=args.limit)
        else:
            parser.print_help()
            sys.exit(1)

    if args.loop:
        while True:
            asyncio.run(run_once())
            log.info(f"⏳ Pause de {args.loop} minutes avant le prochain passage...")
            time.sleep(args.loop * 60)
    else:
        asyncio.run(run_once())


if __name__ == "__main__":
    main()
