# -*- coding: utf-8 -*-
"""
scraper_premierbet.py — Cotes & matchs de football Premier Bet Congo
================================================================================
Remplace le rôle du bouton BeSoccer dans la sidebar : scrape l'API JSON
interne de premierbet.com/cg (upcoming + live) et écrit dans congobet.db,
avec le MÊME schéma que scraper_api.py (CongoBet) et scraper_1xbet_api.py,
pour que ça s'affiche directement dans le dashboard et soit utilisable par
le predictor (marché "Résultat du match" avec labels 1/X/2).

Usage:
    python scraper_premierbet.py              # scrape une fois
    python scraper_premierbet.py --days 5      # récupère 5 jours de matchs à venir

Note : premierbet.com n'expose pas d'archive de résultats passés via API
publique (contrairement à besoccer/football-data.org) — ce scraper alimente
donc uniquement la partie "matchs à venir / en direct + cotes", pas
l'entraînement historique.
"""

import sys

import argparse
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from scraper_api import init_db, save_to_db  # réutilise le schéma congobet.db existant

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("premierbet-api")

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = "https://sports-api.premierbet.com/cg/v1"
SPORT_ID = "1"          # 1 = Football
COUNTRY = "CG"
GROUP = "g5"
PLATFORM = "desktop"
LOCALE = "fr"
PAGE_ID = "63fe10b530a2f04c64fbd643"

DEFAULT_DAYS_AHEAD = 3
REQUEST_DELAY_S = 1.2
TIMEOUT_S = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": "https://www.premierbet.com/cg/sport/football",
}


