"""
generate_dataset.py — Génération d'un dataset d'entraînement depuis Football-Data.org
=======================================================================================

Ce module utilise les données déjà collectées par l'auto-scraper dans congobet.db
pour générer un dataset complet prêt pour l'entraînement de l'IA.

Il ajoute :
- Les statistiques des équipes (forme, moyenne de buts, etc.)
- Les cotes 1X2 (si disponibles)
- Les features pour l'apprentissage automatique
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

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import json
import argparse
import requests
import time

DB_PATH = Path("congobet.db")
DATA_DIR = Path("ai_training_data")
DATA_DIR.mkdir(exist_ok=True)

# ============================================================================
# CONFIGURATION API (pour récupérer les cotes si disponibles)
# ============================================================================

CONFIG = {
    "api_key": "fe50fdb0b9074d04b5533deaafbfe099",
    "base_url": "https://api.football-data.org/v4",
}

# ============================================================================
# CLASSE PRINCIPALE
# ============================================================================

class DatasetGenerator:
    """Génère un dataset d'entraînement à partir de la base de données."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = None
        self.matches_df = None
        self.features_df = None
        
    def connect(self):
        """Établit la connexion à la base de données."""
        self.conn = sqlite3.connect(self.db_path)
        return self.conn
    
    def close(self):
        """Ferme la connexion."""
        if self.conn:
            self.conn.close()
    
    def load_matches(self, competition_id: str = None, min_matches: int = 10):
        """
        Charge les matchs terminés depuis la base.
        
        Args:
            competition_id: Filtrer par compétition (ex: 'PL')
            min_matches: Nombre minimum de matchs pour qu'une équipe soit incluse
        """
        query = """
            SELECT 
                match_id,
                competition_id,
                home_team_id,
                away_team_id,
                home_team_name,
                away_team_name,
                home_score,
                away_score,
                result,
                status,
                utc_date,
                timestamp,
                season_id,
                matchday
            FROM matches 
            WHERE status = 'FINISHED' 
            AND home_score IS NOT NULL 
            AND away_score IS NOT NULL
        """
        
        if competition_id:
            query += f" AND competition_id = '{competition_id}'"
        
        query += " ORDER BY timestamp ASC"
        
        self.matches_df = pd.read_sql_query(query, self.conn)
        print(f"📊 {len(self.matches_df)} matchs chargés")
        
        # Filtrer les équipes avec peu de matchs
        if min_matches > 0:
            team_counts = pd.concat([
                self.matches_df['home_team_id'],
                self.matches_df['away_team_id']
            ]).value_counts()
            
            valid_teams = team_counts[team_counts >= min_matches].index.tolist()
            self.matches_df = self.matches_df[
                self.matches_df['home_team_id'].isin(valid_teams) &
                self.matches_df['away_team_id'].isin(valid_teams)
            ]
            print(f"📊 {len(self.matches_df)} matchs après filtrage (min {min_matches} matchs/équipe)")
        
        return self.matches_df
    
    def calculate_team_stats(self):
        """Calcule les statistiques des équipes."""
        if self.matches_df is None or self.matches_df.empty:
            print("❌ Aucun match chargé")
            return
        
        team_stats = {}
        
        # Statistiques pour chaque équipe
        all_teams = pd.concat([
            self.matches_df[['home_team_id', 'home_team_name']].rename(
                columns={'home_team_id': 'team_id', 'home_team_name': 'team_name'}
            ),
            self.matches_df[['away_team_id', 'away_team_name']].rename(
                columns={'away_team_id': 'team_id', 'away_team_name': 'team_name'}
            )
        ]).drop_duplicates('team_id')
        
        for _, team in all_teams.iterrows():
            team_id = team['team_id']
            team_name = team['team_name']
            
            # Matchs de l'équipe
            team_matches = self.matches_df[
                (self.matches_df['home_team_id'] == team_id) |
                (self.matches_df['away_team_id'] == team_id)
            ]
            
            if len(team_matches) < 5:
                continue
            
            # Statistiques
            total_matches = len(team_matches)
            wins = 0
            draws = 0
            losses = 0
            goals_for = 0
            goals_against = 0
            
            for _, match in team_matches.iterrows():
                is_home = match['home_team_id'] == team_id
                home_score = match['home_score']
                away_score = match['away_score']
                
                if is_home:
                    goals_for += home_score
                    goals_against += away_score
                    if home_score > away_score:
                        wins += 1
                    elif home_score < away_score:
                        losses += 1
                    else:
                        draws += 1
                else:
                    goals_for += away_score
                    goals_against += home_score
                    if away_score > home_score:
                        wins += 1
                    elif away_score < home_score:
                        losses += 1
                    else:
                        draws += 1
            
            # Forme (5 derniers matchs)
            recent = team_matches.tail(5)
            form = []
            for _, match in recent.iterrows():
                is_home = match['home_team_id'] == team_id
                home_score = match['home_score']
                away_score = match['away_score']
                
                if is_home:
                    if home_score > away_score:
                        form.append('W')
                    elif home_score < away_score:
                        form.append('L')
                    else:
                        form.append('D')
                else:
                    if away_score > home_score:
                        form.append('W')
                    elif away_score < home_score:
                        form.append('L')
                    else:
                        form.append('D')
            
            points = wins * 3 + draws
            win_rate = wins / total_matches if total_matches > 0 else 0
            avg_goals_scored = goals_for / total_matches if total_matches > 0 else 0
            avg_goals_conceded = goals_against / total_matches if total_matches > 0 else 0
            goal_diff = goals_for - goals_against
            
            team_stats[team_id] = {
                'team_id': team_id,
                'team_name': team_name,
                'total_matches': total_matches,
                'wins': wins,
                'draws': draws,
                'losses': losses,
                'points': points,
                'goals_for': goals_for,
                'goals_against': goals_against,
                'goal_diff': goal_diff,
                'win_rate': win_rate,
                'avg_goals_scored': avg_goals_scored,
                'avg_goals_conceded': avg_goals_conceded,
                'form': ''.join(form) if form else '',
                'points_per_match': points / total_matches if total_matches > 0 else 0,
                'strength': (win_rate * 0.5 + avg_goals_scored * 0.3 + (1 / (avg_goals_conceded + 0.5)) * 0.2)
            }
        
        self.team_stats = team_stats
        print(f"📊 {len(team_stats)} équipes analysées")
        return team_stats
    
    def generate_features(self):
        """Génère les features pour chaque match."""
        if self.matches_df is None or self.matches_df.empty:
            print("❌ Aucun match chargé")
            return
        
        if not hasattr(self, 'team_stats') or not self.team_stats:
            self.calculate_team_stats()
        
        features = []
        
        for idx, match in self.matches_df.iterrows():
            home_id = match['home_team_id']
            away_id = match['away_team_id']
            
            # Récupérer les stats des équipes
            home_stats = self.team_stats.get(home_id, {})
            away_stats = self.team_stats.get(away_id, {})
            
            # Features pour le match
            feature = {
                'match_id': match['match_id'],
                'home_team': match['home_team_name'],
                'away_team': match['away_team_name'],
                'home_score': match['home_score'],
                'away_score': match['away_score'],
                'result': match['result'],
                'season_id': match['season_id'],
                'matchday': match['matchday'],
                
                # Features domicile
                'home_avg_goals_scored': home_stats.get('avg_goals_scored', 0),
                'home_avg_goals_conceded': home_stats.get('avg_goals_conceded', 0),
                'home_win_rate': home_stats.get('win_rate', 0),
                'home_points_per_match': home_stats.get('points_per_match', 0),
                'home_strength': home_stats.get('strength', 0),
                'home_goals_for': home_stats.get('goals_for', 0),
                'home_goals_against': home_stats.get('goals_against', 0),
                'home_goal_diff': home_stats.get('goal_diff', 0),
                'home_matches_played': home_stats.get('total_matches', 0),
                
                # Features extérieur
                'away_avg_goals_scored': away_stats.get('avg_goals_scored', 0),
                'away_avg_goals_conceded': away_stats.get('avg_goals_conceded', 0),
                'away_win_rate': away_stats.get('win_rate', 0),
                'away_points_per_match': away_stats.get('points_per_match', 0),
                'away_strength': away_stats.get('strength', 0),
                'away_goals_for': away_stats.get('goals_for', 0),
                'away_goals_against': away_stats.get('goals_against', 0),
                'away_goal_diff': away_stats.get('goal_diff', 0),
                'away_matches_played': away_stats.get('total_matches', 0),
                
                # Différentiels
                'strength_diff': home_stats.get('strength', 0) - away_stats.get('strength', 0),
                'win_rate_diff': home_stats.get('win_rate', 0) - away_stats.get('win_rate', 0),
                'goals_scored_diff': home_stats.get('avg_goals_scored', 0) - away_stats.get('avg_goals_scored', 0),
                'goals_conceded_diff': home_stats.get('avg_goals_conceded', 0) - away_stats.get('avg_goals_conceded', 0),
                'points_diff': home_stats.get('points_per_match', 0) - away_stats.get('points_per_match', 0),
            }
            
            features.append(feature)
        
        self.features_df = pd.DataFrame(features)
        print(f"📊 {len(self.features_df)} features générées")
        return self.features_df
    
    def export_csv(self, filename: str = None):
        """Exporte les données en CSV."""
        if self.features_df is None or self.features_df.empty:
            print("❌ Aucune feature à exporter")
            return
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"training_data_{timestamp}.csv"
        
        filepath = DATA_DIR / filename
        self.features_df.to_csv(filepath, index=False, encoding='utf-8-sig')
        print(f"✅ Exporté: {filepath}")
        print(f"   {len(self.features_df)} lignes, {len(self.features_df.columns)} colonnes")
        
        # Statistiques
        print("\n📊 Statistiques:")
        print(f"  • Résultats: H={len(self.features_df[self.features_df['result']=='H'])}")
        print(f"               D={len(self.features_df[self.features_df['result']=='D'])}")
        print(f"               A={len(self.features_df[self.features_df['result']=='A'])}")
        print(f"  • Moyenne buts/match: {self.features_df['home_score'].mean():.2f} - {self.features_df['away_score'].mean():.2f}")
        
        return filepath
    
    def export_json(self, filename: str = None):
        """Exporte les données en JSON."""
        if self.features_df is None or self.features_df.empty:
            print("❌ Aucune feature à exporter")
            return
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"training_data_{timestamp}.json"
        
        filepath = DATA_DIR / filename
        self.features_df.to_json(filepath, orient='records', force_ascii=False, indent=2)
        print(f"✅ Exporté: {filepath}")
        
        return filepath
    
    def get_team_summary(self, team_name: str = None):
        """Affiche un résumé des statistiques d'une équipe."""
        if not hasattr(self, 'team_stats') or not self.team_stats:
            self.calculate_team_stats()
        
        if team_name:
            teams = [t for t in self.team_stats.values() if team_name.lower() in t['team_name'].lower()]
        else:
            teams = list(self.team_stats.values())
        
        if not teams:
            print(f"❌ Équipe '{team_name}' non trouvée")
            return
        
        for team in sorted(teams, key=lambda x: x['points'], reverse=True)[:10]:
            print(f"\n{team['team_name']}")
            print(f"  • Matchs: {team['total_matches']} | Victoires: {team['wins']} | Nuls: {team['draws']} | Défaites: {team['losses']}")
            print(f"  • Buts: {team['goals_for']} - {team['goals_against']} (Diff: {team['goal_diff']})")
            print(f"  • Points: {team['points']} | Moyenne: {team['points_per_match']:.2f}")
            print(f"  • Taux victoire: {team['win_rate']*100:.1f}% | Forme: {team['form']}")
            print(f"  • Force: {team['strength']:.3f}")
    
    def run_full_pipeline(self, competition_id: str = None, min_matches: int = 10, 
                          export_format: str = 'csv'):
        """
        Exécute le pipeline complet.
        
        Args:
            competition_id: Filtrer par compétition
            min_matches: Nombre minimum de matchs par équipe
            export_format: 'csv' ou 'json'
        """
        print("=" * 60)
        print("🏆 GÉNÉRATION DE DATASET D'ENTRAÎNEMENT")
        print("=" * 60)
        
        # 1. Charger les matchs
        print("\n📥 Étape 1: Chargement des matchs...")
        self.connect()
        self.load_matches(competition_id, min_matches)
        
        if self.matches_df.empty:
            print("❌ Aucun match trouvé")
            return
        
        # 2. Calculer les stats
        print("\n📊 Étape 2: Calcul des statistiques...")
        self.calculate_team_stats()
        
        # 3. Générer les features
        print("\n🧠 Étape 3: Génération des features...")
        self.generate_features()
        
        # 4. Exporter
        print("\n💾 Étape 4: Export...")
        if export_format == 'csv':
            self.export_csv()
        else:
            self.export_json()
        
        # 5. Résumé
        print("\n" + "=" * 60)
        print("✅ PIPELINE TERMINÉ")
        print("=" * 60)
        
        self.close()


