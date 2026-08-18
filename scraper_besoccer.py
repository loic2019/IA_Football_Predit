# -*- coding: utf-8 -*-
"""
scraper_besoccer.py — Scraper BeSoccer (résultats + calendrier via Playwright)
================================================================================
CONTEXTE — pourquoi ce fichier remplace le bouton "Sofascore"
----------------------------------------------------------------
`scraper_sofascore.py` (toujours présent, non supprimé) ne scrape en réalité
PAS Sofascore : c'est un client de l'API football-data.org, qui ne couvre que
7 grandes compétitions (PL, BL1, SA, PD, FL1, CL, EL). Un match comme
TPS - Ilves Tampere (Veikkausliiga, Finlande) n'y apparaît jamais — d'où le
"ça scrappe pas bien" pour ce genre de match. Ce nouveau scraper interroge
réellement BeSoccer (besoccer.com), qui couvre un bien plus grand nombre de
championnats (dont les ligues nordiques).

ÉCRITURE EN BASE — compatibilité avec l'existant
----------------------------------------------------------------
Écrit dans LA MÊME base que l'ancien "Sofascore" (historical_results.db,
table `results_history`) — donc predictor.py / common.py continuent de les
utiliser pour l'entraînement sans aucune modification de schéma. Pour ne
jamais mélanger les deux sources dans les stats, chaque `competition_id`
BeSoccer est préfixé `besoccer:` (ex. `besoccer:veikkausliiga`), alors que
football-data.org utilise des codes courts (`PL`, `BL1`...).

LIMITE HONNÊTE — sélecteurs à valider en conditions réelles
----------------------------------------------------------------
BeSoccer rend une bonne partie de son contenu côté serveur (repéré via
récupération de page), mais son gabarit exact (classes CSS) n'a pas pu être
vérifié depuis l'environnement où ce fichier a été écrit (pas d'accès
réseau sortant pour exécuter un vrai navigateur contre besoccer.com). Le
parsing ci-dessous utilise une stratégie délibérément robuste (recherche des
liens `/match/...` plutôt que des noms de classes CSS précis, qui changent
plus souvent). Si `fetch_competition_scores()` ne trouve aucun match alors
qu'il devrait y en avoir, il sauvegarde automatiquement la page brute dans
`logs/besoccer_debug_*.html` pour permettre un ajustement rapide des
sélecteurs — lance `python scraper_besoccer.py --competition veikkausliiga
--season 2026` une première fois et partage ce fichier si besoin.

Lancement :
    python scraper_besoccer.py --competition veikkausliiga --season 2026
    python scraper_besoccer.py --all                     # toutes les compétitions ci-dessous
    python scraper_besoccer.py --match tps-ilves-tampere  # recherche directe d'un match
"""

import argparse
import hashlib
import io
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    "db_path": "historical_results.db",  # MEME base que l'ancien "Sofascore" (football-data.org)
    "log_dir": "logs",
    "base_url": "https://www.besoccer.com",
}

TABLE_NAME = "results_history"  # table partagée, voir scraper_sofascore.py pour le schéma

# Compétitions couvertes par défaut — liste volontairement courte pour
# démarrer (dont le championnat finlandais, à l'origine de la demande).
# Ajoute un slug BeSoccer ici pour couvrir une compétition de plus (le slug
# est celui utilisé dans l'URL https://www.besoccer.com/competition/scores/<slug>/<annee>).
COMPETITIONS = {
    "veikkausliiga": "Finnish Veikkausliiga",
    "ykkosliiga": "Finnish Ykkösliiga",
}

LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"besoccer_scraper_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

SCORE_RE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")


# ============================================================================
# ACCÈS NAVIGATEUR (Playwright)
# ============================================================================

def _dismiss_gates(page) -> None:
    """BeSoccer affiche une bannière cookies + une question d'âge à la première
    visite : on les ferme si elles apparaissent, sans jamais planter si elles
    n'apparaissent pas (site testé sans session existante = comportement
    variable)."""
    for text in ("YES", "Accept", "Accepter", "OK"):
        try:
            btn = page.get_by_text(text, exact=False).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=1500)
                page.wait_for_timeout(300)
        except Exception:
            continue


