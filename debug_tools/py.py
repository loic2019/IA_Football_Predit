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

import asyncio
import argparse
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("run")


async def run_pipeline(coupon_size: int = 8, mise: float = 10.0, value_only: bool = False):
    print(f"\n{'█'*60}")
    print(f"  🤖 CONGOBET AI — Pipeline complet")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'█'*60}\n")

    # 1. Scraping
    print("📡 Étape 1/3 — Scraping CongoBet...\n")
    try:
        from scraper_api import scrape_all
        import json
        matches = await scrape_all()
        if matches:
            with open("congobet_matches.json", "w", encoding="utf-8") as f:
                json.dump({
                    "scraped_at": datetime.now().isoformat(),
                    "total": len(matches),
                    "matches": matches
                }, f, ensure_ascii=False, indent=2)
            print(f"  ✅ {len(matches)} matchs scrapés\n")
        else:
            print("  ⚠️  Scraping vide — utilise les données existantes\n")
    except Exception as e:
        log.warning(f"Scraping échoué: {e} — utilise les données existantes")

    # 2. Prédictions
    print("🧠 Étape 2/3 — Génération des prédictions IA...\n")
    from predictor import (
        load_matches_from_json, Predictor,
        save_predictions, auto_train, print_coupon, print_stats
    )

    matches = load_matches_from_json()
    if not matches:
        print("❌ Aucun match disponible.")
        return

    predictor = Predictor()
    predictions = predictor.predict_all(matches)
    save_predictions(predictions)

    # 3. Coupon
    print("🎯 Étape 3/3 — Construction du coupon...\n")
    coupon = predictor.build_coupon(
        predictions,
        size=coupon_size,
        value_bets_only=value_only
    )
    print_coupon(coupon, mise=mise)

    # Auto-entraînement
    auto_train(predictor.model)
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