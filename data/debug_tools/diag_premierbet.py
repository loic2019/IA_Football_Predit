# -*- coding: utf-8 -*-
"""
debug_tools/diag_premierbet.py — Diagnostic pour https://www.premierbet.com/cg
================================================================================
Adapté du script diag_besoccer.py : teste le chargement de la page avec
Chrome réel + playwright-stealth (async), pour voir si le site a une
protection anti-bot similaire (Cloudflare/Akamai "Client Challenge") ou
si l'accès est direct.

Installation nécessaire avant de lancer ce script :
    pip install playwright-stealth
    playwright install chrome

Lancement :
    python debug_tools/diag_premierbet.py
"""

import asyncio
from pathlib import Path
from datetime import datetime

OUT_DIR = Path("logs")
OUT_DIR.mkdir(exist_ok=True)

URL = "https://www.premierbet.com/cg"

# --- Options à ajuster si besoin ---
USE_REAL_CHROME = True     # True = utilise Chrome installé (nécessite: playwright install chrome)
HEADLESS = True            # False = ouvre une fenêtre visible (utile pour debug CAPTCHA)
USE_STEALTH = True         # True = applique playwright-stealth si le paquet est installé
CHALLENGE_WAIT_S = 12      # secondes d'attente supplémentaires pour laisser un éventuel challenge se résoudre


async def main():
    from playwright.async_api import async_playwright

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = OUT_DIR / f"premierbet_diag_{ts}.png"
    html_path = OUT_DIR / f"premierbet_diag_{ts}.html"
    status = None

    stealth_obj = None
    if USE_STEALTH:
        try:
            from playwright_stealth import Stealth
            stealth_obj = Stealth(
                navigator_languages_override=("fr-FR", "fr"),
            )
            print("ℹ️ playwright-stealth (v2.x) détecté et activé.")
        except ImportError:
            print("⚠️ playwright-stealth non installé (pip install playwright-stealth). Poursuite sans.")

    async with async_playwright() as p:
        launch_kwargs = {
            "headless": HEADLESS,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        }
        if USE_REAL_CHROME:
            launch_kwargs["channel"] = "chrome"

        try:
            browser = await p.chromium.launch(**launch_kwargs)
        except Exception as e:
            print(f"❌ Impossible de lancer le navigateur : {e}")
            if USE_REAL_CHROME:
                print("   → Vérifie que Google Chrome est installé, ou lance : playwright install chrome")
            return

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
            except Exception as e:
                print(f"⚠️ Erreur lors de l'application de Stealth : {e}")

        page = await context.new_page()

        await page.set_extra_http_headers({
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })

        print(f"→ Navigation vers {URL} ...")
        try:
            response = await page.goto(URL, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"❌ page.goto a levé une exception : {e}")
            await browser.close()
            return

        status = response.status if response else None
        print(f"✅ Code HTTP de la réponse : {status if status is not None else 'AUCUNE RÉPONSE (response=None)'}")
        print(f"✅ URL finale (après redirections éventuelles) : {page.url}")

        title_initial = await page.title()
        print(f"ℹ️ Titre juste après chargement : {title_initial!r}")

        if "challenge" in title_initial.lower() or "just a moment" in title_initial.lower():
            print(f"⏳ Page de challenge détectée, attente de {CHALLENGE_WAIT_S}s pour résolution automatique...")
            await page.wait_for_timeout(CHALLENGE_WAIT_S * 1000)
        else:
            await page.wait_for_timeout(3000)

        title_final = await page.title()
        print(f"✅ Titre de la page (final) : {title_final!r}")
        print(f"✅ URL finale (après attente) : {page.url}")

        try:
            await page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"✅ Capture d'écran sauvegardée : {screenshot_path}")
        except Exception as e:
            print(f"⚠️ Impossible de prendre une capture d'écran : {e}")

        html = await page.content()
        html_path.write_text(html, encoding="utf-8")
        print(f"✅ HTML sauvegardé : {html_path} ({len(html)} caractères)")

        await browser.close()

    print("\n--- RÉSUMÉ ---")
    if status is None:
        print("⚠️ Aucune réponse reçue.")
    elif status >= 400:
        print(f"⚠️ Code {status} : possible blocage anti-bot ou erreur serveur.")
    elif "challenge" in title_final.lower() or "just a moment" in title_final.lower():
        print("⚠️ Toujours bloqué sur une page de challenge après attente.")
    else:
        print("✅ La page semble s'être chargée normalement (pas de challenge détecté).")
    print(f"Regarde en priorité : {screenshot_path}")
    print("Envoie-moi la capture d'écran + le code HTTP + le titre final affichés ci-dessus.")


if __name__ == "__main__":
    asyncio.run(main())
