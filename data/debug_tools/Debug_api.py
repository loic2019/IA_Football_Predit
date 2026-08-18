"""
debug_api.py — Inspecte la structure brute de l'API CongoBet
Lance : python debug_api.py
Résultat dans debug_output.json
"""
import asyncio
import aiohttp
import json

BASE = "https://hg-event-api-prod.sporty-tech.net/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Origin": "https://www.congobet.net",
    "Referer": "https://www.congobet.net/",
}

URLS = {
    "mostplayed":   f"{BASE}/events/sports/mostplayed?fr",
    "popular_101":  f"{BASE}/events/sports/popular?take=5&entryPointId=101&betTypeId=10001&l=fr",
    "top_combos":   f"{BASE}/events/sports/top-combos",
    "categories":   f"{BASE}/eventcategories/101?fr",
    "bettypes_101": f"{BASE}/eventcategories/101/bettypes?take=4&preEventOrLive=PreEvent&l=fr",
}

async def main():
    output = {}
    async with aiohttp.ClientSession() as session:
        for name, url in URLS.items():
            try:
                async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    data = await r.json(content_type=None)
                    output[name] = data
                    print(f"✅ {name}: {r.status}")
            except Exception as e:
                print(f"❌ {name}: {e}")
                output[name] = None

    # Sauvegarder tout
    with open("debug_output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Afficher la structure du premier match de chaque endpoint
    print("\n" + "="*60)
    print("STRUCTURE DES DONNÉES PAR ENDPOINT")
    print("="*60)

    for name, data in output.items():
        print(f"\n── {name} ──")
        if data is None:
            print("  VIDE")
            continue

        # Trouver le premier item
        item = None
        if isinstance(data, list) and data:
            item = data[0]
        elif isinstance(data, dict):
            for key in ("result", "events", "items", "data"):
                if key in data and isinstance(data[key], list) and data[key]:
                    item = data[key][0]
                    print(f"  (clé racine: '{key}')")
                    break
            if not item:
                item = data

        if item:
            print(f"  Type: {type(item).__name__}")
            if isinstance(item, dict):
                print(f"  Clés disponibles: {list(item.keys())}")
                # Chercher les cotes
                for key in item:
                    val = item[key]
                    if isinstance(val, list) and val:
                        print(f"  '{key}' (liste de {len(val)}): premier élément clés = {list(val[0].keys()) if isinstance(val[0], dict) else val[0]}")
                    elif isinstance(val, (int, float, str, bool)):
                        print(f"  '{key}': {val}")

    print(f"\n💾 Données complètes → debug_output.json")
    print("📤 Envoie ce fichier à Claude pour analyse !")

asyncio.run(main())