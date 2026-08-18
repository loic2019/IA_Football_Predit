# -*- coding: utf-8 -*-
"""
debug_tools/diag_besoccer.py — Diagnostic v2 (contournements anti-bot)
================================================================================
v1 a reçu un 406 Not Acceptable de besoccer.com : le WAF du site détecte
Playwright comme navigateur automatisé et bloque avant de servir le contenu.
Cette v2 ajoute 2 contournements classiques :
1. --disable-blink-features=AutomationControlled : masque le flag
   navigator.webdriver que beaucoup de systèmes anti-bot vérifient.
2. En-têtes HTTP complets (Accept, Accept-Language, sec-ch-ua...) : un vrai
   navigateur envoie toujours ces en-têtes, Playwright par défaut en envoie
   une version minimaliste qui peut trahir l'automatisation.

Lancement :
    python debug_tools/diag_besoccer.py
"""

from pathlib import Path
from datetime import datetime

OUT_DIR = Path("logs")
OUT_DIR.mkdir(exist_ok=True)

URL = "https://www.besoccer.com/competition/scores/veikkausliiga/2026"


def main():
    from playwright.sync_api import sync_playwright

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "sec-ch-ua": '"Chromium";v="124", "Not(A:Brand";v="24", "Google Chrome";v="124"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "Upgrade-Insecure-Requests": "1",
            },
        )
        # Masque le flag navigator.webdriver AVANT que la page ne charge du JS
        # qui pourrait le vérifier.
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        page = context.new_page()

        print(f"→ Navigation vers {URL} ...")
        try:
            response = page.goto(URL, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"❌ page.goto a levé une exception : {e}")
            browser.close()
            return

        print(f"✅ Code HTTP de la réponse : {response.status if response else 'AUCUNE RÉPONSE (response=None)'}")
        print(f"✅ URL finale : {page.url}")

        page.wait_for_timeout(3000)

        print(f"✅ Titre de la page : {page.title()!r}")

        screenshot_path = OUT_DIR / f"besoccer_diag_v2_{ts}.png"
        html_path = OUT_DIR / f"besoccer_diag_v2_{ts}.html"
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"✅ Capture d'écran sauvegardée : {screenshot_path}")
        except Exception as e:
            print(f"⚠️ Impossible de prendre une capture d'écran : {e}")

        html = page.content()
        html_path.write_text(html, encoding="utf-8")
        print(f"✅ HTML sauvegardé : {html_path} ({len(html)} caractères)")

        browser.close()

    print("\n--- RÉSUMÉ ---")
    print(f"Regarde en priorité : {screenshot_path}")
    print("Envoie-moi la capture d'écran + le code HTTP + la taille du HTML affichés ci-dessus.")


if __name__ == "__main__":
    main()
