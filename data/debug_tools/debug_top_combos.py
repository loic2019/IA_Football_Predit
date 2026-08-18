"""
debug_top_combos.py — Diagnostic : capture la structure réelle de l'endpoint "Top Combinés"
==================================================================================================
POURQUOI CE SCRIPT
--------------------
Je (l'IA) n'ai pas accès à congobet.net depuis mon environnement de travail
(seuls quelques domaines techniques sont autorisés). Plutôt que de deviner la
structure JSON du endpoint "top-combos" et risquer de coder un parseur faux,
ce script se contente de FETCHER la réponse brute et de l'afficher/sauvegarder,
pour qu'on construise le vrai parseur (scraper_combos.py) sur des données
réelles.

USAGE
------
    python debug_tools/debug_top_combos.py

Ça va :
1. Appeler le même endpoint que scraper_api.py (BASE_EVENT_API/events/sports/top-combos)
2. Sauvegarder la réponse brute complète dans debug_tools/top_combos_raw.json
3. Afficher un résumé de la structure (clés du 1er niveau, structure du 1er
   combo trouvé) directement dans le terminal

ENVOIE-MOI ensuite soit :
- le résumé affiché dans le terminal (le plus rapide), soit
- le contenu de top_combos_raw.json (ou juste les 50-100 premières lignes)

... et je finalise scraper_combos.py + combos.py sur la vraie structure.
"""

import json
import sys
from pathlib import Path

import requests

BASE_EVENT_API = "https://hg-event-api-prod.sporty-tech.net/api"
LANG = "fr"
TOP_COMBOS_URL = f"{BASE_EVENT_API}/events/sports/top-combos"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Origin": "https://www.congobet.net",
    "Referer": "https://www.congobet.net/",
}

OUTPUT_PATH = Path(__file__).parent / "top_combos_raw.json"


def summarize(data, path="root", max_depth=4, depth=0):
    """Affiche récursivement la forme des données (clés, types, tailles de listes)."""
    indent = "  " * depth
    if depth > max_depth:
        print(f"{indent}{path}: ... (profondeur max atteinte)")
        return

    if isinstance(data, dict):
        print(f"{indent}{path} (dict, {len(data)} clés): {list(data.keys())}")
        for key, value in list(data.items())[:5]:
            summarize(value, f"{path}.{key}", max_depth, depth + 1)
    elif isinstance(data, list):
        print(f"{indent}{path} (list, {len(data)} éléments)")
        if data:
            summarize(data[0], f"{path}[0]", max_depth, depth + 1)
    else:
        preview = str(data)
        if len(preview) > 80:
            preview = preview[:80] + "..."
        print(f"{indent}{path} = {preview!r}")


def main():
    print(f"[REQ] GET {TOP_COMBOS_URL}")
    try:
        r = requests.get(TOP_COMBOS_URL, headers=HEADERS, timeout=20)
        print(f"[HTTP] Statut: {r.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Requête échouée: {e}")
        sys.exit(1)

    if r.status_code != 200:
        print(f"[ERROR] Réponse non-200. Corps brut (500 premiers caractères):\n{r.text[:500]}")
        sys.exit(1)

    try:
        data = r.json()
    except json.JSONDecodeError as e:
        print(f"[ERROR] Réponse non-JSON: {e}")
        print(f"Corps brut (500 premiers caractères):\n{r.text[:500]}")
        sys.exit(1)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[SAVE] Réponse brute complète sauvegardée dans: {OUTPUT_PATH.resolve()}")

    print(f"\n{'='*60}")
    print("  RÉSUMÉ DE LA STRUCTURE")
    print(f"{'='*60}")
    summarize(data)
    print(f"{'='*60}\n")

    print("➡️  Envoie-moi ce résumé ci-dessus (ou le fichier top_combos_raw.json)")
    print("   pour que je finalise le vrai parseur.")


if __name__ == "__main__":
    main()
