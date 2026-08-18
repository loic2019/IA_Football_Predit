"""
inspector_pro.py — Inspector avancé pour sites de paris
================================================================================
- Reverse-engineering des structures HTML/API
- Détection automatique des patterns de données
- Support multi-sites (CongoBet, 1xBet, BeSoccer)
- Export des sélecteurs CSS pour scraper.py
- Analyse des appels API en temps réel
- Génération automatique des mappings
"""

import asyncio
import json
import sqlite3
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from collections import defaultdict
import time

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("⚠️ Playwright non installé. Installez: pip install playwright && playwright install")
    exit(1)

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    "sites": {
        "congobet": {
            "url": "https://www.congobet.net/sports",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
            "selectors": {}
        },
        "1xbet": {
            "url": "https://www.1xbet.com/fr/live/Football/",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
            "selectors": {}
        },
        "besoccer": {
            "url": "https://www.besoccer.com/competition/scores/veikkausliiga/2026",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
            "selectors": {}
        }
    },
    "output_dir": Path("inspector_output"),
    "db_path": Path("congobet.db"),
}

CONFIG["output_dir"].mkdir(exist_ok=True)

# ============================================================================
# CLASSES
# ============================================================================

class SiteInspector:
    """Inspecteur de site pour reverse-engineering."""
    
    def __init__(self, site_name: str, config: Dict):
        self.site_name = site_name
        self.config = config
        self.api_calls = []
        self.dom_analysis = {}
        self.selectors = {}
        self.browser = None
        self.context = None
        self.page = None
    
    async def setup(self):
        """Initialise le navigateur."""
        p = await async_playwright().start()
        self.browser = await p.chromium.launch(headless=False)
        
        site_config = CONFIG["sites"][self.site_name]
        self.context = await self.browser.new_context(
            viewport={"width": 1440, "height": 900},
            extra_http_headers={
                "User-Agent": site_config.get("user_agent", ""),
                "Accept-Language": "fr-FR,fr;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
        )
        self.page = await self.context.new_page()
        
        # Intercepter les requêtes
        self.page.on("response", self._capture_response)
        
        # Intercepter les requêtes API
        self.page.on("request", self._capture_request)
    
    async def teardown(self):
        """Ferme le navigateur."""
        if self.browser:
            await self.browser.close()
    
    async def _capture_response(self, response):
        """Capture les réponses JSON."""
        url = response.url
        content_type = response.headers.get("content-type", "")
        
        if "json" in content_type and response.status == 200:
            try:
                data = await response.json()
                self.api_calls.append({
                    "url": url,
                    "status": response.status,
                    "headers": dict(response.headers),
                    "data": data,
                    "timestamp": time.time()
                })
            except Exception:
                pass
    
    async def _capture_request(self, request):
        """Capture les requêtes."""
        if "api" in request.url.lower() or "json" in request.url.lower():
            pass  # Déjà capturé via les réponses
    
    async def navigate(self, url: str = None):
        """Navigue vers l'URL du site."""
        if not url:
            url = CONFIG["sites"][self.site_name]["url"]
        
        print(f"\n🌐 Chargement de {url}...")
        await self.page.goto(url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)  # Laisser le temps aux appels API
        
        # Défiler pour charger le contenu dynamique
        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(3)
        await self.page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(2)
    
    async def analyze_dom(self):
        """Analyse le DOM en profondeur."""
        print("\n🔍 Analyse du DOM...")
        
        self.dom_analysis = await self.page.evaluate("""
        () => {
            const report = {
                // 1. Classes CSS
                all_classes: [],
                sport_classes: [],
                
                // 2. Data attributes
                data_attributes: [],
                
                // 3. Structure générale
                structure: {
                    total_elements: document.querySelectorAll('*').length,
                    unique_classes: new Set(),
                    unique_ids: new Set(),
                },
                
                // 4. Sélecteurs candidats
                candidates: {},
                
                // 5. Échantillons DOM
                samples: {},
                
                // 6. Formulaires et inputs
                forms: [],
                
                // 7. Liens et navigation
                links: [],
                
                // 8. Scripts et données JSON
                scripts: []
            };
            
            // 1. Classes CSS
            const sportKeywords = ['match', 'event', 'sport', 'game', 'team',
                'odd', 'price', 'coef', 'bet', 'league', 'competition',
                'market', 'selection', 'fixture', 'score', 'live', 'football',
                'soccer', 'tennis', 'basketball', 'cote', 'paris', 'pronostic'];
            
            document.querySelectorAll('*').forEach(el => {
                el.classList.forEach(c => {
                    report.structure.unique_classes.add(c);
                    if (sportKeywords.some(kw => c.toLowerCase().includes(kw))) {
                        report.sport_classes.push(c);
                    }
                });
                if (el.id) {
                    report.structure.unique_ids.add(el.id);
                }
            });
            
            // 2. Data attributes
            document.querySelectorAll('[data-*]').forEach(el => {
                [...el.attributes].forEach(attr => {
                    if (attr.name.startsWith('data-')) {
                        report.data_attributes.push(attr.name);
                    }
                });
            });
            
            // 3. Sélecteurs candidats
            const candidates = [
                '[class*="event"]', '[class*="match"]', '[class*="fixture"]',
                '[class*="game"]', '[class*="sport"]', '[data-event-id]',
                '[data-match-id]', '[data-id]', 'tr[id]', '.row', '.item',
                '[class*="odd"]', '[class*="cote"]', '[class*="price"]',
                '[class*="bet"]', '[class*="market"]', '[class*="selection"]'
            ];
            
            for (const sel of candidates) {
                try {
                    const elements = document.querySelectorAll(sel);
                    report.candidates[sel] = {
                        count: elements.length,
                        first: elements[0] ? {
                            tag: elements[0].tagName,
                            classes: elements[0].className,
                            text: elements[0].textContent?.slice(0, 100).trim(),
                            html: elements[0].outerHTML?.slice(0, 300)
                        } : null
                    };
                } catch (e) {
                    report.candidates[sel] = { count: 0, error: e.message };
                }
            }
            
            // 4. Échantillons DOM (structures communes)
            const sampleSelectors = ['div', 'tr', 'li', '.row', '.item', '[role="row"]'];
            for (const sel of sampleSelectors) {
                const el = document.querySelector(sel);
                if (el && el.children.length > 0) {
                    const children = [...el.children].map(child => ({
                        tag: child.tagName,
                        classes: child.className,
                        id: child.id
                    }));
                    report.samples[sel] = {
                        tag: el.tagName,
                        classes: el.className,
                        children_count: el.children.length,
                        children_structure: children.slice(0, 5),
                        text_sample: el.textContent?.slice(0, 200).trim()
                    };
                }
            }
            
            // 5. Forms
            document.querySelectorAll('form').forEach(f => {
                report.forms.push({
                    action: f.action,
                    method: f.method,
                    inputs: [...f.querySelectorAll('input')].map(i => ({
                        name: i.name,
                        type: i.type,
                        value: i.value
                    }))
                });
            });
            
            // 6. Scripts JSON
            document.querySelectorAll('script[type="application/json"]').forEach(script => {
                try {
                    const data = JSON.parse(script.textContent);
                    report.scripts.push({
                        type: 'json',
                        preview: JSON.stringify(data).slice(0, 200)
                    });
                } catch (e) {}
            });
            
            return report;
        }
        """)
        
        # Nettoyer les données
        self.dom_analysis["sport_classes"] = list(set(self.dom_analysis.get("sport_classes", [])))
        self.dom_analysis["data_attributes"] = list(set(self.dom_analysis.get("data_attributes", [])))
        
        print(f"   ✅ {len(self.dom_analysis.get('sport_classes', []))} classes sportives trouvées")
        print(f"   ✅ {len(self.dom_analysis.get('data_attributes', []))} data-attributes trouvés")
    
    async def detect_api_patterns(self):
        """Détecte les patterns d'API."""
        print("\n📡 Analyse des appels API...")
        
        patterns = {
            "events": [],
            "odds": [],
            "matches": [],
            "live": [],
            "statistics": [],
        }
        
        for call in self.api_calls:
            url = call["url"]
            data = call.get("data", {})
            
            # Détecter les patterns
            if "event" in url.lower() or "match" in url.lower():
                patterns["matches"].append(url)
            if "odd" in url.lower() or "price" in url.lower():
                patterns["odds"].append(url)
            if "live" in url.lower() or "inplay" in url.lower():
                patterns["live"].append(url)
            if "stat" in url.lower() or "analysis" in url.lower():
                patterns["statistics"].append(url)
            if "event" in url.lower() or "fixture" in url.lower():
                patterns["events"].append(url)
        
        # Résumé
        for key, urls in patterns.items():
            if urls:
                print(f"   📍 {key}: {len(urls)} appels")
                for url in urls[:3]:
                    print(f"      • {url[:80]}...")
        
        return patterns
    
    async def extract_selectors(self):
        """Extrait les sélecteurs CSS pertinents."""
        print("\n🎯 Extraction des sélecteurs...")
        
        selectors = {
            "matches": [],
            "odds": [],
            "teams": [],
            "scores": [],
            "leagues": [],
            "markets": [],
        }
        
        # Analyser les classes sportives
        for cls in self.dom_analysis.get("sport_classes", []):
            lower_cls = cls.lower()
            if "match" in lower_cls or "event" in lower_cls or "fixture" in lower_cls:
                selectors["matches"].append(f".{cls}")
            if "odd" in lower_cls or "price" in lower_cls or "cote" in lower_cls:
                selectors["odds"].append(f".{cls}")
            if "team" in lower_cls:
                selectors["teams"].append(f".{cls}")
            if "score" in lower_cls:
                selectors["scores"].append(f".{cls}")
            if "league" in lower_cls or "competition" in lower_cls:
                selectors["leagues"].append(f".{cls}")
            if "market" in lower_cls or "selection" in lower_cls:
                selectors["markets"].append(f".{cls}")
        
        # Ajouter les data-attributes
        for attr in self.dom_analysis.get("data_attributes", []):
            if "event" in attr.lower() or "match" in attr.lower():
                selectors["matches"].append(f"[{attr}]")
            if "odd" in attr.lower() or "price" in attr.lower():
                selectors["odds"].append(f"[{attr}]")
        
        # Nettoyer
        for key in selectors:
            selectors[key] = list(set(selectors[key]))
            print(f"   {key}: {len(selectors[key])} sélecteurs")
        
        self.selectors = selectors
        return selectors
    
    async def generate_scraper_config(self):
        """Génère une configuration pour scraper.py."""
        print("\n📝 Génération de la configuration...")
        
        config = {
            "site": self.site_name,
            "url": CONFIG["sites"][self.site_name]["url"],
            "selectors": self.selectors,
            "api_endpoints": [],
            "data_mapping": {},
            "generated_at": datetime.now().isoformat()
        }
        
        # Ajouter les endpoints API
        for call in self.api_calls:
            if "json" in call.get("headers", {}).get("content-type", ""):
                config["api_endpoints"].append({
                    "url": call["url"],
                    "method": "GET",
                    "sample": call.get("data", {}).keys() if isinstance(call.get("data"), dict) else []
                })
        
        # Mapping des données
        config["data_mapping"] = {
            "match_id": ["data-event-id", "data-match-id", "id"],
            "home_team": ["class*='home'", "class*='team-home'", "data-home"],
            "away_team": ["class*='away'", "class*='team-away'", "data-away"],
            "home_score": ["class*='score-home'", "data-home-score"],
            "away_score": ["class*='score-away'", "data-away-score"],
            "odds_1": ["class*='odd-1'", "data-odd-1"],
            "odds_X": ["class*='odd-x'", "data-odd-x"],
            "odds_2": ["class*='odd-2'", "data-odd-2"],
        }
        
        # Sauvegarder
        output_file = CONFIG["output_dir"] / f"scraper_config_{self.site_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print(f"   ✅ Configuration sauvegardée: {output_file}")
        
        return config
    
    async def run(self):
        """Exécute l'inspection complète."""
        print(f"\n{'='*60}")
        print(f"🔍 INSPECTION DE {self.site_name.upper()}")
        print(f"{'='*60}")
        
        await self.setup()
        
        try:
            await self.navigate()
            await self.analyze_dom()
            await self.detect_api_patterns()
            await self.extract_selectors()
            config = await self.generate_scraper_config()
            
            # Résumé
            print(f"\n{'='*60}")
            print("📊 RÉSUMÉ DE L'INSPECTION")
            print(f"{'='*60}")
            print(f"   Site: {self.site_name}")
            print(f"   API calls: {len(self.api_calls)}")
            print(f"   Classes sportives: {len(self.dom_analysis.get('sport_classes', []))}")
            print(f"   Data-attributes: {len(self.dom_analysis.get('data_attributes', []))}")
            print(f"   Sélecteurs matches: {len(self.selectors.get('matches', []))}")
            print(f"   Sélecteurs cotes: {len(self.selectors.get('odds', []))}")
            
            # Sauvegarder le rapport complet
            report_file = CONFIG["output_dir"] / f"inspection_{self.site_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            report = {
                "site": self.site_name,
                "timestamp": datetime.now().isoformat(),
                "api_calls": self.api_calls,
                "dom_analysis": self.dom_analysis,
                "selectors": self.selectors,
                "config": config
            }
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2, default=str)
            print(f"\n💾 Rapport complet: {report_file}")
            
            print("\n⏸  Navigateur ouvert pour inspection manuelle.")
            print("   Appuie sur Entrée pour fermer...")
            input()
            
        except Exception as e:
            print(f"❌ Erreur: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await self.teardown()


# ============================================================================
# ANALYSE DE BASE DE DONNÉES
# ============================================================================

def analyze_database(db_path: Path = CONFIG["db_path"]) -> Dict:
    """Analyse la base de données existante pour comprendre la structure."""
    if not db_path.exists():
        return {"error": "Base de données non trouvée"}
    
    result = {
        "tables": [],
        "schemas": {},
        "stats": {}
    }
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Lister les tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    for table in tables:
        table_name = table[0]
        result["tables"].append(table_name)
        
        # Schéma de la table
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        result["schemas"][table_name] = [
            {"name": col[1], "type": col[2], "nullable": not col[3], "default": col[4]}
            for col in columns
        ]
        
        # Statistiques
        try:
            count = cursor.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            result["stats"][table_name] = {"rows": count}
        except:
            pass
    
    conn.close()
    return result


# ============================================================================
# GÉNÉRATION DE SCRAPER
# ============================================================================

def generate_scraper_from_config(config_path: Path, output_path: Path = Path("scraper_generated.py")):
    """Génère un scraper à partir de la configuration."""
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    
    selectors = config.get("selectors", {})
    
    scraper_code = f'''
"""
scraper_generated.py — Scraper généré automatiquement pour {config.get("site", "unknown")}
================================================================================
Généré le {config.get("generated_at", "unknown")}
À adapter manuellement si nécessaire.
"""

import requests
from bs4 import BeautifulSoup
import time
import json
from pathlib import Path

URL = "{config.get("url", "")}"

HEADERS = {{
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
    "Accept-Language": "fr-FR,fr;q=0.9",
}}

# Sélecteurs détectés
SELECTORS = {{
    "matches": {json.dumps(selectors.get("matches", []), indent=4)},
    "odds": {json.dumps(selectors.get("odds", []), indent=4)},
    "teams": {json.dumps(selectors.get("teams", []), indent=4)},
    "scores": {json.dumps(selectors.get("scores", []), indent=4)},
    "leagues": {json.dumps(selectors.get("leagues", []), indent=4)},
}}


def scrape_matches():
    """Scrape les matchs depuis le site."""
    response = requests.get(URL, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    matches = []
    
    # À adapter avec les vrais sélecteurs
    for selector in SELECTORS["matches"]:
        elements = soup.select(selector)
        for el in elements:
            # Extraire les données
            match = {{
                "home": "",
                "away": "",
                "home_score": None,
                "away_score": None,
                "odd_1": None,
                "odd_X": None,
                "odd_2": None,
            }}
            # Ajouter la logique d'extraction ici
            matches.append(match)
    
    return matches


if __name__ == "__main__":
    matches = scrape_matches()
    print(json.dumps(matches, ensure_ascii=False, indent=2))
'''
    
    output_path.write_text(scraper_code, encoding="utf-8")
    print(f"✅ Scraper généré: {output_path}")


# ============================================================================
# MAIN
# ============================================================================

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Inspector Pro pour sites de paris"
    )
    parser.add_argument("--site", type=str, choices=["congobet", "1xbet", "besoccer"], 
                       default="congobet", help="Site à inspecter")
    parser.add_argument("--analyze-db", action="store_true", 
                       help="Analyser la base de données existante")
    parser.add_argument("--generate", type=str, 
                       help="Générer un scraper depuis une config")
    parser.add_argument("--url", type=str, 
                       help="URL personnalisée (override)")
    
    args = parser.parse_args()
    
    if args.analyze_db:
        db_analysis = analyze_database()
        print("\n📊 Analyse de la base de données:")
        for table, info in db_analysis.items():
            if table == "tables":
                print(f"   Tables: {', '.join(info)}")
            elif table == "stats":
                for t, stats in info.items():
                    print(f"   {t}: {stats['rows']} lignes")
        return
    
    if args.generate:
        generate_scraper_from_config(Path(args.generate))
        return
    
    # Inspection du site
    inspector = SiteInspector(args.site, CONFIG)
    
    if args.url:
        CONFIG["sites"][args.site]["url"] = args.url
    
    await inspector.run()


if __name__ == "__main__":
    asyncio.run(main())