# ============================================================================
# FONCTION PRINCIPALE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Génère un dataset d'entraînement pour l'IA"
    )
    parser.add_argument("--competition", type=str, help="Code compétition (PL, BL1, etc.)")
    parser.add_argument("--min-matches", type=int, default=10, help="Minimum matchs par équipe")
    parser.add_argument("--format", type=str, default="csv", choices=["csv", "json"], help="Format d'export")
    parser.add_argument("--team-summary", type=str, help="Afficher le résumé d'une équipe")
    parser.add_argument("--top-teams", type=int, default=10, help="Afficher le top N équipes")
    
    args = parser.parse_args()
    
    generator = DatasetGenerator()
    
    if args.team_summary:
        generator.connect()
        generator.load_matches()
        generator.calculate_team_stats()
        generator.get_team_summary(args.team_summary)
        generator.close()
        return
    
    if args.top_teams:
        generator.connect()
        generator.load_matches()
        generator.calculate_team_stats()
        print(f"\n🏆 Top {args.top_teams} équipes:")
        teams = sorted(generator.team_stats.values(), key=lambda x: x['points'], reverse=True)[:args.top_teams]
        for i, team in enumerate(teams, 1):
            print(f"{i}. {team['team_name']} - {team['points']} pts ({team['win_rate']*100:.1f}%)")
        generator.close()
        return
    
    # Pipeline complet
    generator.run_full_pipeline(
        competition_id=args.competition,
        min_matches=args.min_matches,
        export_format=args.format
    )


if __name__ == "__main__":
    main()