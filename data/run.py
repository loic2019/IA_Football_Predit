"""
run.py — Lance le pipeline complet en une seule commande
=========================================================
  1. Scrape CongoBet (API directe)
  2. Génère les prédictions IA
  3. Affiche le coupon optimal
  4. Auto-entraînement sur résultats passés

Usage:
    python run.py                    # coupon 8 matchs
    python run.py --coupon 5         # coupon 5 matchs
    python run.py --coupon 12        # coupon 12 matchs
    python run.py --value            # value bets uniquement
    python run.py --loop 30          # relance toutes les 30 min
    python run.py --mise 20          # calcul gain pour 20€ misés
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

import asyncio
import argparse
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("run")

PREDICTIONS_PATH = Path("predictions_history.json")


def _save_predictions_json(predictions: list) -> None:
    """Sauvegarde au même format que common.run_prediction_pipeline(), pour que le
    dashboard (page Pronostics, Chatbot IA) puisse lire les résultats de `run.py`."""
    import json

    coupon_preview = predictions[:8]
    snapshot = {
        "generated_at": datetime.now().isoformat(),
        "source_mode": "run_cli",
        "prediction_count": len(predictions),
        "coupon": {"selections": coupon_preview, "size": len(coupon_preview)},
        "predictions": predictions,
    }
    with open(PREDICTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)


async def run_pipeline(coupon_size: int = 8, mise: float = 10.0, value_only: bool = False):
    print(f"\n{'█'*60}")
    print(f"  🤖 CONGOBET AI — Pipeline complet")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'█'*60}\n")

    # 1. Scraping
    print("📡 Étape 1/3 — Scraping (CongoBet + 1xBet)...\n")
    try:
        from scraper_multi import run_and_export_multi

        matches = await run_and_export_multi()
        if matches:
            # run_and_export_multi exporte déjà congobet_matches.json
            print(f"  ✅ {len(matches)} matchs scrapés\n")
        else:
            print("  ⚠️  Scraping vide — utilise les données existantes\n")
    except Exception as e:
        log.warning(f"Scraping multi échoué: {e} — utilise les données existantes")

    # 2. Prédictions
    print("🧠 Étape 2/3 — Génération des prédictions IA...\n")
    from predictor import (
        load_matches_from_db, load_matches_from_json, Predictor,
        normalize_result, print_coupon, print_stats,
    )

    matches = load_matches_from_json()
    if not matches:
        print("❌ Aucun match disponible.")
        return

    predictor = Predictor()
    predictions = predictor.predict_all(matches)
    _save_predictions_json(predictions)

    # 3. Coupon
    print("🎯 Étape 3/3 — Construction du coupon...\n")
    coupon_source = [p for p in predictions if p.get("is_value_bet")] if value_only else predictions
    coupon = predictor.build_coupon(
        coupon_source,
        size=coupon_size,
    )
    print_coupon(coupon, mise=mise)

    # Auto-entraînement sur les matchs terminés disponibles en base
    finished_matches = [m for m in load_matches_from_db(limit=500) if normalize_result(m.get("result"))]
    if finished_matches:
        train_stats = predictor.train_from_results(finished_matches)
        print(f"🧠 Auto-entraînement : {train_stats['trained']} matchs intégrés "
              f"(accuracy globale {train_stats['overall_accuracy']:.1%})\n")
    else:
        print("ℹ️  Aucun match terminé disponible pour l'auto-entraînement.\n")
    print_stats(predictor.model)


async def run_loop(interval_minutes: int, coupon_size: int, mise: float, value_only: bool):
    iteration = 0
    while True:
        iteration += 1
        log.info(f"Cycle #{iteration}")
        await run_pipeline(coupon_size=coupon_size, mise=mise, value_only=value_only)
        log.info(f"⏳ Prochain cycle dans {interval_minutes} min...")
        await asyncio.sleep(interval_minutes * 60)


async def main():
    parser = argparse.ArgumentParser(description="CongoBet AI — Pipeline complet")
    parser.add_argument("--coupon", type=int,   default=8,    help="Taille du coupon (défaut: 8)")
    parser.add_argument("--mise",   type=float, default=10.0, help="Mise en € (défaut: 10)")
    parser.add_argument("--value",  action="store_true",      help="Value bets uniquement")
    parser.add_argument("--loop",   type=int,   metavar="MIN", help="Boucle toutes les N minutes")
    args = parser.parse_args()

    if args.loop:
        await run_loop(args.loop, args.coupon, args.mise, args.value)
    else:
        await run_pipeline(args.coupon, args.mise, args.value)


if __name__ == "__main__":
    asyncio.run(main())
