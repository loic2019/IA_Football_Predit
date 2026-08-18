"""
audit_predictions.py — Diagnostic en LECTURE SEULE du compteur "prédictions vérifiées"
================================================================================
Ne modifie AUCUN fichier. Répond à la Partie B du prompt maître : combien des
"total_predictions" de model_data.json sont de vrais matchs vérifiés fiables,
et combien relèvent d'une autre catégorie (historique sans cotes, ID
manquant, etc.).

Usage :
    python audit_predictions.py

Sortie : le tableau de diagnostic, au format demandé, calculé sur tes VRAIS
fichiers (model_data.json, congobet.db, historical_results.db) — pas des
valeurs inventées.
"""

import json
import sqlite3
from collections import Counter
from pathlib import Path

MODEL_PATH = Path("model_data.json")
DB_PATH = Path("congobet.db")
HISTORICAL_DB_PATH = Path("historical_results.db")


def load_model_data():
    if not MODEL_PATH.exists():
        print(f"❌ {MODEL_PATH} introuvable — lance ce script depuis le dossier de l'appli.")
        return None
    with open(MODEL_PATH, encoding="utf-8") as f:
        return json.load(f)


def audit():
    data = load_model_data()
    if data is None:
        return

    total_brut = data.get("total_predictions", 0)
    history = data.get("history", [])

    # --- 1. Compteur vs historique réel (détecte le double comptage) -------
    history_len = len(history)
    counter_drift = total_brut - history_len  # > 0 si des entrées sont sorties de l'historique tronqué

    # --- 2. Doublons DANS l'historique actuellement conservé ---------------
    id_counts = Counter(str(h.get("match_id") or "") for h in history)
    duplicate_ids = {mid: c for mid, c in id_counts.items() if mid and c > 1}
    duplicate_entries = sum(c - 1 for c in duplicate_ids.values())  # entrées "en trop"

    # --- 3. Sans ID fiable ---------------------------------------------------
    no_id = sum(1 for h in history if not str(h.get("match_id") or "").strip())

    # --- 4. Origine : historique générique (historical_results.db, préfixe
    #    "hist_") vs matchs réels CongoBet/1xBet (avec cote) ------------------
    historical_source = sum(1 for h in history if str(h.get("match_id", "")).startswith("hist_"))
    real_source_with_odds = sum(
        1 for h in history
        if not str(h.get("match_id", "")).startswith("hist_") and h.get("cote")
    )
    real_source_no_odds = (
        history_len - historical_source - real_source_with_odds
    )  # match "réel" mais cote manquante/nulle enregistrée (à surveiller)

    # --- 5. Résultat manquant ou non normalisable ---------------------------
    invalid_result = sum(1 for h in history if h.get("actual") not in ("1", "X", "2"))

    # --- 6. Recoupement avec congobet.db : le match existe-t-il VRAIMENT en
    #    base, avec un score renseigné ? (uniquement pour les IDs non "hist_")
    verifiable_in_db = 0
    not_found_in_db = 0
    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            tables = [t[0] for t in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            table = "matches" if "matches" in tables else ("football_matches" if "football_matches" in tables else None)
            if table:
                cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                id_col = "match_id" if "match_id" in cols else "id"
                db_ids = {str(row[0]) for row in conn.execute(f"SELECT {id_col} FROM {table}").fetchall()}
                for h in history:
                    mid = str(h.get("match_id", ""))
                    if mid.startswith("hist_"):
                        continue
                    if mid in db_ids:
                        verifiable_in_db += 1
                    else:
                        not_found_in_db += 1
        finally:
            conn.close()
    else:
        print(f"⚠️ {DB_PATH} introuvable — impossible de recouper avec les vrais matchs Congobet.\n")

    # === RAPPORT =============================================================
    print("=" * 60)
    print("  DIAGNOSTIC — PRÉDICTIONS VÉRIFIÉES (lecture seule)")
    print("=" * 60)
    print()
    print(f"TOTAL BRUT (compteur affiché)      {total_brut:>8,}")
    print()
    print(f"  Encore présent dans l'historique  {history_len:>8,}")
    print(f"  ⚠️ Écart compteur/historique      {counter_drift:>8,}  "
          f"{'← DOUBLE COMPTAGE PROBABLE' if counter_drift > 0 else '(OK, aucun écart)'}")
    print()
    print("--- Répartition de l'historique actuellement conservé ---")
    print(f"  Matchs réels CongoBet/1xBet (avec cote)   {real_source_with_odds:>8,}")
    print(f"  Matchs réels sans cote enregistrée         {real_source_no_odds:>8,}")
    print(f"  Historique générique (football-data.org)   {historical_source:>8,}")
    print(f"  Doublons (même match_id répété)            {duplicate_entries:>8,}")
    print(f"  Sans ID fiable                              {no_id:>8,}")
    print(f"  Résultat non normalisable (ni 1/X/2)        {invalid_result:>8,}")
    if DB_PATH.exists():
        print()
        print("--- Recoupement avec congobet.db (hors historique générique) ---")
        print(f"  Confirmés présents en base                 {verifiable_in_db:>8,}")
        print(f"  ⚠️ Introuvables en base (orphelins)         {not_found_in_db:>8,}")
    print()
    print("=" * 60)
    print("NOTE : aucune date de match n'est conservée dans l'historique du")
    print("modèle actuellement (voir predictor.py::record_training_match) —")
    print("impossible de vérifier après coup qu'un match était bien PASSÉ au")
    print("moment de son entraînement. C'est un vrai trou de traçabilité, pas")
    print("une valeur calculable ici : corriger dans Predictor.record_training_match")
    print("en ajoutant match_date / source avant de pouvoir combler cette case.")
    print("=" * 60)


if __name__ == "__main__":
    audit()
