# -*- coding: utf-8 -*-
"""
get_congobet_results.py — Résultats des matchs Congobet déjà joués
================================================================================
⚠️ Point important : l'API de Congobet est un flux de COTES EN DIRECT, pas un
flux de résultats. Une fois un match terminé, il disparaît simplement du flux
"live" sans jamais renvoyer le score final. Ce script combine donc les 3
sources déjà utilisées ailleurs dans le projet (coupon_tracker.py) pour
retrouver le vrai résultat des matchs Congobet dont le coup d'envoi est passé :

  1. congobet.db          → rempli par l'inférence "disparition du live"
                             (live_match_inference.py), alimentée en exécutant
                             scraper_api.py en boucle (--loop).
  2. historical_results.db → football-data.org, grandes ligues européennes
                             seulement (PL, BL1, SA, PD, FL1, CL, EL).
  3. API-Football          → couverture large (1100+ compétitions), clé dans
                             core/config.py ou variable d'env API_FOOTBALL_KEY.

Prérequis pour avoir des résultats :
  - Il faut avoir déjà scrapé ces matchs AVANT/PENDANT qu'ils étaient live
    (le scraper doit tourner, idéalement en boucle : `python scraper_api.py
    --loop 10`), pour que congobet.db connaisse leur existence et leur date.
  - Si congobet.db est vide ou ne contient que des matchs à venir, ce script
    lance d'abord un cycle de scraping Congobet pour peupler la base.

Utilisation :
    python get_congobet_results.py                 # résultats des 3 derniers jours
    python get_congobet_results.py --days 7         # résultats des 7 derniers jours
    python get_congobet_results.py --export resultats.csv
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path("congobet.db")


def _ensure_db_populated() -> None:
    """Si congobet.db n'existe pas encore, lance un premier cycle de scraping."""
    if DB_PATH.exists():
        return
    print("ℹ️  congobet.db introuvable — lancement d'un premier scraping Congobet...")
    from scraper_api import run_once
    asyncio.run(run_once())


def get_played_matches(days_back: int = 3) -> list[dict]:
    """Récupère les matchs Congobet dont le coup d'envoi est passé, avec leur
    résultat retrouvé via le filet à 3 niveaux (congobet.db / historical_results.db
    / API-Football)."""
    _ensure_db_populated()

    if not DB_PATH.exists():
        print("⚠️  Aucune base congobet.db disponible — impossible de continuer.")
        return []

    from coupon_tracker import _lookup_result  # réutilise le filet 3-tiers existant

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cutoff_recent = datetime.now().isoformat()          # coup d'envoi déjà passé
    cutoff_old = (datetime.now() - timedelta(days=days_back)).isoformat()

    rows = conn.execute(
        """
        SELECT id, home_team, away_team, league, country, start_time,
               home_score, away_score, result
        FROM matches
        WHERE start_time IS NOT NULL AND start_time != ''
          AND start_time < ? AND start_time > ?
        ORDER BY start_time DESC
        """,
        (cutoff_recent, cutoff_old),
    ).fetchall()

    output = []
    for row in rows:
        m = dict(row)
        if not m["home_team"] or not m["away_team"]:
            continue

        looked_up = _lookup_result(conn, m["id"], m["home_team"], m["away_team"], m["start_time"])
        if looked_up is not None:
            m["home_score"] = looked_up["home_score"]
            m["away_score"] = looked_up["away_score"]
            m["result"] = looked_up["result"]

        if m["result"] is None:
            continue  # résultat pas encore disponible dans aucune des 3 sources

        output.append(m)

    conn.close()
    return output


def _format_result(m: dict) -> str:
    tag = {"1": "🏠 Victoire domicile", "X": "🤝 Match nul", "2": "🚗 Victoire extérieur"}.get(m["result"], m["result"])
    date_str = (m.get("start_time") or "")[:16].replace("T", " ")
    return (
        f"{date_str}  |  {m['league'] or '—'}\n"
        f"  {m['home_team']} {m['home_score']} - {m['away_score']} {m['away_team']}   ({tag})"
    )


def main():
    parser = argparse.ArgumentParser(description="Résultats des matchs Congobet déjà joués")
    parser.add_argument("--days", type=int, default=3, help="Nombre de jours en arrière à couvrir (défaut: 3)")
    parser.add_argument("--export", type=str, default=None, help="Chemin d'export (.csv ou .json)")
    args = parser.parse_args()

    matches = get_played_matches(days_back=args.days)

    if not matches:
        print(f"⚠️  Aucun résultat trouvé sur les {args.days} derniers jours.")
        print("    → Vérifie que scraper_api.py a bien tourné pendant que ces matchs étaient en direct")
        print("      (lance-le en boucle avec `python scraper_api.py --loop 10`), ou augmente --days.")
        return

    print(f"\n✅ {len(matches)} match(s) Congobet terminé(s) trouvé(s) :\n")
    for m in matches:
        print(_format_result(m))
        print()

    if args.export:
        path = Path(args.export)
        if path.suffix == ".json":
            path.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            import csv
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(matches[0].keys()))
                writer.writeheader()
                writer.writerows(matches)
        print(f"💾 Exporté → {path.resolve()}")


if __name__ == "__main__":
    main()
