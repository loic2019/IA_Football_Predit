"""
results_importer_pro.py — Import avancé de résultats historiques
================================================================================
- Support multi-formats (JSON, CSV, Excel, API)
- Auto-matching intelligent des matchs
- Calcul des statistiques pour le Deep Learning
- Mise à jour automatique des features
- Import en streaming pour fichiers volumineux
- Validation et détection d'anomalies
- Export des rapports d'import

Usage:
    python results_importer_pro.py --file historical_results.json
    python results_importer_pro.py --file results_2024.csv --batch-size 10000
    python results_importer_pro.py --api --league PL --season 2024
    python results_importer_pro.py --folder ./results_folder/
    python results_importer_pro.py --auto-detect
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

import argparse
import csv
import json
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import re
import time
from tqdm import tqdm
import requests

# ============================================================================
# CONFIGURATION
# ============================================================================

DB_PATH = Path("congobet.db")
IMPORT_LOG_DIR = Path("import_logs")
IMPORT_LOG_DIR.mkdir(exist_ok=True)

CONFIG = {
    "batch_size": 5000,
    "auto_match_threshold": 0.8,
    "validate_scores": True,
    "update_stats": True,
    "generate_features": True,
    "log_imports": True,
    "api_key": "fe50fdb0b9074d04b5533deaafbfe099",
}

# ============================================================================
# CLASSES
# ============================================================================

class ResultsImporterPro:
    """Importateur avancé de résultats historiques."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = None
        self.import_stats = {
            "total": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "unmatched": 0
        }
        self.log_file = None
        
        # Initialiser la base
        self.init_database()
    
    def init_database(self):
        """Initialise la base avec les tables nécessaires.

        CORRECTIF : cette méthode plantait dès l'instanciation de la classe
        contre le VRAI congobet.db de production (celui de scraper_api.py),
        qui existe déjà avec un schéma différent (pas de colonnes status,
        timestamp, season_id, matchday, home_xg, away_xg, home_strength,
        away_strength, updated_at, source). `CREATE TABLE IF NOT EXISTS`
        est un no-op sur une table déjà existante — les colonnes
        manquantes n'étaient donc JAMAIS ajoutées, et le premier
        `CREATE INDEX ... ON matches(timestamp)` plantait immédiatement
        avec `sqlite3.OperationalError: no such column: timestamp`.
        Reproduit et vérifié avant correction (pas une supposition).

        On applique maintenant la même migration additive que
        scraper_api.py::init_db (ALTER TABLE ADD COLUMN au cas par cas),
        pour que ce script reste compatible qu'il tourne sur une base
        neuve OU sur le vrai congobet.db déjà rempli par les scrapers.
        """
        conn = sqlite3.connect(self.db_path)

        # Table neuve (no-op si `matches` existe déjà avec un autre schéma —
        # c'est le cas normal en production)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY,
                league TEXT,
                country TEXT,
                home_team TEXT,
                away_team TEXT,
                home_score INTEGER,
                away_score INTEGER,
                result TEXT,
                start_time TEXT,
                status TEXT,
                timestamp INTEGER,
                season_id INTEGER,
                matchday INTEGER,
                home_xg REAL,
                away_xg REAL,
                home_strength REAL,
                away_strength REAL,
                scraped_at TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migration additive : ajoute les colonnes manquantes sans jamais
        # toucher aux données existantes (mêmes garanties que
        # scraper_api.py::init_db pour la table `matches` de production).
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(matches)").fetchall()}
        required_cols = {
            "status": "TEXT", "timestamp": "INTEGER", "season_id": "INTEGER",
            "matchday": "INTEGER", "home_xg": "REAL", "away_xg": "REAL",
            "home_strength": "REAL", "away_strength": "REAL",
            "updated_at": "TEXT", "source": "TEXT",
        }
        for col, col_type in required_cols.items():
            if col not in existing_cols:
                try:
                    conn.execute(f"ALTER TABLE matches ADD COLUMN {col} {col_type}")
                except Exception as e:
                    print(f"⚠️ Impossible d'ajouter la colonne {col}: {e}")
        conn.commit()

        # Table d'historique des imports
        conn.execute("""
            CREATE TABLE IF NOT EXISTS import_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                file_name TEXT,
                total_records INTEGER,
                inserted INTEGER,
                updated INTEGER,
                skipped INTEGER,
                errors INTEGER,
                unmatched INTEGER,
                import_date TEXT DEFAULT CURRENT_TIMESTAMP,
                duration REAL
            )
        """)
        
        # Table des logs d'import
        conn.execute("""
            CREATE TABLE IF NOT EXISTS import_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_id INTEGER,
                match_id TEXT,
                action TEXT,
                message TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Index (maintenant sûrs : les colonnes ci-dessus existent forcément
        # à ce stade, qu'on parte d'une base neuve ou de la vraie base de prod)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_timestamp ON matches(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_result ON matches(result)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_teams ON matches(home_team, away_team)")
        
        conn.commit()
        conn.close()
        
        print("✅ Base de données initialisée")
    
    def connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
    
    def close(self):
        if self.conn:
            self.conn.close()
    
    # ========================================================================
    # 1. CHARGEMENT DES DONNÉES
    # ========================================================================
    
    def load_file(self, file_path: Path) -> List[Dict]:
        """Charge un fichier (JSON, CSV, Excel)."""
        if not file_path.exists():
            raise FileNotFoundError(f"Fichier introuvable: {file_path}")
        
        ext = file_path.suffix.lower()
        
        if ext == '.json':
            return self.load_json(file_path)
        elif ext == '.csv':
            return self.load_csv(file_path)
        elif ext in ['.xlsx', '.xls']:
            return self.load_excel(file_path)
        else:
            raise ValueError(f"Format non supporté: {ext}")
    
    def load_json(self, file_path: Path) -> List[Dict]:
        """Charge un fichier JSON."""
        with open(file_path, encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # Chercher la clé qui contient les résultats
            for key in ['results', 'matches', 'data', 'items']:
                if key in data and isinstance(data[key], list):
                    return data[key]
            # Si pas trouvé, retourner le dict entier
            return [data]
        return []
    
    def load_csv(self, file_path: Path) -> List[Dict]:
        """Charge un fichier CSV."""
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        return df.to_dict('records')
    
    def load_excel(self, file_path: Path) -> List[Dict]:
        """Charge un fichier Excel."""
        df = pd.read_excel(file_path)
        return df.to_dict('records')
    
    def load_from_api(self, competition_id: str, season: int) -> List[Dict]:
        """Charge les résultats depuis l'API Football-Data.org."""
        print(f"📡 Récupération des résultats depuis l'API...")
        
        matches = []
        for matchday in range(1, 39):  # Max 38 journées
            try:
                url = f"https://api.football-data.org/v4/competitions/{competition_id}/matches"
                params = {
                    'season': season,
                    'matchday': matchday,
                    'status': 'FINISHED'
                }
                headers = {'X-Auth-Token': CONFIG['api_key']}
                
                response = requests.get(url, params=params, headers=headers)
                if response.status_code != 200:
                    continue
                
                data = response.json()
                for match in data.get('matches', []):
                    if match.get('status') == 'FINISHED':
                        score = match.get('score', {}).get('fullTime', {})
                        matches.append({
                            'id': f"api_{match.get('id')}",
                            'home': match.get('homeTeam', {}).get('name', ''),
                            'away': match.get('awayTeam', {}).get('name', ''),
                            'home_score': score.get('home'),
                            'away_score': score.get('away'),
                            'date': match.get('utcDate', '')[:10],
                            'league': match.get('competition', {}).get('name', ''),
                            'season': season,
                            'matchday': matchday
                        })
                
                print(f"   ✅ Journée {matchday}: {len(matches)} matchs")
                time.sleep(1)  # Respecter les limites API
                
            except Exception as e:
                print(f"   ⚠️ Erreur matchday {matchday}: {e}")
                continue
        
        return matches
    
    # ========================================================================
    # 2. NORMALISATION DES DONNÉES
    # ========================================================================
    
    def normalize_match(self, item: Dict) -> Dict:
        """Normalise un match pour l'import."""
        normalized = {}
        
        # ID
        normalized['id'] = self.get_id(item)
        
        # Équipes
        normalized['home_team'] = self.normalize_team_name(item.get('home', item.get('home_team', '')))
        normalized['away_team'] = self.normalize_team_name(item.get('away', item.get('away_team', '')))
        
        # Scores
        home_score = item.get('home_score', item.get('score_home'))
        away_score = item.get('away_score', item.get('score_away'))
        normalized['home_score'] = self.normalize_score(home_score)
        normalized['away_score'] = self.normalize_score(away_score)
        
        # Résultat
        if 'result' in item:
            result = str(item['result']).strip().upper()
            normalized['result'] = result if result in ['1', 'X', '2'] else None
        else:
            normalized['result'] = self.calculate_result(
                normalized['home_score'], 
                normalized['away_score']
            )
        
        # Date
        normalized['start_time'] = self.normalize_date(item.get('date', item.get('start_time', '')))
        
        # Métadonnées
        normalized['league'] = str(item.get('league', item.get('competition', ''))).strip()
        normalized['season'] = item.get('season', item.get('season_id'))
        normalized['matchday'] = item.get('matchday', item.get('journee'))
        normalized['status'] = 'FINISHED'
        
        return normalized
    
    def get_id(self, item: Dict) -> str:
        """Génère un ID unique pour le match."""
        # Si un ID existe déjà
        if 'id' in item and item['id']:
            return str(item['id'])
        
        # Générer un ID à partir des équipes et de la date
        home = self.normalize_team_name(item.get('home', item.get('home_team', '')))
        away = self.normalize_team_name(item.get('away', item.get('away_team', '')))
        date = self.normalize_date(item.get('date', item.get('start_time', '')))
        
        if home and away and date:
            # Créer un ID unique
            import hashlib
            raw = f"{home}_{away}_{date}"
            hash_id = hashlib.md5(raw.encode()).hexdigest()[:12]
            return f"import_{hash_id}"
        
        # Fallback: ID aléatoire
        import uuid
        return f"import_{uuid.uuid4().hex[:12]}"
    
    def normalize_team_name(self, name: str) -> str:
        """Normalise le nom d'une équipe."""
        if not name:
            return ""
        
        name = str(name).strip()
        
        # Supprimer les accents
        import unicodedata
        name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ASCII')
        
        # Nettoyer
        name = re.sub(r'\s+', ' ', name)
        name = name.replace(' FC', '').replace(' SC', '').replace(' AS', '').strip()
        
        return name
    
    def normalize_score(self, score: Any) -> Optional[int]:
        """Normalise un score. Rejette les valeurs négatives (Partie H :
        "validation du score") — un score de foot n'est jamais négatif ;
        accepter '-1' silencieusement produirait une ligne invalide sans
        que personne ne le remarque."""
        if score is None or score == '' or score == 'null':
            return None
        try:
            value = int(score)
        except Exception:
            return None
        return value if value >= 0 else None
    
    def normalize_date(self, date: str) -> Optional[str]:
        """Normalise une date."""
        if not date:
            return None
        
        date_str = str(date).strip()
        
        # Patterns de dates
        patterns = [
            (r'(\d{4})-(\d{2})-(\d{2})', '%Y-%m-%d'),
            (r'(\d{2})/(\d{2})/(\d{4})', '%d/%m/%Y'),
            (r'(\d{2})\.(\d{2})\.(\d{4})', '%d.%m.%Y'),
            (r'(\d{2})-(\d{2})-(\d{4})', '%d-%m-%Y'),
        ]
        
        for pattern, fmt in patterns:
            match = re.match(pattern, date_str)
            if match:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return dt.strftime('%Y-%m-%d')
                except:
                    continue
        
        # ISO complet
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00').replace('T', ' '))
            return dt.strftime('%Y-%m-%d')
        except:
            pass
        
        return None
    
    def calculate_result(self, home_score: Optional[int], away_score: Optional[int]) -> Optional[str]:
        """Calcule le résultat à partir des scores."""
        if home_score is None or away_score is None:
            return None
        
        if home_score > away_score:
            return '1'
        elif home_score < away_score:
            return '2'
        else:
            return 'X'
    
    # ========================================================================
    # 3. MATCHING
    # ========================================================================
    
    def find_match(self, match: Dict) -> Optional[str]:
        """Trouve un match existant dans la base."""
        if not match.get('home_team') or not match.get('away_team'):
            return None
        
        # 1. Recherche par ID
        if match.get('id'):
            row = self.conn.execute(
                "SELECT id FROM matches WHERE id = ?",
                (match['id'],)
            ).fetchone()
            if row:
                return row[0]
        
        # 2. Recherche par équipes + date
        if match.get('start_time'):
            row = self.conn.execute("""
                SELECT id FROM matches 
                WHERE LOWER(TRIM(home_team)) = LOWER(TRIM(?))
                AND LOWER(TRIM(away_team)) = LOWER(TRIM(?))
                AND DATE(start_time) = DATE(?)
                ORDER BY updated_at DESC
                LIMIT 1
            """, (match['home_team'], match['away_team'], match['start_time'])).fetchone()
            if row:
                return row[0]
        
        # 3. Recherche par équipes seulement (moins précis)
        row = self.conn.execute("""
            SELECT id FROM matches 
            WHERE LOWER(TRIM(home_team)) = LOWER(TRIM(?))
            AND LOWER(TRIM(away_team)) = LOWER(TRIM(?))
            ORDER BY updated_at DESC
            LIMIT 1
        """, (match['home_team'], match['away_team'])).fetchone()
        if row:
            return row[0]
        
        return None
    
    # ========================================================================
    # 4. IMPORT
    # ========================================================================
    
    def import_matches(self, matches: List[Dict], source: str = "file") -> Dict:
        """Importe une liste de matchs."""
        print(f"\n📥 Import de {len(matches)} matchs...")
        
        self.connect()
        
        # Compteurs
        stats = {
            "total": len(matches),
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "unmatched": 0,
            "future_date_skipped": 0,  # Partie H : un import "historique" ne doit jamais
                                        # avaler un match encore à venir (voir Partie F)
        }
        
        start_time = time.time()
        today = datetime.now().strftime("%Y-%m-%d")
        
        for item in tqdm(matches, desc="Import"):
            try:
                # Normaliser
                match = self.normalize_match(item)
                
                # Vérifier les données minimales
                if not match.get('home_team') or not match.get('away_team'):
                    stats['skipped'] += 1
                    continue
                
                if match.get('home_score') is None and match.get('away_score') is None:
                    stats['skipped'] += 1
                    continue

                # Un match "historique" avec une date future n'a pas de sens :
                # soit la date est mal formée, soit ce n'est pas un match
                # terminé — dans les deux cas, on ne l'insère pas en silence.
                if match.get('start_time') and match['start_time'] > today:
                    stats['future_date_skipped'] += 1
                    continue
                
                # Trouver le match existant
                existing_id = self.find_match(match)
                
                if existing_id:
                    # Mise à jour
                    self.update_match(existing_id, match, source=source)
                    stats['updated'] += 1
                else:
                    # Insertion
                    self.insert_match(match, source=source)
                    stats['inserted'] += 1
                
            except Exception as e:
                stats['errors'] += 1
                print(f"   ❌ Erreur: {e}")
                continue
        
        duration = time.time() - start_time
        
        # Log
        self.log_import(source, stats, duration)
        
        self.close()
        
        return stats
    
    def insert_match(self, match: Dict, source: str = "MANUAL"):
        """Insère un nouveau match. `source` reste sur la ligne elle-même
        (colonne matches.source, ajoutée par la migration ci-dessus) — pas
        seulement dans le journal import_history — pour que la provenance
        (Partie H : "les données manuelles doivent rester identifiables")
        soit vérifiable directement sur le match, pas seulement dans un log
        séparé qu'on peut perdre de vue."""
        self.conn.execute("""
            INSERT INTO matches (
                id, league, home_team, away_team,
                home_score, away_score, result,
                start_time, status, scraped_at, updated_at, source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,?)
        """, (
            match.get('id'),
            match.get('league', ''),
            match['home_team'],
            match['away_team'],
            match.get('home_score'),
            match.get('away_score'),
            match.get('result'),
            match.get('start_time'),
            'FINISHED',
            datetime.now().isoformat(),
            source,
        ))
        self.conn.commit()
    
    def update_match(self, match_id: str, match: Dict, source: str = "MANUAL"):
        """Met à jour un match existant."""
        # Ne mettre à jour que si les scores sont différents
        current = self.conn.execute(
            "SELECT home_score, away_score, result FROM matches WHERE id = ?",
            (match_id,)
        ).fetchone()
        
        if current:
            current_home = current[0]
            current_away = current[1]
            
            # Si les scores sont les mêmes, ne pas mettre à jour
            if (current_home == match.get('home_score') and 
                current_away == match.get('away_score')):
                return
        
        self.conn.execute("""
            UPDATE matches 
            SET home_score = COALESCE(?, home_score),
                away_score = COALESCE(?, away_score),
                result = COALESCE(?, result),
                status = 'FINISHED',
                updated_at = CURRENT_TIMESTAMP,
                source = ?
            WHERE id = ?
        """, (
            match.get('home_score'),
            match.get('away_score'),
            match.get('result'),
            source,
            match_id
        ))
        self.conn.commit()
    
    # ========================================================================
    # 5. LOGGING
    # ========================================================================
    
    def log_import(self, source: str, stats: Dict, duration: float):
        """Enregistre l'import dans l'historique."""
        conn = sqlite3.connect(self.db_path)
        
        conn.execute("""
            INSERT INTO import_history (
                source, total_records, inserted, updated,
                skipped, errors, unmatched, duration
            ) VALUES (?,?,?,?,?,?,?,?)
        """, (
            source,
            stats['total'],
            stats['inserted'],
            stats['updated'],
            stats['skipped'],
            stats['errors'],
            stats.get('unmatched', 0),
            duration
        ))
        
        conn.commit()
        conn.close()
    
    def get_import_history(self, limit: int = 10) -> List[Dict]:
        """Récupère l'historique des imports."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        rows = conn.execute("""
            SELECT * FROM import_history
            ORDER BY import_date DESC
            LIMIT ?
        """, (limit,)).fetchall()
        
        conn.close()
        return [dict(row) for row in rows]
    
    # ========================================================================
    # 6. STATISTIQUES
    # ========================================================================
    
    def compute_team_stats(self):
        """Calcule les statistiques des équipes pour le Deep Learning."""
        print("\n📊 Calcul des statistiques des équipes...")
        
        self.connect()
        
        # Récupérer tous les matchs
        rows = self.conn.execute("""
            SELECT home_team, away_team, home_score, away_score, result
            FROM matches
            WHERE home_score IS NOT NULL AND away_score IS NOT NULL
        """).fetchall()
        
        if not rows:
            print("   ⚠️ Aucun match avec scores")
            self.close()
            return
        
        team_stats = defaultdict(lambda: {
            'matches': 0,
            'wins': 0,
            'draws': 0,
            'losses': 0,
            'goals_for': 0,
            'goals_against': 0,
            'points': 0
        })
        
        for row in rows:
            home, away, home_score, away_score, result = row
            
            # Équipe domicile
            team_stats[home]['matches'] += 1
            team_stats[home]['goals_for'] += home_score
            team_stats[home]['goals_against'] += away_score
            
            # Équipe extérieur
            team_stats[away]['matches'] += 1
            team_stats[away]['goals_for'] += away_score
            team_stats[away]['goals_against'] += home_score
            
            # Résultat
            if result == '1':
                team_stats[home]['wins'] += 1
                team_stats[home]['points'] += 3
                team_stats[away]['losses'] += 1
            elif result == '2':
                team_stats[away]['wins'] += 1
                team_stats[away]['points'] += 3
                team_stats[home]['losses'] += 1
            elif result == 'X':
                team_stats[home]['draws'] += 1
                team_stats[home]['points'] += 1
                team_stats[away]['draws'] += 1
                team_stats[away]['points'] += 1
        
        print(f"   ✅ {len(team_stats)} équipes analysées")
        
        self.close()
        return dict(team_stats)


# ============================================================================
# 7. CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Importateur avancé de résultats historiques"
    )
    parser.add_argument("--file", type=str, help="Fichier à importer (JSON, CSV, Excel)")
    parser.add_argument("--folder", type=str, help="Dossier contenant les fichiers")
    parser.add_argument("--api", action="store_true", help="Importer depuis l'API Football-Data")
    parser.add_argument("--league", type=str, default="PL", help="Code ligue (ex: PL, BL1)")
    parser.add_argument("--season", type=int, help="Saison (ex: 2024)")
    parser.add_argument("--batch-size", type=int, default=5000, help="Taille du batch")
    parser.add_argument("--auto-detect", action="store_true", help="Détection automatique")
    parser.add_argument("--stats", action="store_true", help="Afficher les statistiques")
    parser.add_argument("--history", action="store_true", help="Afficher l'historique des imports")
    
    args = parser.parse_args()
    
    importer = ResultsImporterPro()
    
    if args.history:
        history = importer.get_import_history()
        print("\n📋 Historique des imports:")
        for h in history:
            print(f"   {h['import_date'][:16]} | {h['source']} | "
                  f"Insert: {h['inserted']} | Update: {h['updated']} | "
                  f"Durée: {h['duration']:.1f}s")
        return
    
    if args.stats:
        stats = importer.compute_team_stats()
        if stats:
            # Top 10
            sorted_teams = sorted(stats.items(), key=lambda x: x[1]['points'], reverse=True)[:10]
            print("\n🏆 Top 10 équipes:")
            for i, (team, s) in enumerate(sorted_teams, 1):
                print(f"   {i}. {team}: {s['points']} pts "
                      f"({s['wins']}W/{s['draws']}D/{s['losses']}L) "
                      f"Diff: {s['goals_for']-s['goals_against']}")
        return
    
    if args.api:
        if not args.league or not args.season:
            print("❌ Pour l'API, spécifiez --league et --season")
            return
        
        matches = importer.load_from_api(args.league, args.season)
        if matches:
            stats = importer.import_matches(matches, source=f"api_{args.league}_{args.season}")
            print(f"\n✅ Import API terminé:")
            print(f"   Insert: {stats['inserted']} | Update: {stats['updated']} | Skip: {stats['skipped']}")
        return
    
    if args.folder:
        folder = Path(args.folder)
        if not folder.exists():
            print(f"❌ Dossier introuvable: {folder}")
            return
        
        files = list(folder.glob("*.*"))
        total_inserted = 0
        total_updated = 0
        
        for file in files:
            if file.suffix.lower() in ['.json', '.csv', '.xlsx', '.xls']:
                print(f"\n📄 Import de {file.name}")
                matches = importer.load_file(file)
                stats = importer.import_matches(matches, source=f"file_{file.name}")
                total_inserted += stats['inserted']
                total_updated += stats['updated']
        
        print(f"\n✅ Import dossier terminé:")
        print(f"   Total Insert: {total_inserted} | Update: {total_updated}")
        return
    
    if args.file:
        file_path = Path(args.file)
        matches = importer.load_file(file_path)
        stats = importer.import_matches(matches, source=f"file_{file_path.name}")
        print(f"\n✅ Import terminé:")
        print(f"   Insert: {stats['inserted']} | Update: {stats['updated']} | Skip: {stats['skipped']}")
        return
    
    if args.auto_detect:
        print("🔍 Détection automatique des fichiers...")
        # Chercher des fichiers dans le dossier courant
        files = list(Path('.').glob('*.*'))
        import_files = [f for f in files if f.suffix.lower() in ['.json', '.csv', '.xlsx', '.xls']]
        
        if not import_files:
            print("   ⚠️ Aucun fichier trouvé")
            return
        
        for file in import_files:
            print(f"\n📄 Import automatique de {file.name}")
            try:
                matches = importer.load_file(file)
                stats = importer.import_matches(matches, source=f"auto_{file.name}")
                print(f"   ✅ Insert: {stats['inserted']} | Update: {stats['updated']}")
            except Exception as e:
                print(f"   ❌ Erreur: {e}")
        return
    
    parser.print_help()


if __name__ == "__main__":
    main()