def _save_debug_html(page, label: str) -> str:
    debug_path = LOG_DIR / f"besoccer_debug_{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    try:
        debug_path.write_text(page.content(), encoding="utf-8")
        logger.warning(f"Aucun match extrait — page brute sauvegardée dans {debug_path} pour ajustement des sélecteurs.")
    except Exception as e:
        logger.error(f"Impossible de sauvegarder la page de debug : {e}")
    return str(debug_path)


def _fetch_page_html(url: str, wait_selector: Optional[str] = None) -> Optional[str]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                )
            )
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            _dismiss_gates(page)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=8000)
                except Exception:
                    pass  # on tente quand même l'extraction sur ce qui a chargé
            page.wait_for_timeout(1500)  # laisse le temps au JS de finir l'hydratation
            html = page.content()
            return html
        except Exception as e:
            logger.error(f"Erreur de navigation vers {url} : {e}")
            return None
        finally:
            browser.close()


# ============================================================================
# PARSING
# ============================================================================

def _parse_score_page(html: str, competition_slug: str) -> list[dict]:
    """
    Extrait les matchs d'une page de résultats BeSoccer.

    Stratégie : repère tous les liens `/match/...` (URL stable des fiches
    match BeSoccer), puis reconstitue équipes + score à partir du texte du
    conteneur parent le plus proche qui contient un score au format "N-N".
    C'est plus robuste qu'un nom de classe CSS précis (qui peut changer à
    chaque refonte du site), au prix d'un peu de bruit qu'on filtre ensuite.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    matches = []
    seen_hrefs = set()

    for link in soup.find_all("a", href=re.compile(r"/match/[a-z0-9-]+/\d+")):
        href = link.get("href", "")
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        # Remonte jusqu'à un conteneur qui contient un score exploitable.
        container = link
        score_match = None
        for _ in range(4):
            if container is None:
                break
            text = container.get_text(" ", strip=True)
            score_match = SCORE_RE.search(text)
            if score_match:
                break
            container = container.parent

        if not container:
            continue

        # Nom des 2 équipes déduit du slug de l'URL (.../match/team-a-team-b/12345)
        slug_part = href.strip("/").split("/")
        team_slug = slug_part[1] if len(slug_part) > 1 else ""
        match_ext_id = slug_part[2] if len(slug_part) > 2 and slug_part[2].isdigit() else None

        home_score = away_score = None
        if score_match:
            home_score, away_score = int(score_match.group(1)), int(score_match.group(2))

        # Les noms d'équipes lisibles sont dans les liens imbriqués (logos/noms)
        team_links = container.find_all("a", href=re.compile(r"^/team/"))
        team_names = []
        for tl in team_links:
            name = tl.get_text(strip=True)
            if name and name not in team_names:
                team_names.append(name)

        if len(team_names) < 2:
            # Repli : essaie de déduire les noms depuis le slug (moins fiable,
            # mais évite de perdre le match si les liens d'équipe n'ont pas
            # été trouvés avec ce gabarit).
            continue

        home_name, away_name = team_names[0], team_names[1]
        result = None
        if home_score is not None and away_score is not None:
            result = "H" if home_score > away_score else "A" if away_score > home_score else "D"

        raw_id = f"besoccer:{competition_slug}:{match_ext_id or team_slug}"
        match_id = int(hashlib.md5(raw_id.encode("utf-8")).hexdigest()[:12], 16) % (10**9)

        matches.append({
            "match_id": match_id,
            "competition_id": f"besoccer:{competition_slug}",
            "home_team_name": home_name,
            "away_team_name": away_name,
            "home_score": home_score,
            "away_score": away_score,
            "result": result,
            "status": "FINISHED" if home_score is not None else "SCHEDULED",
            "utc_date": "",  # non extrait de façon fiable sans sélecteur validé — voir limite ci-dessus
        })

    return matches


# ============================================================================
# BASE DE DONNÉES (réutilise le schéma de scraper_sofascore.py)
# ============================================================================

def _ensure_table(conn: sqlite3.Connection) -> None:
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
    conn.commit()


def save_matches(matches: list[dict]) -> tuple[int, int]:
    if not matches:
        return 0, 0

    conn = sqlite3.connect(CONFIG["db_path"])
    _ensure_table(conn)

    new_count, updated_count = 0, 0
    for m in matches:
        existing = conn.execute(
            f"SELECT status FROM {TABLE_NAME} WHERE match_id = ?", (m["match_id"],)
        ).fetchone()
        if existing is None:
            new_count += 1
        elif existing[0] == m["status"]:
            continue
        else:
            updated_count += 1

        conn.execute(f"""
            INSERT OR REPLACE INTO {TABLE_NAME} (
                match_id, competition_id, home_team_name, away_team_name,
                home_score, away_score, result, status, utc_date, last_updated
            ) VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        """, (
            m["match_id"], m["competition_id"], m["home_team_name"], m["away_team_name"],
            m["home_score"], m["away_score"], m["result"], m["status"], m["utc_date"],
        ))

    conn.commit()
    conn.close()
    return new_count, updated_count


# ============================================================================
# POINTS D'ENTRÉE
# ============================================================================

def fetch_competition_scores(slug: str, season: int) -> list[dict]:
    url = f"{CONFIG['base_url']}/competition/scores/{slug}/{season}"
    logger.info(f"[BeSoccer] Récupération {slug} {season} — {url}")
    html = _fetch_page_html(url, wait_selector="a[href*='/match/']")
    if not html:
        return []

    matches = _parse_score_page(html, slug)
    if not matches:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            _save_debug_html(page, slug)
            browser.close()
    return matches


def fetch_match_search(query: str) -> list[dict]:
    """Recherche directe (ex. 'tps-ilves-tampere') — utile au coup par coup,
    moins adapté à un cycle automatique répété que fetch_competition_scores."""
    url = f"{CONFIG['base_url']}/search/{query}"
    logger.info(f"[BeSoccer] Recherche — {url}")
    html = _fetch_page_html(url)
    if not html:
        return []
    return _parse_score_page(html, "search")


def run_cycle(competitions: dict, season: int) -> dict:
    summary = {"new": 0, "updated": 0, "total": 0, "errors": 0, "competitions": {}}
    for slug, name in competitions.items():
        try:
            matches = fetch_competition_scores(slug, season)
            new, updated = save_matches(matches)
            summary["new"] += new
            summary["updated"] += updated
            summary["total"] += len(matches)
            summary["competitions"][slug] = {"name": name, "matches": len(matches), "new": new, "updated": updated}
            logger.info(f"[BeSoccer] {name} : {len(matches)} matchs ({new} nouveaux, {updated} mis à jour)")
        except Exception as e:
            summary["errors"] += 1
            summary["competitions"][slug] = {"name": name, "error": str(e)}
            logger.error(f"[BeSoccer] Erreur sur {name} ({slug}) : {e}")
        time.sleep(1)  # politesse envers le serveur entre 2 pages
    return summary


def main():
    parser = argparse.ArgumentParser(description="CongoBet AI — Scraper BeSoccer")
    parser.add_argument("--competition", type=str, help="Slug BeSoccer (ex: veikkausliiga)")
    parser.add_argument("--season", type=int, default=datetime.now().year, help="Année de saison")
    parser.add_argument("--all", action="store_true", help="Scrape toutes les compétitions de COMPETITIONS")
    parser.add_argument("--match", type=str, help="Recherche directe (ex: tps-ilves-tampere)")
    args = parser.parse_args()

    if args.match:
        matches = fetch_match_search(args.match)
        new, updated = save_matches(matches)
        print(f"[BeSoccer] Recherche '{args.match}' : {len(matches)} match(s) trouvé(s) ({new} nouveaux, {updated} mis à jour)")
        return

    if args.all:
        summary = run_cycle(COMPETITIONS, args.season)
        print(f"[BeSoccer] Terminé : {summary['total']} matchs ({summary['new']} nouveaux, {summary['updated']} mis à jour, {summary['errors']} erreurs)")
        return

    slug = args.competition or next(iter(COMPETITIONS))
    matches = fetch_competition_scores(slug, args.season)
    new, updated = save_matches(matches)
    print(f"[BeSoccer] {slug} {args.season} : {len(matches)} matchs ({new} nouveaux, {updated} mis à jour)")


if __name__ == "__main__":
    main()
