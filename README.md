# CongoBet Scraper 🎯

Scraper Playwright async pour extraire les matchs et cotes de CongoBet,
avec pipeline de stockage SQLite et export pour moteur de pronostic IA.

## Installation

```bash
pip install playwright aiohttp
playwright install chromium
```

## Workflow recommandé

### Étape 1 — Inspecter la structure HTML du site
Lance d'abord l'inspector pour identifier les vrais sélecteurs CSS :

```bash
python inspector.py
```

Résultats dans :
- `/tmp/api_calls.json` — tous les appels API JSON interceptés
- `/tmp/dom_analysis.json` — classes CSS et data-attributes détectés

### Étape 2 — Adapter scraper.py
Dans `_extract_matches()`, remplace les sélecteurs génériques par ceux
trouvés par l'inspector. Si CongoBet expose une API JSON (très probable
pour un site SPA moderne), adapter `parse_api_response()` directement.

### Étape 3 — Lancer le pipeline

```bash
# Scrape unique
python pipeline.py --once

# Scrape en boucle toutes les 15 min
python pipeline.py --interval 15

# Exporter les données pour le pronostic
python pipeline.py --export ma_session.json
```

## Architecture

```
inspector.py     → Reverse-engineering de la structure du site
scraper.py       → Core scraper Playwright (extraire matchs + cotes)
pipeline.py      → Scheduler + SQLite + export JSON pronostic
```

## Structure JSON exportée

```json
{
  "exported_at": "2024-03-14T10:00:00",
  "total": 42,
  "matches": [
    {
      "id": "match_123",
      "league": "Premier League",
      "home": "Arsenal FC",
      "away": "Everton FC",
      "start_time": "2024-03-14T15:00:00",
      "markets": {
        "1X2": { "1": 1.35, "X": 4.20, "2": 7.50 },
        "BTTS": { "Oui": 1.70, "Non": 2.00 },
        "Over/Under": { ">2.5": 1.85, "<2.5": 1.90 }
      }
    }
  ]
}
```

## Anti-détection

- Headers HTTP réalistes (User-Agent, Accept-Language)
- Script init pour masquer `navigator.webdriver`
- Blocage des ressources inutiles (images, fonts) pour la vitesse
- Scroll simulé pour déclencher le lazy-loading

## Prochaine étape : Moteur de pronostic IA

Le fichier `/tmp/predictor_input.json` généré par le pipeline
est directement consommable par :
- Un modèle XGBoost entraîné sur les stats historiques
- L'API Claude pour l'analyse contextuelle
- Un modèle de Poisson pour la prédiction de buts
