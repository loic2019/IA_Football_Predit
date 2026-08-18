"""
daily_evaluation_pro.py — Évaluation quotidienne avancée
================================================================================
- Compare les prédictions IA (classique + deep) vs résultats réels
- Support du modèle profond 50 couches
- Analyse de performance par compétition
- Graphiques d'évolution
- Export automatique des rapports
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

import json
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============================================================================
# CONFIGURATION
# ============================================================================

DB_PATH = Path("congobet.db")
PREDICTIONS_PATH = Path("predictions_history.json")
DEEP_PREDICTIONS_PATH = Path("deep_predictions_history.json")
EVAL_REPORT_DIR = Path("evaluation_reports")
EVAL_REPORT_DIR.mkdir(exist_ok=True)

# ============================================================================
# CLASSES
# ============================================================================

class DailyEvaluator:
    """Évaluateur quotidien des prédictions."""
    
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.conn = None
        self.ensure_tables()
    
    def ensure_tables(self):
        """Crée les tables d'évaluation."""
        conn = sqlite3.connect(self.db_path)
        
        # Table des évaluations
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evaluation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evaluation_date TEXT,
                model_type TEXT,
                total_evaluated INTEGER,
                correct INTEGER,
                wrong INTEGER,
                accuracy REAL,
                pnl REAL,
                roi REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table des détails par match
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evaluation_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evaluation_id INTEGER,
                match_id TEXT,
                model_type TEXT,
                predicted TEXT,
                actual TEXT,
                correct BOOLEAN,
                confidence REAL,
                cote REAL,
                pnl REAL,
                home TEXT,
                away TEXT,
                league TEXT,
                home_score INTEGER,
                away_score INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table des performances par ligue
        conn.execute("""
            CREATE TABLE IF NOT EXISTS league_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league TEXT,
                model_type TEXT,
                total INTEGER,
                correct INTEGER,
                accuracy REAL,
                pnl REAL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
    
    def close(self):
        if self.conn:
            self.conn.close()
    
    def _parse_date(self, dt_str: str) -> Optional[date]:
        """Parse une date ISO."""
        if not dt_str:
            return None
        try:
            iso = dt_str.replace("Z", "+00:00")
            return datetime.fromisoformat(iso).date()
        except Exception:
            try:
                return datetime.strptime(dt_str[:10], "%Y-%m-%d").date()
            except Exception:
                return None
    
    def _result_label(self, result: str, home: str, away: str) -> str:
        """Label lisible d'un résultat."""
        return {
            "1": f"Victoire {home}",
            "X": "Nul",
            "2": f"Victoire {away}"
        }.get(result, result or "?")
    
    def load_predictions(self, path: Path, model_type: str = "classic") -> Dict:
        """Charge les prédictions depuis un fichier."""
        if not path.exists():
            return {}
        
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        
        idx = {}
        for p in data.get("predictions", []):
            mid = p.get("match_id", "")
            if mid:
                p["model_type"] = model_type
                idx[mid] = p
        return idx
    
    def get_finished_matches_for_date(self, target: Optional[date] = None) -> List[Dict]:
        """Récupère les matchs terminés pour une date."""
        target = target or date.today()
        
        if not self.db_path.exists():
            return []
        
        self.connect()
        
        try:
            # Vérifier les tables disponibles
            tables = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            tables = [t[0] for t in tables]
            
            # Déterminer la table à utiliser
            if 'football_matches' in tables:
                table = 'football_matches'
                id_col = 'match_id'
                score_cols = 'home_score, away_score'
                league_col = 'competition_id as league'
            elif 'matches' in tables:
                table = 'matches'
                id_col = 'match_id'
                score_cols = 'home_score, away_score'
                league_col = 'competition_id as league'
            else:
                return []
            
            # Construire la requête
            query = f"""
                SELECT 
                    {id_col} as id,
                    home_team_name as home,
                    away_team_name as away,
                    {league_col},
                    utc_date as start_time,
                    result,
                    {score_cols},
                    status
                FROM {table}
                WHERE status = 'FINISHED'
                AND result IS NOT NULL
                AND result != ''
            """
            
            rows = self.conn.execute(query).fetchall()
            
            # Filtrer par date
            out = []
            for row in rows:
                d = self._parse_date(row["start_time"] or "")
                if d == target:
                    out.append(dict(row))
            
            return out
            
        except Exception as e:
            print(f"❌ Erreur chargement matchs: {e}")
            return []
        finally:
            self.close()
    
    def evaluate_match(self, match: Dict, pred: Dict, model_type: str = "classic") -> Dict:
        """Évalue une prédiction individuelle."""
        actual = str(match.get("result", "")).strip()
        predicted = str(pred.get("prediction", "")).strip()
        
        is_correct = predicted == actual if predicted in ("1", "X", "2") else None
        
        # P&L
        cote = pred.get("cote", 0)
        stake = 10.0
        pnl = None
        if cote and cote > 1.0 and is_correct is not None:
            pnl = round(stake * (cote - 1.0), 2) if is_correct else round(-stake, 2)
        
        return {
            "match_id": match.get("id", ""),
            "home": match.get("home", ""),
            "away": match.get("away", ""),
            "league": match.get("league", ""),
            "home_score": match.get("home_score"),
            "away_score": match.get("away_score"),
            "result_reel": actual,
            "prediction_ia": predicted,
            "correct": is_correct,
            "confidence": pred.get("confidence", 0),
            "cote": cote,
            "pnl": pnl,
            "model_type": model_type
        }
    
    def evaluate_day(self, target: Optional[date] = None) -> Dict:
        """
        Évalue toutes les prédictions pour une journée donnée.
        """
        target = target or date.today()
        
        # Charger les matchs terminés
        matches = self.get_finished_matches_for_date(target)
        
        if not matches:
            return {
                "date": target.isoformat(),
                "date_display": target.strftime("%d/%m/%Y"),
                "total_finished": 0,
                "evaluations": {},
                "summary": {}
            }
        
        # Charger les prédictions
        classic_preds = self.load_predictions(PREDICTIONS_PATH, "classic")
        deep_preds = self.load_predictions(DEEP_PREDICTIONS_PATH, "deep") if DEEP_PREDICTIONS_PATH.exists() else {}
        
        evaluations = {}
        all_details = []
        
        # Évaluer les prédictions classiques
        classic_evals = []
        for match in matches:
            mid = match.get("id", "")
            pred = classic_preds.get(mid, {})
            if pred:
                eval_result = self.evaluate_match(match, pred, "classic")
                classic_evals.append(eval_result)
                all_details.append(eval_result)
        
        evaluations["classic"] = self._compute_stats(classic_evals)
        
        # Évaluer les prédictions profondes
        if deep_preds:
            deep_evals = []
            for match in matches:
                mid = match.get("id", "")
                pred = deep_preds.get(mid, {})
                if pred:
                    eval_result = self.evaluate_match(match, pred, "deep")
                    deep_evals.append(eval_result)
                    all_details.append(eval_result)
            
            evaluations["deep"] = self._compute_stats(deep_evals)
        
        # Ensemble (moyenne des deux)
        if evaluations.get("classic") and evaluations.get("deep"):
            ensemble_evals = []
            for classic, deep in zip(classic_evals, deep_evals):
                if classic and deep:
                    # Moyenne des prédictions
                    classic_pred = classic.get("prediction_ia")
                    deep_pred = deep.get("prediction_ia")
                    if classic_pred and deep_pred:
                        # Si les deux sont d'accord, on prend cette prédiction
                        if classic_pred == deep_pred:
                            pred = classic_pred
                        else:
                            # Sinon on prend celle avec la plus haute confiance
                            classic_conf = classic.get("confidence", 0)
                            deep_conf = deep.get("confidence", 0)
                            pred = classic_pred if classic_conf >= deep_conf else deep_pred
                        
                        # Créer une évaluation ensemble
                        ensemble_match = match.copy()
                        ensemble_pred = {
                            "prediction": pred,
                            "confidence": max(classic.get("confidence", 0), deep.get("confidence", 0)),
                            "cote": classic.get("cote", 0) or deep.get("cote", 0)
                        }
                        eval_result = self.evaluate_match(ensemble_match, ensemble_pred, "ensemble")
                        ensemble_evals.append(eval_result)
                        all_details.append(eval_result)
            
            evaluations["ensemble"] = self._compute_stats(ensemble_evals)
        
        # Résumé
        summary = {
            "date": target.isoformat(),
            "date_display": target.strftime("%d/%m/%Y"),
            "total_finished": len(matches),
            "models": list(evaluations.keys()),
            "best_model": max(evaluations.keys(), key=lambda k: evaluations[k].get("accuracy", 0)) if evaluations else None
        }
        
        # Sauvegarder les résultats
        self.save_evaluation(target, evaluations, all_details)
        
        return {
            "date": target.isoformat(),
            "date_display": target.strftime("%d/%m/%Y"),
            "total_finished": len(matches),
            "evaluations": evaluations,
            "summary": summary,
            "details": all_details
        }
    
    def _compute_stats(self, evals: List[Dict]) -> Dict:
        """Calcule les statistiques à partir des évaluations."""
        if not evals:
            return {
                "total": 0,
                "correct": 0,
                "wrong": 0,
                "accuracy": 0,
                "pnl": 0,
                "roi": 0,
                "avg_confidence": 0
            }
        
        total = len(evals)
        correct = sum(1 for e in evals if e.get("correct") is True)
        wrong = sum(1 for e in evals if e.get("correct") is False)
        pnl = sum(e.get("pnl", 0) for e in evals if e.get("pnl") is not None)
        total_staked = sum(10.0 for e in evals if e.get("pnl") is not None)
        confidence = [e.get("confidence", 0) for e in evals if e.get("confidence") is not None]
        
        return {
            "total": total,
            "correct": correct,
            "wrong": wrong,
            "accuracy": correct / total if total > 0 else 0,
            "pnl": pnl,
            "roi": (pnl / total_staked * 100) if total_staked > 0 else 0,
            "avg_confidence": sum(confidence) / len(confidence) if confidence else 0
        }
    
    def save_evaluation(self, target: date, evaluations: Dict, details: List[Dict]):
        """Sauvegarde les résultats d'évaluation dans la base."""
        conn = sqlite3.connect(self.db_path)
        
        try:
            # Pour chaque modèle
            for model_type, stats in evaluations.items():
                # Insérer dans evaluation_history
                cursor = conn.execute("""
                    INSERT INTO evaluation_history (
                        evaluation_date, model_type,
                        total_evaluated, correct, wrong,
                        accuracy, pnl, roi
                    ) VALUES (?,?,?,?,?,?,?,?)
                """, (
                    target.isoformat(),
                    model_type,
                    stats.get("total", 0),
                    stats.get("correct", 0),
                    stats.get("wrong", 0),
                    stats.get("accuracy", 0),
                    stats.get("pnl", 0),
                    stats.get("roi", 0)
                ))
                
                eval_id = cursor.lastrowid
                
                # Insérer les détails
                for detail in details:
                    if detail.get("model_type") == model_type:
                        conn.execute("""
                            INSERT INTO evaluation_details (
                                evaluation_id, match_id, model_type,
                                predicted, actual, correct,
                                confidence, cote, pnl,
                                home, away, league,
                                home_score, away_score
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (
                            eval_id,
                            detail.get("match_id", ""),
                            model_type,
                            detail.get("prediction_ia", ""),
                            detail.get("result_reel", ""),
                            1 if detail.get("correct") else 0 if detail.get("correct") is not None else None,
                            detail.get("confidence", 0),
                            detail.get("cote", 0),
                            detail.get("pnl", 0),
                            detail.get("home", ""),
                            detail.get("away", ""),
                            detail.get("league", ""),
                            detail.get("home_score"),
                            detail.get("away_score")
                        ))
            
            conn.commit()
            
        except Exception as e:
            print(f"❌ Erreur sauvegarde: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def get_performance_history(self, days: int = 30, model_type: str = "classic") -> pd.DataFrame:
        """Récupère l'historique des performances."""
        conn = sqlite3.connect(self.db_path)
        
        query = f"""
            SELECT 
                evaluation_date,
                total_evaluated,
                correct,
                wrong,
                accuracy,
                pnl,
                roi
            FROM evaluation_history
            WHERE model_type = '{model_type}'
            ORDER BY evaluation_date DESC
            LIMIT {days}
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        return df
    
    def get_league_performance(self) -> pd.DataFrame:
        """Récupère les performances par ligue."""
        conn = sqlite3.connect(self.db_path)
        
        query = """
            SELECT 
                league,
                COUNT(*) as total,
                SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as correct,
                AVG(CASE WHEN correct = 1 THEN 1.0 ELSE 0 END) as accuracy,
                SUM(pnl) as pnl
            FROM evaluation_details
            WHERE correct IS NOT NULL
            GROUP BY league
            ORDER BY total DESC
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        return df


# ============================================================================
# RAPPORTS ET VISUALISATIONS
# ============================================================================

def generate_daily_report(evaluator: DailyEvaluator, target: Optional[date] = None) -> None:
    """Génère un rapport HTML quotidien."""
    target = target or date.today()
    result = evaluator.evaluate_day(target)
    
    if result["total_finished"] == 0:
        print(f"ℹ️ Aucun match terminé le {result['date_display']}")
        return
    
    # Créer le rapport
    report = {
        "date": result["date_display"],
        "total_matches": result["total_finished"],
        "models": {}
    }
    
    for model, stats in result["evaluations"].items():
        report["models"][model] = {
            "accuracy": f"{stats['accuracy']:.1%}",
            "correct": stats["correct"],
            "wrong": stats["wrong"],
            "total": stats["total"],
            "pnl": f"{stats['pnl']:+.2f}€",
            "roi": f"{stats['roi']:+.1f}%",
            "avg_confidence": f"{stats['avg_confidence']:.1%}"
        }
    
    # Sauvegarder le rapport
    report_file = EVAL_REPORT_DIR / f"report_{target.isoformat()}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Rapport généré: {report_file}")
    
    # Afficher un résumé
    print(f"\n📊 Évaluation du {report['date']}")
    print(f"   Matchs terminés: {report['total_matches']}")
    print("\n   Modèles:")
    for model, stats in report["models"].items():
        print(f"   • {model.upper()}: Accuracy {stats['accuracy']} ({stats['correct']}/{stats['total']})")
        print(f"     P&L {stats['pnl']} | ROI {stats['roi']}")


def create_performance_charts(evaluator: DailyEvaluator, days: int = 30):
    """Crée des graphiques de performance."""
    
    # Collecter les données
    data = {}
    for model in ["classic", "deep", "ensemble"]:
        df = evaluator.get_performance_history(days, model)
        if not df.empty:
            data[model] = df
    
    if not data:
        print("❌ Aucune donnée disponible")
        return
    
    # Créer les graphiques
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=('Accuracy', 'P&L Cumulé', 'ROI', 'Volume de prédictions'),
        vertical_spacing=0.12,
        horizontal_spacing=0.12
    )
    
    colors = {"classic": "#f5c451", "deep": "#33c7ff", "ensemble": "#2ecc87"}
    
    for model, df in data.items():
        # Accuracy
        fig.add_trace(
            go.Scatter(
                x=df['evaluation_date'],
                y=df['accuracy'],
                name=f'{model} (acc)',
                line=dict(color=colors.get(model, '#888'), width=2),
                mode='lines+markers',
                showlegend=True
            ),
            row=1, col=1
        )
        
        # P&L cumulé
        if not df.empty:
            cum_pnl = df['pnl'].cumsum() if 'pnl' in df.columns else df['pnl']
            fig.add_trace(
                go.Scatter(
                    x=df['evaluation_date'],
                    y=cum_pnl,
                    name=f'{model} (PNL)',
                    line=dict(color=colors.get(model, '#888'), width=2),
                    mode='lines+markers',
                    showlegend=False
                ),
                row=1, col=2
            )
        
        # ROI
        if 'roi' in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df['evaluation_date'],
                    y=df['roi'],
                    name=f'{model} (ROI)',
                    line=dict(color=colors.get(model, '#888'), width=2, dash='dash'),
                    mode='lines+markers',
                    showlegend=False
                ),
                row=2, col=1
            )
        
        # Volume
        fig.add_trace(
            go.Bar(
                x=df['evaluation_date'],
                y=df['total_evaluated'],
                name=f'{model} (volume)',
                marker_color=colors.get(model, '#888'),
                showlegend=False
            ),
            row=2, col=2
        )
    
    fig.update_layout(
        height=600,
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    
    fig.update_yaxes(tickformat='.0%', row=1, col=1)
    fig.update_yaxes(tickformat='.0f', row=1, col=2)
    fig.update_yaxes(tickformat='.0%', row=2, col=1)
    
    return fig


# ============================================================================
# FONCTION PRINCIPALE
# ============================================================================

def main():
    """Fonction principale pour l'évaluation quotidienne."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Évaluation quotidienne des prédictions"
    )
    parser.add_argument("--date", type=str, help="Date au format YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=7, help="Nombre de jours à évaluer")
    parser.add_argument("--report", action="store_true", help="Générer un rapport")
    parser.add_argument("--charts", action="store_true", help="Générer les graphiques")
    
    args = parser.parse_args()
    
    evaluator = DailyEvaluator()
    
    if args.date:
        target = datetime.strptime(args.date, "%Y-%m-%d").date()
        result = evaluator.evaluate_day(target)
        
        print(f"\n📊 Évaluation du {result['date_display']}")
        print(f"   Matchs terminés: {result['total_finished']}")
        
        for model, stats in result["evaluations"].items():
            print(f"\n   🤖 Modèle {model.upper()}:")
            print(f"      Précision: {stats['accuracy']:.1%} ({stats['correct']}/{stats['total']})")
            print(f"      P&L: {stats['pnl']:+.2f}€")
            print(f"      ROI: {stats['roi']:+.1f}%")
            print(f"      Confiance moyenne: {stats['avg_confidence']:.1%}")
    
    elif args.report:
        # Générer les rapports des derniers jours
        for i in range(args.days):
            target = date.today() - timedelta(days=i)
            generate_daily_report(evaluator, target)
    
    elif args.charts:
        fig = create_performance_charts(evaluator, days=args.days)
        if fig:
            fig.show()
    
    else:
        # Évaluation par défaut: aujourd'hui
        result = evaluator.evaluate_day()
        print(f"\n📊 Évaluation du {result['date_display']}")
        print(f"   Matchs terminés: {result['total_finished']}")
        
        for model, stats in result["evaluations"].items():
            print(f"\n   🤖 Modèle {model.upper()}:")
            print(f"      Précision: {stats['accuracy']:.1%} ({stats['correct']}/{stats['total']})")
            print(f"      P&L: {stats['pnl']:+.2f}€")
            print(f"      ROI: {stats['roi']:+.1f}%")
        
        # Afficher les détails
        print("\n📋 Détails des matchs:")
        for detail in result["details"][:10]:
            status = "✅" if detail["correct"] else "❌" if detail["correct"] is not None else "⏳"
            print(f"   {status} {detail['home']} vs {detail['away']}")
            print(f"      Prédit: {detail['prediction_ia']} | Réel: {detail['result_reel']}")
            if detail["cote"]:
                print(f"      Cote: {detail['cote']:.2f} | P&L: {detail['pnl']:+.2f}€")


if __name__ == "__main__":
    main()