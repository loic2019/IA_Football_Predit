# -*- coding: utf-8 -*-
"""
debug_tools/discover_api_premierbet.py — Découverte des endpoints API internes
================================================================================
Objectif : au lieu de parser le HTML rendu (fragile), on repère les appels
JSON (XHR/fetch) que le site premierbet.com fait en interne pour charger les
matchs, les cotes, les équipes, etc. Ces endpoints sont souvent stables et
bien plus simples à interroger directement (avec requests, sans navigateur).

Le script :
1. Ouvre la page d'accueil et une page de sport (ex: football) avec Playwright
2. Écoute toutes les requêtes réseau de type XHR/fetch
3. Filtre celles qui renvoient du JSON
4. Sauvegarde la liste des endpoints + un extrait de leur réponse dans un
   fichier texte, pour qu'on puisse les analyser ensemble

Installation nécessaire :
    pip install playwright-stealth
    playwright install chrome

Lancement :
    python debug_tools/discover_api_premierbet.py
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime

OUT_DIR = Path("logs")
OUT_DIR.mkdir(exist_ok=True)

# Pages à visiter pour déclencher le chargement de données (accueil + sport si possible)
URLS_TO_VISIT = [
    "https://www.premierbet.com/cg",
    "https://www.premierbet.com/cg/sport/football",  # ajustera si le chemin est différent
]

USE_REAL_CHROME = True
HEADLESS = True
PAGE_WAIT_S = 8  # temps d'attente sur chaque page pour laisser les requêtes se déclencher


async def main():
    from playwright.async_api import async_playwright

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUT_DIR / f"api_discovery_{ts}.txt"

    stealth_obj = None
    try:
        from playwright_stealth import Stealth
        stealth_obj = Stealth(navigator_languages_override=("fr-FR", "fr"))
        print("ℹ️ playwright-stealth activé.")
    except ImportError:
        print("⚠️ playwright-stealth non installé, poursuite sans.")

    captured = []  # liste de dicts {url, method, status, content_type, snippet}

    async def on_response(response):
        try:
            req = response.request
            if req.resource_type not in ("xhr", "fetch"):
                return
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                return
            try:
                body_text = await response.text()
            except Exception:
                body_text = ""
            snippet = body_text[:500]  # on ne garde qu'un extrait pour l'analyse
            captured.append({
                "url": response.url,
                "method": req.method,
                "status": response.status,
                "content_type": content_type,
                "snippet": snippet,
            })
        except Exception:
            pass  # on ignore les erreurs de capture individuelles pour ne pas interrompre le script

    async with async_playwright() as p:
        launch_kwargs = {
            "headless": HEADLESS,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if USE_REAL_CHROME:
            launch_kwargs["channel"] = "chrome"

        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="fr-FR",
            timezone_id="Africa/Brazzaville",
        )
        if stealth_obj is not None:
            try:
                await stealth_obj.apply_stealth_async(context)
            except Exception:
                pass

        page = await context.new_page()
        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        for url in URLS_TO_VISIT:
            print(f"→ Navigation vers {url} ...")
            try:
                await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            except Exception as e:
                print(f"⚠️ Erreur sur {url} : {e}")
                continue
            print(f"   ...attente de {PAGE_WAIT_S}s pour laisser les requêtes JSON se déclencher")
            await page.wait_for_timeout(PAGE_WAIT_S * 1000)

        await browser.close()

    # Déduplique par URL de base (sans les paramètres numériques variables comme les timestamps)
    seen = set()
    unique_captured = []
    for item in captured:
        key = item["url"].split("?")[0]
        if key not in seen:
            seen.add(key)
            unique_captured.append(item)

    with report_path.open("w", encoding="utf-8") as f:
        f.write(f"=== Endpoints JSON détectés ({len(unique_captured)} uniques, {len(captured)} appels au total) ===\n\n")
        for item in unique_captured:
            f.write(f"[{item['method']}] {item['status']} — {item['url']}\n")
            f.write(f"Content-Type: {item['content_type']}\n")
            f.write(f"Extrait de la réponse:\n{item['snippet']}\n")
            f.write("-" * 80 + "\n\n")

    print(f"\n✅ {len(unique_captured)} endpoints JSON uniques détectés sur {len(captured)} appels au total.")
    print(f"✅ Rapport complet sauvegardé : {report_path}")
    print("Envoie-moi ce fichier (ou colle son contenu) pour qu'on identifie les bons endpoints à utiliser.")


if __name__ == "__main__":
    asyncio.run(main())
