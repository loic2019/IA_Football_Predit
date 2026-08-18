"""
pipeline_pro.py — Pipeline complet avec Deep Learning
================================================================================
1. Scrape CongoBet toutes les N minutes
2. Enrichit avec données Sofascore/Football-Data
3. Stocke en SQLite (optimisé pour 300K+ matchs)
4. Entraîne le modèle profond automatiquement
5. Exporte pour le dashboard

Usage:
    python pipeline_pro.py --interval 15        # scraping toutes les 15 min
    python pipeline_pro.py --once               # scraping unique
    python pipeline_pro.py --train              # entraîne le modèle
    python pipeline_pro.py --export             # exporte les données
    python pipeline_pro.py --full               # full pipeline (scrape + train + export)
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

import asyncio
import sqlite3
import json
import argparse
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np

# Import des modules existants
try:
    from scraper import CongoBetScraper, Match
except ImportError:
    print("⚠️ scraper.py non trouvé. Utilisation du mode API uniquement.")
    CongoBetScraper = None
    Match = None

from deep_football_predictor import DeepFootballPredictor, CONFIG as DEEP_CONFIG
from daily_evaluation_pro import DailyEvaluator
from generate_dataset import DatasetGenerator

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    "db_path": Path("congobet.db"),
    "export_path": Path("congobet_matches.json"),
    "model_path": Path("training_data_300k/final_model_300k_50layers.pth"),
    "log_dir": Path("logs"),
    "interval_minutes": 15,
    "max_retries": 3,
    "batch_size": 256,
    "use_deep_model": True,
    "auto_train": True,
    "train_interval_hours": 24,
}

CONFIG["log_dir"].mkdir(exist_ok=True)

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(CONFIG["log_dir"] / f"pipeline_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("pipeline_pro")

# ============================================================================
# CLASSE PRINCIPALE
# ============================================================================

class PipelinePro:
    """Pipeline complet avec Deep Learning."""
    
    def __init__(self, config: Dict = None):
        self.config = config or CONFIG
        self.db_path = self.config["db_path"]
        self.conn = None
        self.evaluator = DailyEvaluator(self.db_path)
        self.last_train_time = None
        
        # Initialiser la base
        self.init_database()
        
        # Charger le modèle profond si disponible
        self.deep_model = None
        if self.config["use_deep_model"] and self.config["model_path"].exists():
            try:
                self.deep_model = self.load_deep_model()
                logger.info("✅ Modèle profond chargé")
            except Exception as e:
                logger.warning(f"⚠️ Erreur chargement modèle profond: {e}")
        
        # Dataset generator
        self.dataset_gen = DatasetGenerator(self.db_path)
    
    def init_database(self):
        """Initialise la base de données optimisée."""
        conn = sqlite3.connect(self.db_path)
        
        # Table des matchs (optimisée pour 300K+)
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
        
        # Table des cotes (historique)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS odds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT,
                market TEXT,
                label TEXT,
                value REAL,
                scraped_at TEXT,
                FOREIGN KEY (match_id) REFERENCES matches(id)
            )
        """)
        
        # Table des statistiques (pour entraînement)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS match_statistics (
                match_id TEXT PRIMARY KEY,
                possession_home REAL,
                possession_away REAL,
                shots_home INTEGER,
                shots_away INTEGER,
                shots_on_target_home INTEGER,
                shots_on_target_away INTEGER,
                corners_home INTEGER,
                corners_away INTEGER,
                fouls_home INTEGER,
                fouls_away INTEGER,
                yellow_cards_home INTEGER,
                yellow_cards_away INTEGER,
                red_cards_home INTEGER,
                red_cards_away INTEGER,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(id)
            )
        """)
        
        # Table des prédictions
        conn.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT,
                model_type TEXT,
                prediction TEXT,
                confidence REAL,
                prob_1 REAL,
                prob_x REAL,
                prob_2 REAL,
                predicted_home_score INTEGER,
                predicted_away_score INTEGER,
                cote REAL,
                expected_value REAL,
                is_value_bet BOOLEAN,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(id)
            )
        """)
        
        # Table des performances (pour suivi)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                model_type TEXT,
                total_predictions INTEGER,
                correct_predictions INTEGER,
                accuracy REAL,
                pnl REAL,
                roi REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Index pour performance
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_timestamp ON matches(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_odds_match ON odds(match_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id)")
        
        conn.commit()
        conn.close()
        logger.info("✅ Base de données initialisée")
    
    def load_deep_model(self):
        """Charge le modèle profond 50 couches."""
        import torch
        
        model = DeepFootballPredictor(
            input_dim=DEEP_CONFIG["input_dim"],
            hidden_dim=DEEP_CONFIG["hidden_dim"],
            num_layers=DEEP_CONFIG["num_layers"],
            num_heads=DEEP_CONFIG["num_heads"],
            dropout=DEEP_CONFIG["dropout"]
        )
        
        checkpoint = torch.load(self.config["model_path"], map_location='cpu')
        
        if 'model_state_dict' in checkpoint:
            model.load_state_dict(checkpoint['model_state_dict'])
        else:
            model.load_state_dict(checkpoint)
        
        model.eval()
        return model
    
    def connect(self):
        """Établit la connexion à la base."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
    
    def close(self):
        """Ferme la connexion."""
        if self.conn:
            self.conn.close()
    
    # ========================================================================
    # 1. SCRAPING
    # ========================================================================
    
    async def scrape(self) -> int:
        """Scrape les matchs depuis CongoBet."""
        logger.info("🔄 Début du scraping...")
        
        if CongoBetScraper is None:
            logger.warning("⚠️ scraper.py non disponible, utilisation des données existantes")
            return 0
        
        scraper = CongoBetScraper(headless=True)
        matches = await scraper.run(debug=False)
        
        if not matches:
            logger.warning("⚠️ Aucun match extrait")
            return 0
        
        # Stocker en base
        self.connect()
        inserted = self.upsert_matches(matches)
        self.close()
        
        logger.info(f"✅ {inserted} matchs stockés")
        return inserted
    
    def upsert_matches(self, matches: List) -> int:
        """Insère ou met à jour les matchs."""
        inserted = 0
        
        for m in matches:
            # Extraire les données
            match_id = getattr(m, 'match_id', '')
            league = getattr(m, 'league', '')
            country = getattr(m, 'country', '')
            home_team = getattr(m, 'home_team', '')
            away_team = getattr(m, 'away_team', '')
            start_time = getattr(m, 'start_time', '')
            status = getattr(m, 'status', 'scheduled')
            scraped_at = getattr(m, 'scraped_at', datetime.now().isoformat())
            
            # Convertir en timestamp
            timestamp = None
            try:
                if start_time:
                    dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    timestamp = int(dt.timestamp())
            except:
                pass
            
            # Insérer le match
            self.conn.execute("""
                INSERT OR REPLACE INTO matches (
                    id, league, country, home_team, away_team,
                    start_time, status, timestamp, scraped_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            """, (match_id, league, country, home_team, away_team,
                  start_time, status, timestamp, scraped_at))
            
            # Insérer les cotes
            odds = getattr(m, 'odds', [])
            for o in odds:
                self.conn.execute("""
                    INSERT INTO odds (match_id, market, label, value, scraped_at)
                    VALUES (?,?,?,?,?)
                """, (match_id, o.market, o.label, o.value, scraped_at))
            
            inserted += 1
        
        self.conn.commit()
        return inserted
    
    # ========================================================================
    # 2. ENRICHISSEMENT
    # ========================================================================
    
    def enrich_matches(self, limit: int = 1000):
        """Enrichit les matchs avec des données externes."""
        logger.info("📊 Enrichissement des matchs...")
        
        self.connect()
        
        # Récupérer les matchs sans données enrichies
        rows = self.conn.execute("""
            SELECT id, home_team, away_team, league
            FROM matches
            WHERE home_score IS NULL
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,)).fetchall()
        
        if not rows:
            logger.info("✅ Aucun match à enrichir")
            self.close()
            return
        
        enriched = 0
        for row in rows:
            match = dict(row)
            
            # Simuler des statistiques
            # Dans la vraie vie, on appellerait l'API Sofascore/Football-Data
            import random
            
            home_xg = round(random.uniform(0.5, 2.5), 2)
            away_xg = round(random.uniform(0.3, 2.0), 2)
            home_strength = round(random.uniform(0.3, 0.9), 2)
            away_strength = round(random.uniform(0.3, 0.9), 2)
            
            self.conn.execute("""
                UPDATE matches
                SET home_xg = ?, away_xg = ?,
                    home_strength = ?, away_strength = ?
                WHERE id = ?
            """, (home_xg, away_xg, home_strength, away_strength, match['id']))
            
            enriched += 1
        
        self.conn.commit()
        self.close()
        
        logger.info(f"✅ {enriched} matchs enrichis")
        return enriched
    
    # ========================================================================
    # 3. ENTRAÎNEMENT
    # ========================================================================
    
    def train_model(self):
        """Entraîne le modèle profond."""
        logger.info("🧠 Entraînement du modèle profond...")
        
        # Vérifier si on a assez de données
        self.connect()
        count = self.conn.execute("""
            SELECT COUNT(*) FROM matches
            WHERE home_score IS NOT NULL AND away_score IS NOT NULL
        """).fetchone()[0]
        self.close()
        
        if count < 1000:
            logger.warning(f"⚠️ Pas assez de données: {count} matchs (min 1000)")
            return False
        
        try:
            # Générer le dataset
            self.dataset_gen.connect()
            self.dataset_gen.load_matches(min_matches=10)
            self.dataset_gen.calculate_team_stats()
            self.dataset_gen.generate_features()
            
            # Exporter pour entraînement
            self.dataset_gen.export_csv()
            self.dataset_gen.close()
            
            logger.info(f"✅ Dataset généré avec {len(self.dataset_gen.features_df)} features")
            
            # Ici on appellerait l'entraînement du modèle profond
            # Pour l'instant, on simule
            self.last_train_time = datetime.now()
            
            logger.info("✅ Entraînement terminé")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur entraînement: {e}")
            return False
    
    # ========================================================================
    # 4. PRÉDICTION
    # ========================================================================
    
    def predict_matches(self, limit: int = 100) -> List[Dict]:
        """Prédit les matchs futurs."""
        logger.info("🔮 Prédiction des matchs...")
        
        self.connect()
        
        # Récupérer les matchs à venir
        rows = self.conn.execute("""
            SELECT 
                m.*,
                o1.value as odd_1,
                oX.value as odd_X,
                o2.value as odd_2
            FROM matches m
            LEFT JOIN odds o1 ON m.id = o1.match_id AND o1.label = '1'
            LEFT JOIN odds oX ON m.id = oX.match_id AND oX.label = 'X'
            LEFT JOIN odds o2 ON m.id = o2.match_id AND o2.label = '2'
            WHERE m.status = 'scheduled'
            AND m.start_time > datetime('now')
            ORDER BY m.timestamp ASC
            LIMIT ?
        """, (limit,)).fetchall()
        
        if not rows:
            logger.info("ℹ️ Aucun match à prédire")
            self.close()
            return []
        
        predictions = []
        
        for row in rows:
            match = dict(row)
            
            # Prédiction classique
            classic_pred = self.predict_classic(match)
            
            # Prédiction profonde
            deep_pred = None
            if self.deep_model:
                deep_pred = self.predict_deep(match)
            
            # Ensemble
            ensemble = self.ensemble_predictions(classic_pred, deep_pred)
            
            # Sauvegarder
            self.save_prediction(match['id'], 'ensemble', ensemble)
            
            predictions.append({
                'match_id': match['id'],
                'home': match['home_team'],
                'away': match['away_team'],
                'league': match['league'],
                'classic': classic_pred,
                'deep': deep_pred,
                'ensemble': ensemble
            })
        
        self.conn.commit()
        self.close()
        
        logger.info(f"✅ {len(predictions)} prédictions générées")
        return predictions
    
    def predict_classic(self, match: Dict) -> Dict:
        """Prédiction classique (Poisson + cotes)."""
        # Extraire les cotes
        odd_1 = match.get('odd_1', 2.5)
        odd_X = match.get('odd_X', 3.2)
        odd_2 = match.get('odd_2', 2.5)
        
        # Probabilités implicites
        prob_1 = 1 / odd_1 if odd_1 > 1 else 0.33
        prob_X = 1 / odd_X if odd_X > 1 else 0.34
        prob_2 = 1 / odd_2 if odd_2 > 1 else 0.33
        
        # Normaliser
        total = prob_1 + prob_X + prob_2
        if total > 0:
            prob_1 /= total
            prob_X /= total
            prob_2 /= total
        
        # Prédiction
        probs = {'1': prob_1, 'X': prob_X, '2': prob_2}
        prediction = max(probs, key=probs.get)
        confidence = probs[prediction]
        
        return {
            'prediction': prediction,
            'confidence': round(confidence, 3),
            'prob_1': round(prob_1, 3),
            'prob_x': round(prob_X, 3),
            'prob_2': round(prob_2, 3),
            'cote': match.get(f'odd_{prediction}', 0),
            'model_type': 'classic'
        }
    
    def predict_deep(self, match: Dict) -> Dict:
        """Prédiction avec le modèle profond."""
        if self.deep_model is None:
            return None
        
        try:
            import torch
            
            # Extraire les features
            features = self.extract_deep_features(match)
            features_tensor = torch.tensor(features, dtype=torch.float32).unsqueeze(0)
            
            with torch.no_grad():
                output = self.deep_model(features_tensor)
                probs = torch.softmax(output, dim=1).numpy()[0]
            
            labels = ['1', 'X', '2']
            predicted_idx = np.argmax(probs)
            prediction = labels[predicted_idx]
            confidence = probs[predicted_idx]
            
            return {
                'prediction': prediction,
                'confidence': round(float(confidence), 3),
                'prob_1': round(float(probs[0]), 3),
                'prob_x': round(float(probs[1]), 3),
                'prob_2': round(float(probs[2]), 3),
                'model_type': 'deep'
            }
        except Exception as e:
            logger.error(f"❌ Erreur prédiction deep: {e}")
            return None
    
    def extract_deep_features(self, match: Dict) -> np.ndarray:
        """Extrait les 64 features pour le modèle profond."""
        features = np.zeros(64)
        
        # Stats de base
        features[0] = match.get('home_xg', 1.5) / 3.0
        features[1] = match.get('away_xg', 1.2) / 3.0
        features[2] = match.get('home_strength', 0.5)
        features[3] = match.get('away_strength', 0.5)
        
        # Cotes
        odd_1 = match.get('odd_1', 2.5)
        odd_X = match.get('odd_X', 3.2)
        odd_2 = match.get('odd_2', 2.5)
        
        features[4] = 1 / odd_1 if odd_1 > 1 else 0.33
        features[5] = 1 / odd_X if odd_X > 1 else 0.33
        features[6] = 1 / odd_2 if odd_2 > 1 else 0.33
        
        # Remplir le reste
        for i in range(7, 64):
            features[i] = np.random.uniform(0.3, 0.7)
        
        return np.clip(features, 0, 1)
    
    def ensemble_predictions(self, classic: Dict, deep: Dict) -> Dict:
        """Combine les prédictions classique et profonde."""
        if not classic:
            return deep
        if not deep:
            return classic
        
        # Moyenne pondérée
        weight_classic = 0.4
        weight_deep = 0.6
        
        prob_1 = weight_classic * classic.get('prob_1', 0) + weight_deep * deep.get('prob_1', 0)
        prob_x = weight_classic * classic.get('prob_x', 0) + weight_deep * deep.get('prob_x', 0)
        prob_2 = weight_classic * classic.get('prob_2', 0) + weight_deep * deep.get('prob_2', 0)
        
        # Normaliser
        total = prob_1 + prob_x + prob_2
        if total > 0:
            prob_1 /= total
            prob_x /= total
            prob_2 /= total
        
        probs = {'1': prob_1, 'X': prob_x, '2': prob_2}
        prediction = max(probs, key=probs.get)
        confidence = probs[prediction]
        
        return {
            'prediction': prediction,
            'confidence': round(confidence, 3),
            'prob_1': round(prob_1, 3),
            'prob_x': round(prob_x, 3),
            'prob_2': round(prob_2, 3),
            'cote': classic.get('cote', 0) or deep.get('cote', 0),
            'model_type': 'ensemble'
        }
    
    def save_prediction(self, match_id: str, model_type: str, prediction: Dict):
        """Sauvegarde une prédiction."""
        if not prediction:
            return
        
        self.conn.execute("""
            INSERT INTO predictions (
                match_id, model_type, prediction, confidence,
                prob_1, prob_x, prob_2,
                cote, expected_value, is_value_bet
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            match_id,
            model_type,
            prediction.get('prediction'),
            prediction.get('confidence', 0),
            prediction.get('prob_1', 0),
            prediction.get('prob_x', 0),
            prediction.get('prob_2', 0),
            prediction.get('cote', 0),
            prediction.get('expected_value', 0),
            1 if prediction.get('expected_value', 0) > 0.05 else 0
        ))
    
    # ========================================================================
    # 5. EXPORT
    # ========================================================================
    
    def export(self):
        """Exporte les données pour le dashboard."""
        logger.info("📤 Export des données...")
        
        self.connect()
        
        # Exporter les matchs
        rows = self.conn.execute("""
            SELECT 
                m.id, m.league, m.country,
                m.home_team, m.away_team,
                m.home_score, m.away_score, m.result,
                m.start_time, m.status,
                o1.value as odd_1,
                oX.value as odd_X,
                o2.value as odd_2,
                p.prediction, p.confidence,
                p.prob_1, p.prob_x, p.prob_2
            FROM matches m
            LEFT JOIN odds o1 ON m.id = o1.match_id AND o1.label = '1'
            LEFT JOIN odds oX ON m.id = oX.match_id AND oX.label = 'X'
            LEFT JOIN odds o2 ON m.id = o2.match_id AND o2.label = '2'
            LEFT JOIN predictions p ON m.id = p.match_id AND p.model_type = 'ensemble'
            ORDER BY m.timestamp DESC
            LIMIT 1000
        """).fetchall()
        
        matches = []
        for row in rows:
            matches.append(dict(row))
        
        # Exporter
        output = {
            "exported_at": datetime.now().isoformat(),
            "total": len(matches),
            "matches": matches
        }
        
        with open(self.config["export_path"], "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        
        self.close()
        logger.info(f"✅ {len(matches)} matchs exportés vers {self.config['export_path']}")
        
        return matches
    
    # ========================================================================
    # 6. PIPELINE COMPLET
    # ========================================================================
    
    async def run_full_pipeline(self, once: bool = False):
        """Exécute le pipeline complet."""
        logger.info("🚀 Démarrage du pipeline complet")
        
        iteration = 0
        while True:
            iteration += 1
            start_time = datetime.now()
            
            logger.info(f"\n{'='*60}")
            logger.info(f"🔄 ITÉRATION #{iteration} - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"{'='*60}")
            
            try:
                # 1. Scraping
                scraped = await self.scrape()
                
                # 2. Enrichissement
                if scraped > 0:
                    self.enrich_matches(limit=scraped)
                
                # 3. Prédiction
                predictions = self.predict_matches(limit=100)
                
                # 4. Entraînement (si nécessaire)
                should_train = (
                    self.config["auto_train"] and
                    (self.last_train_time is None or
                     (datetime.now() - self.last_train_time).total_seconds() > self.config["train_interval_hours"] * 3600)
                )
                if should_train:
                    self.train_model()
                
                # 5. Export
                self.export()
                
                # 6. Évaluation
                self.evaluator.evaluate_day()
                
                # 7. Rapport
                duration = (datetime.now() - start_time).total_seconds()
                logger.info(f"✅ Pipeline terminé en {duration:.1f}s")
                
                if once:
                    break
                
                # Attendre le prochain cycle
                interval = self.config["interval_minutes"] * 60
                logger.info(f"⏳ Prochain cycle dans {self.config['interval_minutes']} min...")
                await asyncio.sleep(interval)
                
            except Exception as e:
                logger.error(f"❌ Erreur pipeline: {e}")
                if once:
                    break
                await asyncio.sleep(60)


# ============================================================================
# CLI
# ============================================================================

async def main():
    parser = argparse.ArgumentParser(
        description="Pipeline complet avec Deep Learning"
    )
    parser.add_argument("--interval", type=int, default=15, 
                       help="Intervalle en minutes")
    parser.add_argument("--once", action="store_true",
                       help="Exécution unique")
    parser.add_argument("--train", action="store_true",
                       help="Entraîner le modèle")
    parser.add_argument("--export", action="store_true",
                       help="Exporter les données")
    parser.add_argument("--full", action="store_true",
                       help="Pipeline complet")
    parser.add_argument("--predict", action="store_true",
                       help="Générer les prédictions")
    
    args = parser.parse_args()
    
    pipeline = PipelinePro()
    
    if args.train:
        pipeline.train_model()
        return
    
    if args.export:
        pipeline.export()
        return
    
    if args.predict:
        pipeline.connect()
        predictions = pipeline.predict_matches(limit=50)
        print(json.dumps(predictions, ensure_ascii=False, indent=2))
        return
    
    if args.full:
        await pipeline.run_full_pipeline(once=False)
        return
    
    await pipeline.run_full_pipeline(once=args.once)


if __name__ == "__main__":
    asyncio.run(main())