def fetch_upcoming(date_str: str) -> dict:
    url = f"{BASE_URL}/events/upcoming"
    params = {
        "country": COUNTRY, "group": GROUP, "platform": PLATFORM, "locale": LOCALE,
        "timeOffset": -60, "sportId": SPORT_ID, "pageId": PAGE_ID, "date": date_str,
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def fetch_live() -> dict:
    url = f"{BASE_URL}/events/live"
    params = {
        "country": COUNTRY, "group": GROUP, "platform": PLATFORM, "locale": LOCALE,
        "sportId": SPORT_ID, "pageId": PAGE_ID, "zoomSportId": "61",
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def to_congobet_matches(payload: dict, is_live: bool) -> list:
    """
    Transforme la réponse premierbet (catégories > compétitions > events) en
    liste de dicts au format attendu par scraper_api.save_to_db() :
    id, home, away, league, country, start_time, is_live, state, markets{...}

    Capture TOUS les marchés renvoyés (pas seulement 1X2) : si un marché
    "Total Corners" ou équivalent est présent dans la réponse résumé de
    l'API, il sera automatiquement stocké dans la table odds (générique) et
    donc exploitable par le predictor. Pour les matchs live, tente aussi de
    récupérer le score en cours et le temps écoulé — les noms de champs
    varient selon les fournisseurs (betradar), donc on essaie plusieurs clés
    possibles sans jamais planter si elles sont absentes.
    """
    out = []
    seen_market_names = set()  # pour le rapport de diagnostic (voir run_once)
    categories = payload.get("data", {}).get("categories", [])
    for cat in categories:
        cat_name = cat.get("name", "")
        for comp in cat.get("competitions", []):
            comp_name = comp.get("name", "")
            for event in comp.get("events", []):
                team_names = event.get("eventNames", ["", ""])
                home = team_names[0] if len(team_names) > 0 else ""
                away = team_names[1] if len(team_names) > 1 else ""

                # --- Marché principal 1X2 + capture générique de tous les marchés ---
                markets = {}
                for market in event.get("markets", []):
                    market_name = market.get("name", "")
                    seen_market_names.add(market_name)
                    outcomes = market.get("outcomes", [])
                    if not outcomes:
                        continue

                    if market_name == "1X2":
                        odd_1 = odd_x = odd_2 = None
                        for o in outcomes:
                            if o.get("name") == "1":
                                odd_1 = o.get("value")
                            elif o.get("name") == "X":
                                odd_x = o.get("value")
                            elif o.get("name") == "2":
                                odd_2 = o.get("value")
                        if odd_1 and odd_x and odd_2:
                            try:
                                markets["Résultat du match"] = {
                                    "1": float(odd_1), "X": float(odd_x), "2": float(odd_2),
                                }
                            except (TypeError, ValueError):
                                pass
                    elif any(kw in market_name.lower() for kw in ("corner",)):
                        # Marché corners détecté (ex: "Total Corners", "Corners Plus/Moins X.5")
                        # -> stocké tel quel, label = nom de l'outcome (ex "Plus 9.5"), value = cote
                        corner_odds = {}
                        for o in outcomes:
                            label = o.get("name")
                            value = o.get("value")
                            if label and value:
                                try:
                                    corner_odds[label] = float(value)
                                except (TypeError, ValueError):
                                    pass
                        if corner_odds:
                            markets[f"Corners: {market_name}"] = corner_odds

                # --- Score en cours / temps écoulé (matchs live uniquement) ---
                # Les noms de champs varient selon le fournisseur ; on essaie les clés
                # les plus courantes sans jamais lever d'exception si absentes.
                live_home_score = None
                live_away_score = None
                elapsed_minutes = None
                if is_live:
                    score_obj = event.get("currentScore") or event.get("score") or {}
                    if isinstance(score_obj, dict):
                        live_home_score = score_obj.get("home") or score_obj.get("homeScore")
                        live_away_score = score_obj.get("away") or score_obj.get("awayScore")
                    live_home_score = live_home_score if live_home_score is not None else event.get("homeScore")
                    live_away_score = live_away_score if live_away_score is not None else event.get("awayScore")
                    elapsed_minutes = (
                        event.get("matchTime") or event.get("clock") or event.get("elapsed")
                        or event.get("liveTime") or event.get("period")
                    )

                start_time_ms = event.get("startTime")
                start_time_iso = ""
                if start_time_ms:
                    start_time_iso = datetime.utcfromtimestamp(start_time_ms / 1000).isoformat()

                out.append({
                    "id": f"premierbet:{event.get('id')}",
                    "home": home,
                    "away": away,
                    "league": comp_name,
                    "country": cat_name,
                    "start_time": start_time_iso,
                    "is_live": is_live,
                    "state": "live" if is_live else "scheduled",
                    "state_details": "",
                    "home_score": live_home_score,
                    "away_score": live_away_score,
                    "result": None,
                    "scraped_at": datetime.now().isoformat(),
                    "markets": markets,
                    "_live_elapsed": elapsed_minutes,  # info diagnostic, pas stockée en DB
                })
    to_congobet_matches._seen_market_names = getattr(to_congobet_matches, "_seen_market_names", set()) | seen_market_names
    return out


LIVE_STATE_PATH = Path("data") / "premierbet_live_state.json"  # conservé pour compat, plus utilisé directement


def infer_finished_matches(current_live_matches: list) -> int:
    """Délègue au module partagé (utilisé aussi par CongoBet)."""
    from live_match_inference import infer_finished_by_disappearance
    return infer_finished_by_disappearance("premierbet", current_live_matches, db_path="congobet.db")


def run_once(days_ahead: int = DEFAULT_DAYS_AHEAD) -> dict:
    print(f"\n{'═'*55}")
    print("  🎯 Premier Bet Congo — Scraper Football")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*55}\n")

    all_matches = []
    today = datetime.now()

    for i in range(days_ahead + 1):
        date_str = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        log.info(f"→ Récupération des matchs à venir du {date_str} ...")
        try:
            payload = fetch_upcoming(date_str)
            matches = to_congobet_matches(payload, is_live=False)
            log.info(f"   {len(matches)} matchs trouvés.")
            all_matches.extend(matches)
        except Exception as e:
            log.warning(f"   ⚠️ Erreur upcoming {date_str} : {e}")
        time.sleep(REQUEST_DELAY_S)

    log.info("→ Récupération des matchs en direct ...")
    live_matches = []
    try:
        payload = fetch_live()
        live_matches = to_congobet_matches(payload, is_live=True)
        log.info(f"   {len(live_matches)} matchs en direct trouvés.")
        all_matches.extend(live_matches)
    except Exception as e:
        log.warning(f"   ⚠️ Erreur live : {e}")

    # Infère les matchs terminés (disparus du flux live) pour alimenter l'entraînement
    finished_inferred = infer_finished_matches(live_matches)
    if finished_inferred:
        log.info(f"✅ {finished_inferred} match(s) Premier Bet marqué(s) terminé(s) (résultat inféré) pour l'entraînement.")

    # Déduplique par id (un même match peut apparaître dans plusieurs jours/catégories)
    dedup = {m["id"]: m for m in all_matches}
    final_matches = list(dedup.values())
    for m in final_matches:
        m.pop("_live_elapsed", None)  # champ diagnostic uniquement, pas pour la DB

    db = init_db("congobet.db")
    count = save_to_db(db, final_matches)
    db.close()

    log.info(f"✅ {count} matchs Premier Bet sauvegardés dans congobet.db")

    # --- Rapport de diagnostic : quels marchés sont réellement disponibles ? ---
    seen_markets = sorted(getattr(to_congobet_matches, "_seen_market_names", set()))
    corner_markets = [m for m in seen_markets if "corner" in m.lower()]
    log.info(f"ℹ️ {len(seen_markets)} noms de marchés distincts vus dans cette réponse API.")
    if corner_markets:
        log.info(f"✅ Marché(s) corners détecté(s) : {corner_markets}")
    else:
        log.info(
            "⚠️ Aucun marché 'corners' trouvé dans la réponse résumé de l'API "
            "(l'API upcoming/live ne renvoie peut-être que le marché 1X2 par défaut ; "
            "un appel à un endpoint détail par match serait alors nécessaire)."
        )
    report_path = Path("logs") / f"premierbet_markets_seen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text("\n".join(seen_markets), encoding="utf-8")
    log.info(f"📄 Liste complète des marchés vus sauvegardée : {report_path}")

    return {"count": count, "matches": final_matches, "seen_markets": seen_markets}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS_AHEAD, help="Nombre de jours à venir à récupérer")
    args = parser.parse_args()
    run_once(days_ahead=args.days)
