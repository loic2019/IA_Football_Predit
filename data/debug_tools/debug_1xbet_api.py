"""
Debug: identifier les endpoints JSON utilisés par 1xBet.

But:
  - ouvrir une page 1xBet en Playwright
  - écouter les réponses réseau
  - sauvegarder les réponses JSON probables (odds/markets/events) dans un fichier

Lance:
  env\Scripts\python.exe debug_1xbet_api.py
"""

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


URL = "https://1xbet.cg/fr/live/football/209499-china-second-league"
OUT_JSONL = Path("1xbet_debug_responses.jsonl")

JSON_PATTERNS = [
    "odds",
    "1x2",
    "market",
    "markets",
    "event",
    "events",
    "line",
    "prices",
    "selection",
    "football",
]


async def main():
    OUT_JSONL.unlink(missing_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        found = {"count": 0, "urls": []}

        async def on_response(resp):
            try:
                u = resp.url.lower()
            except Exception:
                return

            if not any(k in u for k in JSON_PATTERNS):
                return

            ctype = (resp.headers or {}).get("content-type", "")
            if "application/json" not in ctype and "json" not in u:
                # Certains endpoints renvoient du JSON sans header clair
                # On tente quand même.
                pass

            try:
                data = await resp.json()
            except Exception:
                return

            found["count"] += 1
            found["urls"].append(resp.url)

            record = {
                "url": resp.url,
                "status": resp.status,
                "content_type": ctype,
                "data_type": type(data).__name__,
            }
            with OUT_JSONL.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"meta": record, "data": data}, ensure_ascii=False) + "\n")

            # Stop après quelques réponses pour éviter explosion
            if found["count"] >= 15:
                return

        page.on("response", on_response)

        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        # Laisse le temps aux requêtes XHR/fetch de partir
        await page.wait_for_timeout(20000)

        await browser.close()

    print(f"Debug terminée. JSON sauvegardées dans: {OUT_JSONL}")
    print(f"Nombre endpoints capturés: {found['count']}")
    for u in found["urls"][:10]:
        print(" -", u)


if __name__ == "__main__":
    asyncio.run(main())

