"""
Exporte les matchs sans résultat vers un CSV à compléter manuellement.

Usage:
    python export_missing_results.py
    python export_missing_results.py --out missing_results_to_fill.csv
"""

import sys
import io

# Forcer l'encodage UTF-8 sur la console Windows : sans ça, tout print()
# contenant un caractere hors cp1252 (emoji, box-drawing...) peut planter
# avec "UnicodeEncodeError: 'charmap' codec can't encode character".
try:
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import argparse
import csv
import sqlite3
from pathlib import Path

DB_PATH = Path("congobet.db")


def export_missing(db_path: Path, out_path: Path) -> dict:
    if not db_path.exists():
        raise FileNotFoundError(f"Base introuvable: {db_path}")

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    cols = {row[1] for row in db.execute("PRAGMA table_info(matches)").fetchall()}
    required = {"result", "home_score", "away_score"}
    if not required.issubset(cols):
        db.close()
        raise RuntimeError("Colonnes résultat absentes. Lance d'abord scraper_api.py une fois.")

    rows = db.execute(
        """
        SELECT id, home, away, start_time, league, country
        FROM matches
        WHERE result IS NULL
        ORDER BY start_time ASC, scraped_at DESC
        """
    ).fetchall()
    db.close()

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "home", "away", "date", "home_score", "away_score", "result", "league", "country"])
        for row in rows:
            date_value = (row["start_time"] or "")[:10]
            writer.writerow([
                row["id"],
                row["home"],
                row["away"],
                date_value,
                "",
                "",
                "",
                row["league"] or "",
                row["country"] or "",
            ])

    return {"count": len(rows), "out": str(out_path)}


def main():
    parser = argparse.ArgumentParser(description="Exporte les matchs sans résultat vers CSV")
    parser.add_argument("--db", default=str(DB_PATH), help="Chemin vers congobet.db")
    parser.add_argument("--out", default="missing_results_to_fill.csv", help="Nom du CSV de sortie")
    args = parser.parse_args()

    stats = export_missing(Path(args.db), Path(args.out))
    print("\n=== Export matchs sans résultat ===")
    print(f"Fichier : {stats['out']}")
    print(f"Matchs  : {stats['count']}\n")
    print("Ensuite:")
    print("1) Remplis home_score / away_score (ou result)")
    print("2) Réimporte avec: python results_importer.py --file <ton_csv>\n")


if __name__ == "__main__":
    main()
