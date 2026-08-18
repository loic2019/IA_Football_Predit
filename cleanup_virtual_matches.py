"""
cleanup_virtual_matches.py — Retire les matchs virtuels/eSport déjà en base
================================================================================
scraper_1xbet_api.py demandait jusqu'ici explicitement les sports virtuels
(virtualSports=true) sans filtrer les ligues type "Esoccer Battle" ou "Cyber
Football League" — ces matchs générés par ordinateur sont entrés dans
congobet.db avec une date, un score et des cotes tout à fait normaux en
apparence, indiscernables des vrais matchs une fois en base. Ce script
retire ce qui a déjà été importé AVANT le correctif appliqué à
scraper_1xbet_api.py (qui empêche maintenant l'entrée de nouveaux matchs
virtuels).

Nettoie :
- congobet.db : table matches (+ lignes odds correspondantes)
- model_data.json : history, puis recalcule total_predictions /
  correct_predictions / calibration / league_accuracy uniquement à partir de
  ce qui reste (réutilise predictor.ModelData.reconcile(), déjà testée)

Ne touche PAS à historical_results.db : cette base vient de football-data.org
(vraies données Premier League/Liga/Bundesliga/Serie A/Ligue 1/Champions
League), pas des scrapers de sites de paris — aucun risque de football
virtuel là-dedans.

Sécurité :
- Sauvegarde congobet.db -> congobet.db.bak et model_data.json ->
  model_data.json.bak avant toute modification.
- Mode --dry-run par défaut : affiche ce qui SERAIT supprimé, sans rien
  modifier. Relancer avec --apply pour appliquer réellement.

Usage :
    python cleanup_virtual_matches.py            # aperçu, ne modifie rien
    python cleanup_virtual_matches.py --apply     # applique et sauvegarde
"""

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

DB_PATH = Path("congobet.db")
MODEL_PATH = Path("model_data.json")

# Mêmes mots-clés que le filtre ajouté dans scraper_1xbet_api.py — dupliqués
# ici volontairement plutôt qu'importés, pour ne pas dépendre d'un module qui
# configure son propre logging/encodage au chargement (effets de bord inutiles
# pour ce script de nettoyage ponctuel).
VIRTUAL_LEAGUE_KEYWORDS = (
    "virtual", "cyber", "esoccer", "e-soccer", "efootball", "e-football",
    "fifa", "battle",
)


def is_virtual_league(league) -> bool:
    league_lower = str(league or "").lower()
    return any(kw in league_lower for kw in VIRTUAL_LEAGUE_KEYWORDS)


def clean_congobet_db(apply: bool) -> dict:
    if not DB_PATH.exists():
        return {"status": "absent", "removed": 0, "examples": []}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        tables = [t[0] for t in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        table = "matches" if "matches" in tables else ("football_matches" if "football_matches" in tables else None)
        if not table:
            return {"status": "no_matches_table", "removed": 0, "examples": []}

        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "league" not in cols:
            return {"status": "no_league_column", "removed": 0, "examples": []}
        id_col = "match_id" if "match_id" in cols else "id"
        home_col = "home_team" if "home_team" in cols else ("home" if "home" in cols else None)
        away_col = "away_team" if "away_team" in cols else ("away" if "away" in cols else None)

        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        to_remove = []
        for row in rows:
            if is_virtual_league(row["league"]):
                to_remove.append({
                    "id": row[id_col],
                    "league": row["league"],
                    "home": row[home_col] if home_col else "?",
                    "away": row[away_col] if away_col else "?",
                })

        if apply and to_remove:
            ids = [r["id"] for r in to_remove]
            placeholders = ",".join("?" * len(ids))
            if "odds" in tables:
                conn.execute(f"DELETE FROM odds WHERE match_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM {table} WHERE {id_col} IN ({placeholders})", ids)
            conn.commit()

        return {"status": "ok", "removed": len(to_remove), "examples": to_remove[:10]}
    finally:
        conn.close()


def clean_model_data(apply: bool) -> dict:
    if not MODEL_PATH.exists():
        return {"status": "absent", "removed": 0, "examples": []}

    with open(MODEL_PATH, encoding="utf-8") as f:
        data = json.load(f)

    history = data.get("history", [])
    virtual_entries = [h for h in history if is_virtual_league(h.get("league"))]
    kept = [h for h in history if not is_virtual_league(h.get("league"))]

    if apply and virtual_entries:
        data["history"] = kept
        with open(MODEL_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    examples = [
        {"league": h.get("league"), "home": h.get("home"), "away": h.get("away")}
        for h in virtual_entries[:10]
    ]
    return {"status": "ok", "removed": len(virtual_entries), "examples": examples}


def main():
    parser = argparse.ArgumentParser(description="Nettoie les matchs de football virtuel/eSport déjà en base")
    parser.add_argument("--apply", action="store_true", help="Applique réellement (sinon dry-run)")
    args = parser.parse_args()

    print("=" * 60)
    print(f"  NETTOYAGE FOOTBALL VIRTUEL/ESPORT — {'APPLIQUÉ' if args.apply else 'APERÇU (dry-run)'}")
    print("=" * 60)

    if args.apply:
        if DB_PATH.exists():
            shutil.copy(DB_PATH, DB_PATH.with_name(DB_PATH.name + ".bak"))
        if MODEL_PATH.exists():
            shutil.copy(MODEL_PATH, MODEL_PATH.with_name(MODEL_PATH.name + ".bak"))

    db_report = clean_congobet_db(apply=args.apply)
    print(f"\ncongobet.db : {db_report['removed']} match(s) virtuel(s) {'supprimé(s)' if args.apply else 'trouvé(s)'}")
    for ex in db_report["examples"]:
        print(f"    - [{ex['league']}] {ex['home']} vs {ex['away']}")
    if db_report["removed"] > 10:
        print(f"    ... et {db_report['removed'] - 10} de plus")

    model_report = clean_model_data(apply=args.apply)
    print(f"\nmodel_data.json (history) : {model_report['removed']} entrée(s) virtuelle(s) {'supprimée(s)' if args.apply else 'trouvée(s)'}")
    for ex in model_report["examples"]:
        print(f"    - [{ex['league']}] {ex['home']} vs {ex['away']}")
    if model_report["removed"] > 10:
        print(f"    ... et {model_report['removed'] - 10} de plus")

    if args.apply and model_report["removed"] > 0:
        print("\nRecalcul du compteur de prédictions (comme repair_predictions.py)...")
        from predictor import ModelData
        recon = ModelData().reconcile(dry_run=False)
        print(f"  Prédictions vérifiées : {recon['before']['total_predictions']:,} -> {recon['after']['total_predictions']:,}")
        print(f"  Bonnes prédictions    : {recon['before']['correct_predictions']:,} -> {recon['after']['correct_predictions']:,}")

    print()
    if not args.apply:
        print("ℹ️  Aucune modification effectuée (dry-run).")
        print("    Relance avec --apply pour appliquer réellement :")
        print("    python cleanup_virtual_matches.py --apply")
    else:
        print("✅ Nettoyage terminé (sauvegardes : congobet.db.bak, model_data.json.bak)")
    print("=" * 60)


if __name__ == "__main__":
    main()
