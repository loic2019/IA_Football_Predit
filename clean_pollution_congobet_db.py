# -*- coding: utf-8 -*-
"""
clean_pollution_congobet_db.py — Nettoyage ponctuel des matchs "fictifs"
================================================================================
Contexte : un script séparé (results_importer.py) permet d'importer des
résultats historiques externes (ex: --api --league PD pour la Liga
espagnole) DIRECTEMENT dans la table `matches` de congobet.db, la même table
que celle utilisée par les vrais scrapers Congobet/1xBet/Premierbet. Ces
matchs importés n'ont jamais de cotes réelles associées (table `odds`),
contrairement à un vrai match scrapé, qui a TOUJOURS ses cotes enregistrées
au même moment. Le pipeline de prédiction les traitait donc par erreur comme
de vrais matchs "récents" à parier, avec une cote fictive de 0.00 (visible
dans "Derniers tickets" : "PD ✅ Athletic Club vs Getafe CF" par exemple).

Le code a déjà été corrigé pour ne plus JAMAIS utiliser ces matchs pollués
à l'avenir (voir common.py, get_matches_for_prediction). Ce script nettoie
UNE FOIS les matchs et coupons déjà pollués qui traînent dans ta base
actuelle.

Utilisation :
    python clean_pollution_congobet_db.py            # aperçu (dry-run)
    python clean_pollution_congobet_db.py --confirm   # applique le nettoyage
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

DB_PATH = Path("congobet.db")


def find_polluted_match_ids(conn: sqlite3.Connection) -> list[str]:
    """Un match TERMINÉ sans aucune cote enregistrée ne peut être qu'un
    import externe (results_importer.py) — un vrai match scrapé a toujours
    ses cotes écrites en même temps que le match lui-même."""
    rows = conn.execute(
        """
        SELECT m.id, m.home_team, m.away_team, m.league, m.start_time
        FROM matches m
        WHERE m.home_score IS NOT NULL AND m.away_score IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM odds o WHERE o.match_id = m.id)
        """
    ).fetchall()
    return rows


def find_polluted_coupons(conn: sqlite3.Connection, polluted_ids: set[str]) -> list[int]:
    """Repère les coupons de l'historique qui contiennent au moins une
    sélection sur un match pollué (donc une cote fictive à 0.00)."""
    ids_to_delete = []
    rows = conn.execute("SELECT id, matches_json FROM coupon_history").fetchall()
    for row in rows:
        try:
            selections = json.loads(row["matches_json"] or "[]")
        except Exception:
            continue
        for sel in selections:
            match_id = sel.get("id") or sel.get("match_id")
            if match_id in polluted_ids:
                ids_to_delete.append(row["id"])
                break
    return ids_to_delete


def main():
    parser = argparse.ArgumentParser(description="Nettoie les matchs/tickets fictifs de congobet.db")
    parser.add_argument("--confirm", action="store_true", help="Applique réellement la suppression (sinon: aperçu seul)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print("⚠️  congobet.db introuvable dans ce dossier.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    polluted_matches = find_polluted_match_ids(conn)
    polluted_ids = {m["id"] for m in polluted_matches}

    print(f"\n🔍 {len(polluted_matches)} match(s) 'fictif(s)' détecté(s) (terminé, sans aucune cote réelle) :\n")
    for m in polluted_matches[:20]:
        print(f"  - {m['home_team']} vs {m['away_team']}  ({m['league']})  {m['start_time']}")
    if len(polluted_matches) > 20:
        print(f"  ... et {len(polluted_matches) - 20} de plus.")

    polluted_coupons = find_polluted_coupons(conn, polluted_ids) if polluted_ids else []
    print(f"\n🔍 {len(polluted_coupons)} coupon(s)/ticket(s) de l'historique basé(s) sur ces matchs fictifs.\n")

    if not polluted_ids and not polluted_coupons:
        print("✅ Rien à nettoyer, ta base est propre.")
        conn.close()
        return

    if not args.confirm:
        print("Aperçu seulement — relance avec --confirm pour appliquer la suppression :")
        print("    python clean_pollution_congobet_db.py --confirm")
        conn.close()
        return

    if polluted_coupons:
        conn.executemany("DELETE FROM coupon_history WHERE id = ?", [(cid,) for cid in polluted_coupons])
    if polluted_ids:
        conn.executemany("DELETE FROM matches WHERE id = ?", [(mid,) for mid in polluted_ids])
    conn.commit()
    conn.close()

    print(f"✅ Nettoyage terminé : {len(polluted_ids)} match(s) et {len(polluted_coupons)} coupon(s) supprimé(s).")


if __name__ == "__main__":
    main()
