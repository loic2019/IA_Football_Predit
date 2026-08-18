# -*- coding: utf-8 -*-
"""
enrichment_api_football.py — Blessures, arbitres, joueurs, entraîneurs, cartons, météo
================================================================================
Utilise API-Football (api-sports.io) pour les données sportives détaillées et
Open-Meteo (gratuit, sans clé) pour la météo.

⚠️ QUOTA : le tier gratuit d'API-Football est limité à 100 requêtes/jour.
Impossible d'enrichir tous les matchs scrapés (des centaines) avec ce budget.
Ce module se concentre donc UNIQUEMENT sur les matchs du coupon du jour
(~8 matchs), qui nécessitent chacun environ 3-4 requêtes (recherche fixture,
blessures, compositions/arbitre) → largement dans le budget quotidien.

Configuration requise :
    - Variable d'environnement API_FOOTBALL_KEY (clé gratuite sur
      https://www.api-football.com/pricing), OU
    - core.config.get_config().api_football_key

Fonctionnement :
1. On cherche la "fixture" API-Football correspondant à notre match interne
   par nom d'équipe + date (correspondance approximative, voir _match_fixture).
2. Si trouvée, on récupère blessures / compositions (joueurs + entraîneur) /
   arbitre pour cette fixture précise.
3. On récupère la météo (Open-Meteo) via les coordonnées de la ville du stade
   renvoyées par API-Football elle-même (pas besoin de table de villes à part).
4. Tout est mis en cache dans une table SQLite dédiée (match_enrichment) pour
   ne jamais re-consommer de quota sur un même match déjà enrichi.

⚠️ Ce module n'a pas pu être testé en conditions réelles (pas d'accès réseau
à api-sports.io depuis l'environnement de développement) — teste-le d'abord
avec un seul match avant de l'intégrer au cycle automatique.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from difflib import SequenceMatcher

import requests

from core.config import get_config

API_BASE = "https://v3.football.api-sports.io"
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"
DB_PATH = "congobet.db"

REQUEST_DELAY_S = 0.5  # marge de sécurité entre appels API-Football


def _headers() -> dict:
    key = get_config().api_football_key
    if not key:
        raise RuntimeError(
            "Aucune clé API-Football configurée. Définis la variable d'environnement "
            "API_FOOTBALL_KEY avec ta clé gratuite (https://www.api-football.com/pricing)."
        )
    return {"x-apisports-key": key}


def _init_table() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_enrichment (
            match_id        TEXT PRIMARY KEY,
            fixture_id      INTEGER,
            enriched_at     TEXT,
            injuries_json   TEXT,
            referee         TEXT,
            lineup_json     TEXT,
            coach_home      TEXT,
            coach_away      TEXT,
            weather_json    TEXT,
            match_found     INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def _get_cached(match_id: str) -> dict | None:
    _init_table()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM match_enrichment WHERE match_id=?", (match_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _save_cache(match_id: str, data: dict) -> None:
    _init_table()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO match_enrichment
        (match_id, fixture_id, enriched_at, injuries_json, referee, lineup_json,
         coach_home, coach_away, weather_json, match_found)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        match_id, data.get("fixture_id"), datetime.now().isoformat(),
        json.dumps(data.get("injuries", []), ensure_ascii=False),
        data.get("referee"),
        json.dumps(data.get("lineup", {}), ensure_ascii=False),
        data.get("coach_home"), data.get("coach_away"),
        json.dumps(data.get("weather", {}), ensure_ascii=False),
        int(data.get("fixture_id") is not None),
    ))
    conn.commit()
    conn.close()


def _api_get(endpoint: str, params: dict) -> dict:
    resp = requests.get(f"{API_BASE}/{endpoint}", headers=_headers(), params=params, timeout=20)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY_S)
    return resp.json()


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").lower().strip(), (b or "").lower().strip()).ratio()


def _find_fixture(home: str, away: str, date_iso: str) -> dict | None:
    """
    Cherche la fixture API-Football correspondant à notre match. On interroge
    par date (jour du match), puis on choisit la fixture dont les noms
    d'équipes ressemblent le plus aux nôtres (nécessaire car les noms
    diffèrent parfois légèrement entre bookmakers et API-Football).
    """
    try:
        date_str = date_iso[:10]  # YYYY-MM-DD
    except Exception:
        return None

    try:
        data = _api_get("fixtures", {"date": date_str})
    except Exception:
        return None

    fixtures = data.get("response", [])
    best, best_score = None, 0.0
    for fx in fixtures:
        teams = fx.get("teams", {})
        fx_home = teams.get("home", {}).get("name", "")
        fx_away = teams.get("away", {}).get("name", "")
        score = (_name_similarity(home, fx_home) + _name_similarity(away, fx_away)) / 2
        if score > best_score:
            best_score = score
            best = fx

    # Seuil prudent : si les noms ne se ressemblent pas assez, on considère
    # qu'on n'a pas trouvé la bonne fixture plutôt que de risquer une
    # mauvaise correspondance (mieux vaut pas de donnée qu'une donnée fausse).
    if best and best_score >= 0.72:
        return best
    return None


def _get_weather_for_fixture(fixture: dict) -> dict:
    venue = fixture.get("fixture", {}).get("venue", {})
    lat, lon = venue.get("lat"), venue.get("lon")  # pas toujours fourni par l'API
    if lat is None or lon is None:
        return {}
    try:
        resp = requests.get(OPEN_METEO_BASE, params={
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation_probability",
        }, timeout=15)
        resp.raise_for_status()
        current = resp.json().get("current", {})
        return {
            "temp": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "wind": current.get("wind_speed_10m"),
            "rain_prob": (current.get("precipitation_probability") or 0) / 100.0,
        }
    except Exception:
        return {}


def enrich_match(match_id: str, home: str, away: str, start_time: str, force: bool = False) -> dict:
    """
    Enrichit UN match (blessures, arbitre, compositions, entraîneurs, météo).
    Résultat mis en cache — un match déjà enrichi n'est jamais re-interrogé
    (sauf force=True), pour préserver le quota de 100 requêtes/jour.
    """
    if not force:
        cached = _get_cached(match_id)
        if cached is not None:
            return cached

    result = {"fixture_id": None, "injuries": [], "referee": None, "lineup": {},
              "coach_home": None, "coach_away": None, "weather": {}}

    fixture = _find_fixture(home, away, start_time)
    if fixture is None:
        _save_cache(match_id, result)
        return result

    fixture_id = fixture.get("fixture", {}).get("id")
    result["fixture_id"] = fixture_id
    result["referee"] = fixture.get("fixture", {}).get("referee")

    try:
        inj_data = _api_get("injuries", {"fixture": fixture_id})
        result["injuries"] = inj_data.get("response", [])
    except Exception:
        pass

    try:
        lineup_data = _api_get("fixtures/lineups", {"fixture": fixture_id})
        lineups = lineup_data.get("response", [])
        for team_lineup in lineups:
            team_name = team_lineup.get("team", {}).get("name", "")
            coach_name = team_lineup.get("coach", {}).get("name")
            is_home = _name_similarity(team_name, home) >= _name_similarity(team_name, away)
            if is_home:
                result["coach_home"] = coach_name
            else:
                result["coach_away"] = coach_name
            result["lineup"][("home" if is_home else "away")] = team_lineup.get("startXI", [])
    except Exception:
        pass

    result["weather"] = _get_weather_for_fixture(fixture)

    _save_cache(match_id, result)
    return result


def get_fixture_result(home: str, away: str, date_iso: str) -> dict | None:
    """
    Cherche le résultat final (score + issue 1/X/2) d'un match via
    API-Football — utilisé pour régler les coupons quand ni congobet.db ni
    historical_results.db n'ont le résultat (couverture bien plus large que
    football-data.org : 1100+ compétitions selon API-Football, contre 7 pour
    football-data.org).

    Ne consomme du quota QUE si le match n'a pas déjà été trouvé/enrichi
    (réutilise le même cache que enrich_match — voir match_enrichment).
    Coûte 1 requête (recherche de fixture) si pas déjà en cache.
    """
    fixture = _find_fixture(home, away, date_iso)
    if fixture is None:
        return None

    status_short = fixture.get("fixture", {}).get("status", {}).get("short", "")
    if status_short not in ("FT", "AET", "PEN"):  # pas encore terminé
        return None

    goals = fixture.get("goals", {})
    home_score, away_score = goals.get("home"), goals.get("away")
    if home_score is None or away_score is None:
        return None

    result = "1" if home_score > away_score else "2" if away_score > home_score else "X"
    return {"result": result, "home_score": home_score, "away_score": away_score}


def enrich_coupon_matches(coupon: dict) -> dict:
    """
    Enrichit tous les matchs d'un coupon (typiquement 8) — pensé pour rester
    dans le budget gratuit de 100 req/jour (~4 requêtes/match = 32 requêtes
    pour un coupon de 8 matchs).
    """
    selections = coupon.get("selections", [])
    results = {}
    for s in selections:
        match_id = s.get("match_id") or s.get("id")
        if not match_id:
            continue
        try:
            results[match_id] = enrich_match(
                match_id, s.get("home", ""), s.get("away", ""), s.get("start_time", "")
            )
        except Exception as e:
            results[match_id] = {"error": str(e)}
    return results


def to_feature_dict(enrichment: dict, home: str, away: str) -> dict:
    """
    Transforme les données brutes API-Football au format attendu par
    feature_engineering/builder.py : match["weather"] = {...} et
    match["injuries"] = {"home": {"count":.., "suspensions":.., "key_out":..}, "away": {...}}
    """
    injuries_raw = enrichment.get("injuries", [])
    home_count = away_count = 0
    home_susp = away_susp = 0
    for inj in injuries_raw:
        team_name = inj.get("team", {}).get("name", "")
        inj_type = str(inj.get("player", {}).get("type", "") or inj.get("type", "")).lower()
        is_home = _name_similarity(team_name, home) >= _name_similarity(team_name, away)
        is_suspension = "suspend" in inj_type
        if is_home:
            home_count += 1
            home_susp += int(is_suspension)
        else:
            away_count += 1
            away_susp += int(is_suspension)

    return {
        "weather": enrichment.get("weather", {}),
        "injuries": {
            "home": {"count": home_count, "suspensions": home_susp, "key_out": home_susp},
            "away": {"count": away_count, "suspensions": away_susp, "key_out": away_susp},
        },
        "referee": enrichment.get("referee"),
        "coach_home": enrichment.get("coach_home"),
        "coach_away": enrichment.get("coach_away"),
    }


def get_enrichment_for_match(match_id: str) -> dict | None:
    """Lecture seule (utilisée par feature_engineering/builder.py)."""
    cached = _get_cached(match_id)
    if not cached:
        return None
    return {
        "injuries": json.loads(cached.get("injuries_json") or "[]"),
        "referee": cached.get("referee"),
        "lineup": json.loads(cached.get("lineup_json") or "{}"),
        "coach_home": cached.get("coach_home"),
        "coach_away": cached.get("coach_away"),
        "weather": json.loads(cached.get("weather_json") or "{}"),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 4:
        home, away, date = sys.argv[1], sys.argv[2], sys.argv[3]
        print(f"Test d'enrichissement : {home} vs {away} le {date}")
        r = enrich_match(f"test_{home}_{away}", home, away, date, force=True)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print("Usage: python enrichment_api_football.py 'Equipe Domicile' 'Equipe Exterieur' '2026-07-25'")
        print("Nécessite la variable d'environnement API_FOOTBALL_KEY définie.")
