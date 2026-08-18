# -*- coding: utf-8 -*-
"""
scraper_premierbet_football.py — Cotes & matchs de football via l'API interne
================================================================================
Utilise directement l'API JSON publique découverte derrière premierbet.com/cg
(sports-api.premierbet.com) au lieu de parser le HTML. Beaucoup plus rapide,
stable, et ne nécessite pas de navigateur (juste `requests`).

Récupère :
- Les matchs à venir (upcoming) sur une plage de dates donnée
- Les matchs en direct (live)
- Les cotes 1X2 (et éventuellement d'autres marchés) pour chaque match

Sauvegarde le résultat en CSV et en JSON brut dans le dossier data/.

Lancement :
    python scraper_premierbet_football.py

Configuration en haut du fichier : nombre de jours à récupérer, délai entre
requêtes, etc.
"""

import requests
import json
import csv
import time
from pathlib import Path
from datetime import datetime, timedelta

# --- Configuration ---
BASE_URL = "https://sports-api.premierbet.com/cg/v1"
SPORT_ID = "1"          # 1 = Football
COUNTRY = "CG"
GROUP = "g5"
PLATFORM = "desktop"
LOCALE = "fr"
PAGE_ID = "63fe10b530a2f04c64fbd643"  # id de page CMS vu dans les requêtes capturées

DAYS_AHEAD = 3          # nombre de jours à venir à récupérer (aujourd'hui + N jours)
REQUEST_DELAY_S = 1.5   # pause entre chaque requête pour rester correct vis-à-vis du serveur
TIMEOUT_S = 20

OUT_DIR = Path("data")
OUT_DIR.mkdir(exist_ok=True)

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
    """Récupère les matchs à venir pour une date donnée (format YYYY-MM-DD)."""
    url = f"{BASE_URL}/events/upcoming"
    params = {
        "country": COUNTRY,
        "group": GROUP,
        "platform": PLATFORM,
        "locale": LOCALE,
        "timeOffset": -60,
        "sportId": SPORT_ID,
        "pageId": PAGE_ID,
        "date": date_str,
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def fetch_live() -> dict:
    """Récupère les matchs de football actuellement en direct."""
    url = f"{BASE_URL}/events/live"
    params = {
        "country": COUNTRY,
        "group": GROUP,
        "platform": PLATFORM,
        "locale": LOCALE,
        "sportId": SPORT_ID,
        "pageId": PAGE_ID,
        "zoomSportId": "61",
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def flatten_events(payload: dict, status_label: str) -> list:
    """
    Transforme la structure imbriquée (catégories > compétitions > événements)
    en une liste plate de dictionnaires, une ligne par match, avec les cotes 1X2
    extraites si disponibles.
    """
    rows = []
    categories = payload.get("data", {}).get("categories", [])
    for cat in categories:
        cat_name = cat.get("name")
        cat_id = cat.get("id")
        for comp in cat.get("competitions", []):
            comp_name = comp.get("name")
            comp_id = comp.get("id")
            for event in comp.get("events", []):
                team_names = event.get("eventNames", ["", ""])
                home = team_names[0] if len(team_names) > 0 else ""
                away = team_names[1] if len(team_names) > 1 else ""

                # Recherche du marché 1X2 (id "1" en live, "3" en pre-match d'après les extraits vus)
                odd_1, odd_x, odd_2 = None, None, None
                for market in event.get("markets", []):
                    if market.get("name") == "1X2":
                        outcomes = market.get("outcomes", [])
                        for o in outcomes:
                            if o.get("name") == "1":
                                odd_1 = o.get("value")
                            elif o.get("name") == "X":
                                odd_x = o.get("value")
                            elif o.get("name") == "2":
                                odd_2 = o.get("value")
                        break

                start_time_ms = event.get("startTime")
                start_time_iso = None
                if start_time_ms:
                    start_time_iso = datetime.utcfromtimestamp(start_time_ms / 1000).isoformat()

                rows.append({
                    "status": status_label,
                    "event_id": event.get("id"),
                    "provider_id": event.get("providerId"),
                    "category": cat_name,
                    "category_id": cat_id,
                    "competition": comp_name,
                    "competition_id": comp_id,
                    "home_team": home,
                    "away_team": away,
                    "start_time_utc": start_time_iso,
                    "odd_1": odd_1,
                    "odd_X": odd_x,
                    "odd_2": odd_2,
                    "market_count": event.get("marketCount"),
                })
    return rows


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_rows = []
    raw_payloads = []

    # --- Matchs à venir sur les prochains jours ---
    today = datetime.now()
    for i in range(DAYS_AHEAD + 1):
        date_str = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        print(f"→ Récupération des matchs du {date_str} ...")
        try:
            payload = fetch_upcoming(date_str)
            raw_payloads.append({"type": "upcoming", "date": date_str, "payload": payload})
            rows = flatten_events(payload, status_label="upcoming")
            print(f"   {len(rows)} matchs trouvés.")
            all_rows.extend(rows)
        except Exception as e:
            print(f"   ⚠️ Erreur : {e}")
        time.sleep(REQUEST_DELAY_S)

    # --- Matchs en direct ---
    print("→ Récupération des matchs en direct ...")
    try:
        payload = fetch_live()
        raw_payloads.append({"type": "live", "date": None, "payload": payload})
        rows = flatten_events(payload, status_label="live")
        print(f"   {len(rows)} matchs en direct trouvés.")
        all_rows.extend(rows)
    except Exception as e:
        print(f"   ⚠️ Erreur : {e}")

    # --- Sauvegarde CSV ---
    csv_path = OUT_DIR / f"premierbet_football_{ts}.csv"
    if all_rows:
        fieldnames = list(all_rows[0].keys())
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\n✅ CSV sauvegardé : {csv_path} ({len(all_rows)} lignes)")
    else:
        print("\n⚠️ Aucune donnée récupérée, CSV non créé.")

    # --- Sauvegarde JSON brut (utile si tu veux ré-analyser plus tard) ---
    json_path = OUT_DIR / f"premierbet_football_raw_{ts}.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(raw_payloads, f, ensure_ascii=False, indent=2)
    print(f"✅ JSON brut sauvegardé : {json_path}")


if __name__ == "__main__":
    main()
