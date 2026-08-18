"""
auto_cycle_worker.py — Exécute le cycle auto (scraping + entraînement + prédiction)
=======================================================================================
POURQUOI CE FICHIER EXISTE
----------------------------
Avant : app_dashboard.py déclenchait `run_auto_cycle(...)` DIRECTEMENT dans le script
Streamlit, à chaque re-render de la page (donc à chaque clic, chaque navigation entre
pages, chaque rafraîchissement automatique). Comme un cycle complet peut prendre
plusieurs dizaines de secondes à quelques minutes (scraping CongoBet + 1xBet + BeSoccer,
entraînement, prédiction), cela bloquait le rendu de la page, et le
`<meta http-equiv="refresh" content="60">` forçait en plus un rechargement complet
de l'onglet — ce qui donnait l'impression que "l'app se ferme" au bout de quelques minutes.

Maintenant : ce script tourne en PROCESS SÉPARÉ, indépendamment de Streamlit. Il lit/écrit
le même `automation_state.json` que common.py, donc le dashboard continue d'afficher un
statut à jour — mais n'exécute plus jamais lui-même le travail lourd. Le bouton
"Lancer cycle maintenant" dans la sidebar reste disponible pour un déclenchement manuel
explicite (c'est un choix utilisateur volontaire, donc acceptable que ça bloque
brièvement l'UI le temps du cycle).

LANCEMENT
---------
Dans un terminal séparé, à la racine du projet (même dossier que common.py) :

    python auto_cycle_worker.py

Pour le faire tourner en tâche de fond durable :
- Windows : Planificateur de tâches (Task Scheduler), ou `pythonw auto_cycle_worker.py`
- Linux/Mac : `nohup python auto_cycle_worker.py &` ou un service systemd/cron
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

import sys
import time
import logging
from datetime import datetime

# common.py doit être dans le même dossier / sur le PYTHONPATH
from common import load_automation_state, seconds_until_next_cycle, run_auto_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("auto_cycle_worker")

CHECK_INTERVAL_SECONDS = 15  # fréquence de vérification (léger, pas de scraping ici)


def main():
    log.info("🚀 Worker auto-cycle démarré (Ctrl+C pour arrêter)")
    log.info("   Ce process est indépendant du dashboard Streamlit.")

    while True:
        try:
            state = load_automation_state()

            if not state.get("enabled", True):
                log.info("⏸️  Auto-cycle désactivé (toggle sidebar). En attente...")
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            remaining = seconds_until_next_cycle(state)
            if remaining == 0:
                log.info("▶️  Cycle dû — lancement (scraping + entraînement + prédiction)...")
                result = run_auto_cycle(force=False, include_premierbet=True)
                if result.get("ran"):
                    status = result.get("state", {}).get("last_cycle_status")
                    log.info(f"✅ Cycle terminé — statut: {status}")
                else:
                    log.info(f"ℹ️  Cycle non lancé: {result.get('reason')}")
            else:
                log.info(f"⏳ Prochain cycle dans {remaining // 60}m {remaining % 60}s")

        except KeyboardInterrupt:
            log.info("🛑 Arrêt demandé, fin du worker.")
            sys.exit(0)
        except Exception as e:
            log.error(f"❌ Erreur dans la boucle du worker: {e}")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
