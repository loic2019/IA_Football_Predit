"""
repair_predictions.py — Corrige le compteur "prédictions vérifiées"
================================================================================
Contrairement à audit_predictions.py (lecture seule), CE script MODIFIE
model_data.json : il déduplique l'historique et recalcule total_predictions,
correct_predictions, calibration et league_accuracy uniquement à partir des
matchs réellement tracables (voir Predictor.ModelData.reconcile()).

Sécurité :
- Sauvegarde automatique de model_data.json en .bak avant toute écriture.
- Mode --dry-run par défaut : affiche le rapport SANS rien modifier.
  Relancer avec --apply pour appliquer réellement.

Usage :
    python repair_predictions.py            # aperçu, ne modifie rien
    python repair_predictions.py --apply     # applique et sauvegarde
"""

import argparse
import shutil
from pathlib import Path

from predictor import ModelData

MODEL_PATH = Path("model_data.json")


def main():
    parser = argparse.ArgumentParser(description="Réconciliation du compteur de prédictions")
    parser.add_argument("--apply", action="store_true", help="Applique réellement (sinon dry-run)")
    args = parser.parse_args()

    if not MODEL_PATH.exists():
        print(f"❌ {MODEL_PATH} introuvable — lance ce script depuis le dossier de l'appli.")
        return

    model = ModelData()
    report = model.reconcile(dry_run=not args.apply)

    print("=" * 60)
    print(f"  RÉCONCILIATION — {'APPLIQUÉE' if args.apply else 'APERÇU (dry-run)'}")
    print("=" * 60)
    print()
    print(f"  Prédictions vérifiées   {report['before']['total_predictions']:>8,}  ->  {report['after']['total_predictions']:>8,}")
    print(f"  Bonnes prédictions       {report['before']['correct_predictions']:>8,}  ->  {report['after']['correct_predictions']:>8,}")
    print(f"  Doublons retirés                          {report['duplicates_removed']:>8,}")
    print(f"  Entrées sans ID retirées                   {report['entries_without_id_dropped']:>8,}")
    print(f"  Dérive de compteur corrigée                {report['counter_drift_corrected']:>8,}")
    print()

    if not args.apply:
        print("ℹ️  Aucune modification effectuée (dry-run).")
        print("    Relance avec --apply pour appliquer réellement :")
        print("    python repair_predictions.py --apply")
    else:
        print(f"✅ model_data.json mis à jour (sauvegarde dans {MODEL_PATH.name}.bak)")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    if "--apply" in sys.argv and MODEL_PATH.exists():
        backup_path = MODEL_PATH.with_name(MODEL_PATH.name + ".bak")
        shutil.copy(MODEL_PATH, backup_path)
    main()
