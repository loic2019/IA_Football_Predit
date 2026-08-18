"""
migrate_missing_nn_features.py — Force le ré-entraînement des entrées
antérieures à l'ajout de nn_features/source/match_date
================================================================================
predictor.py::record_training_match() n'ajoute nn_features, source et
match_date que depuis un correctif récent. Les entrées créées AVANT ce
correctif restent à jamais incomplètes : has_trained_match() les considère
comme "déjà entraînées" (elles sont bien dans history) et les ignore pour
toujours — elles ne récupéreront donc jamais ces champs, même après des
dizaines de nouveaux cycles. C'est ce qui bloque `--train-nn` à "0 échantillon
disponible" malgré des milliers de matchs réels en historique.

Ce script retire ces entrées incomplètes de l'historique (elles restent dans
historical_results.db / congobet.db — rien n'est perdu à la source), afin
qu'elles soient automatiquement reprises au prochain entraînement, cette fois
avec nn_features + source + match_date + le tri chronologique déjà corrigé.

Sécurité :
- Sauvegarde model_data.json -> model_data.json.bak avant modification.
- Mode --dry-run par défaut : affiche ce qui SERAIT retiré, sans rien modifier.

Effet attendu : le compteur "Prédictions vérifiées" va temporairement BAISSER
après ce script (les entrées incomplètes sont retirées), puis remonter au
prochain `--train` / cycle automatique — avec cette fois des chiffres
complets et fiables. C'est normal, pas une régression.

Usage :
    python migrate_missing_nn_features.py            # aperçu
    python migrate_missing_nn_features.py --apply     # applique
    # puis : python predictor.py --train
    #        python predictor.py --train-nn 30
"""

import argparse
import shutil
from pathlib import Path

from predictor import ModelData

MODEL_PATH = Path("model_data.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Applique réellement (sinon dry-run)")
    args = parser.parse_args()

    if not MODEL_PATH.exists():
        print(f"❌ {MODEL_PATH} introuvable — lance ce script depuis le dossier de l'appli.")
        return

    if args.apply:
        shutil.copy(MODEL_PATH, MODEL_PATH.with_name(MODEL_PATH.name + ".bak"))

    model = ModelData()
    history = model.data.get("history", [])

    incomplete = [h for h in history if not h.get("nn_features")]
    complete = [h for h in history if h.get("nn_features")]

    print("=" * 60)
    print(f"  MIGRATION nn_features — {'APPLIQUÉE' if args.apply else 'APERÇU (dry-run)'}")
    print("=" * 60)
    print(f"\n  Historique total          : {len(history):,}")
    print(f"  Déjà complètes (gardées)  : {len(complete):,}")
    print(f"  Incomplètes (à retirer)   : {len(incomplete):,}")

    if not incomplete:
        print("\n✅ Rien à faire — toutes les entrées ont déjà nn_features.")
        return

    if args.apply:
        model.data["history"] = complete
        recon = model.reconcile(dry_run=False)
        print(f"\n  Prédictions vérifiées : {recon['before']['total_predictions']:,} -> {recon['after']['total_predictions']:,}")
        print(f"  Bonnes prédictions    : {recon['before']['correct_predictions']:,} -> {recon['after']['correct_predictions']:,}")
        print(f"\n✅ {len(incomplete):,} entrée(s) retirée(s) — seront réentraînées au prochain cycle.")
        print("\n💡 Prochaines étapes :")
        print("    python predictor.py --train")
        print("    python predictor.py --train-nn 30")
    else:
        print("\nExemples d'entrées qui seraient retirées :")
        for h in incomplete[:5]:
            print(f"    - [{h.get('league', '?')}] {h.get('home', '?')} vs {h.get('away', '?')}")
        print("\nℹ️  Aucune modification effectuée (dry-run).")
        print("    Relance avec --apply pour appliquer réellement :")
        print("    python migrate_missing_nn_features.py --apply")

    print("=" * 60)


if __name__ == "__main__":
    main()
