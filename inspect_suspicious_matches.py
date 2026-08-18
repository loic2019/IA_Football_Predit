"""
inspect_suspicious_matches.py — Liste les matchs les plus susceptibles d'être
de faux rapprochements (correspondance approximative nom+date)
================================================================================
Ne modifie RIEN. Affiche les entrées d'historique dont le résultat a été
retrouvé par correspondance nom d'équipe + date approximative (±3 jours)
contre historical_results.db (coupon_tracker.py::_lookup_result_free, tier 2)
— id préfixé "recent_" — plutôt que lu directement depuis une ligne
congobet.db. Ce sont les seules entrées où un vrai match peut, en théorie,
se voir attribuer le résultat d'un AUTRE match si deux équipes portent des
noms proches à quelques jours d'intervalle.

Usage :
    python inspect_suspicious_matches.py
    python inspect_suspicious_matches.py --limit 50
"""

import argparse
import json
import random
from pathlib import Path

MODEL_PATH = Path("model_data.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30, help="Nombre d'entrées à afficher")
    parser.add_argument("--sample", action="store_true",
                         help="Si aucune correspondance approximative trouvée, affiche un échantillon "
                              "aléatoire de TOUTE la base à la place (pour vérification manuelle).")
    args = parser.parse_args()

    if not MODEL_PATH.exists():
        print(f"❌ {MODEL_PATH} introuvable — lance ce script depuis le dossier de l'appli.")
        return

    with open(MODEL_PATH, encoding="utf-8") as f:
        data = json.load(f)

    history = data.get("history", [])
    suspicious = [h for h in history if str(h.get("match_id", "")).startswith("recent_")]

    print("=" * 70)
    print(f"  MATCHS À VÉRIFIER EN PRIORITÉ (correspondance approximative)")
    print("=" * 70)
    print(f"\n{len(suspicious)} entrée(s) sur {len(history)} au total dans l'historique")
    print("(résultat retrouvé par nom d'équipe + date ±3 jours, pas par ID exact)\n")

    to_show = suspicious
    if not suspicious:
        print("Aucune correspondance approximative trouvée — la cause est ailleurs.")
        print(f"Échantillon aléatoire de {min(args.limit, len(history))} entrées sur les {len(history)} au total,")
        print("toutes sources confondues, pour vérification manuelle :\n")
        random.seed(0)
        to_show = random.sample(history, min(args.limit, len(history)))

    for h in to_show[:args.limit]:
        print(f"  [{h.get('league', '?')}] {h.get('home', '?')} vs {h.get('away', '?')}")
        print(f"      résultat retenu: {h.get('actual', '?')}  |  source: {h.get('source', 'inconnue (ancienne entrée)')}")
        print(f"      match_id: {h.get('match_id', '?')}")
        if h.get("match_date"):
            print(f"      date: {h.get('match_date')}")
        print()

    if len(to_show) > args.limit:
        print(f"... et {len(to_show) - args.limit} de plus (utilise --limit pour en voir davantage)")

    print("=" * 70)
    print("Cherche chacun de ces matchs (équipes + date) sur Google/Flashscore.")
    print("S'il n'existe pas, ou si la date/le score ne correspond pas à ce qui")
    print("est affiché ici, note l'équipe/la date exacte et envoie-la : je pourrai")
    print("remonter précisément pourquoi ce rapprochement s'est fait.")
    print("=" * 70)


if __name__ == "__main__":
    main()
