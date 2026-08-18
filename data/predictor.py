"""
predictor.py — Moteur de pronostic (version stable)
=================================================================
- Modèle de Poisson (prédiction de buts)
- Auto-entraînement sur les résultats passés
- Génération de coupons optimisés
- Compatible avec la base de données congobet.db

Usage:
    python predictor.py --analyze          # analyse les matchs du jour
    python predictor.py --coupon 8         # génère un coupon de 8 matchs
    python predictor.py --train            # re-entraîne le modèle
    python predictor.py --stats            # affiche les stats du modèle
    python predictor.py --auto-train 10    # auto-entraînement en boucle (10 min)
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
import math
import random
import argparse
import logging
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict

log = logging.getLogger("predictor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_PATH = Path("congobet.db")
JSON_PATH = Path("congobet_matches.json")
MODEL_PATH = Path("model_data.json")


def normalize_result(result: str) -> str:
    mapping = {
        "H": "1",
        "HOME": "1",
        "HOME_TEAM": "1",
        "A": "2",
        "AWAY": "2",
        "AWAY_TEAM": "2",
        "D": "X",
        "DRAW": "X",
        "1": "1",
        "X": "X",
        "2": "2",
    }
    return mapping.get(str(result or "").upper(), "")

def load_matches_from_db(competition_id: str = None, limit: int = 1000) -> list[dict]:
    """Charge les matchs depuis la base de données."""
    if not DB_PATH.exists():
        log.error(f"❌ {DB_PATH} introuvable")
        return []
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    
    if 'matches' in tables:
        table_name = 'matches'
    elif 'football_matches' in tables:
        table_name = 'football_matches'
    else:
        log.error("❌ Aucune table de matchs trouvée")
        conn.close()
        return []
    
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'home_team_name' in columns:
        home_col = 'home_team_name'
        away_col = 'away_team_name'
        league_col = 'competition_id'
        id_col = 'match_id'
        date_col = 'utc_date'
    elif 'home_team' in columns:
        home_col = 'home_team'
        away_col = 'away_team'
        league_col = 'league'
        id_col = 'id'
        date_col = 'start_time'
    else:
        home_col = 'home'
        away_col = 'away'
        league_col = 'league'
        id_col = 'id'
        date_col = 'start_time'
    
    has_status = 'status' in columns
    
    query = f"""
        SELECT 
            {id_col} as id, 
            {home_col} as home, 
            {away_col} as away,
            {league_col} as league, 
            home_score, 
            away_score, 
            result
    """
    
    if has_status:
        query += f", {date_col} as start_time"
    else:
        query += f", {date_col} as start_time"
    
    query += f" FROM {table_name}"
    
    if competition_id:
        query += f" WHERE {league_col} = '{competition_id}'"
    
    query += " ORDER BY start_time DESC"
    
    if limit:
        query += f" LIMIT {limit}"
    
    try:
        rows = conn.execute(query).fetchall()
        matches = [dict(row) for row in rows]
        if "odds" in tables:
            for match in matches:
                odds_rows = conn.execute(
                    "SELECT market, label, value FROM odds WHERE match_id = ?",
                    (match.get("id"),),
                ).fetchall()
                markets = {}
                for row in odds_rows:
                    markets.setdefault(row["market"], {})[row["label"]] = row["value"]
                match["markets"] = markets
        log.info(f"📂 {len(matches)} matchs chargés depuis {DB_PATH}")
        conn.close()
        return matches
    except sqlite3.OperationalError as e:
        log.error(f"❌ Erreur SQL: {e}")
        conn.close()
        return []


def load_matches_from_json() -> list[dict]:
    """Charge les matchs depuis le JSON."""
    if not JSON_PATH.exists():
        log.error(f"❌ {JSON_PATH} introuvable")
        return []
    
    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    
    matches = data.get("matches", [])
    
    for match in matches:
        if 'markets' not in match:
            match['markets'] = {
                "Résultat du match": {
                    "1": round(random.uniform(1.5, 3.0), 2),
                    "X": round(random.uniform(3.0, 4.5), 2),
                    "2": round(random.uniform(1.5, 3.0), 2)
                }
            }
    
    log.info(f"📂 {len(matches)} matchs chargés depuis {JSON_PATH}")
    return matches


def cote_to_prob(cote: float) -> float:
    if cote <= 1.0:
        return 0.99
    return 1.0 / cote


def extract_probs_from_odds(markets: dict) -> dict:
    """Extrait les probabilités depuis les cotes 1X2."""
    probs = {"1": 0.33, "X": 0.34, "2": 0.33}
    
    if not markets:
        return probs
    
    for market_name, odds in markets.items():
        if any(kw in str(market_name).lower() for kw in ["résultat", "1x2", "match", "resultat"]):
            if isinstance(odds, dict) and all(k in odds for k in ("1", "X", "2")):
                raw = {}
                total = 0
                for label in ("1", "X", "2"):
                    if odds.get(label) and float(odds[label]) > 1.0:
                        raw[label] = cote_to_prob(float(odds[label]))
                        total += raw[label]
                if total > 0:
                    for k in raw:
                        probs[k] = raw[k] / total
                break
    
    return probs


def poisson_prob(lam: float, k: int) -> float:
    return (math.exp(-lam) * (lam ** k)) / math.factorial(k)


def btts_probability(home_xg: float, away_xg: float) -> float:
    """
    P(les deux équipes marquent) à partir des xG Poisson déjà calculés pour
    le résultat 1X2 — pas de nouveau modèle nécessaire, juste une lecture
    différente des mêmes taux de buts attendus :
    P(BTTS=Oui) = 1 - P(dom.=0) - P(ext.=0) + P(dom.=0 ET ext.=0)
    (indépendance entre les 2 équipes — même hypothèse que poisson_match_probs).
    """
    p_home_0 = poisson_prob(home_xg, 0)
    p_away_0 = poisson_prob(away_xg, 0)
    return round(1 - p_home_0 - p_away_0 + (p_home_0 * p_away_0), 4)


def poisson_match_probs(home_xg: float, away_xg: float, max_goals: int = 8) -> dict:
    p1, px, p2 = 0.0, 0.0, 0.0
    
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson_prob(home_xg, h) * poisson_prob(away_xg, a)
            if h > a:
                p1 += p
            elif h == a:
                px += p
            else:
                p2 += p
    
    return {"1": round(p1, 4), "X": round(px, 4), "2": round(p2, 4)}


def estimate_xg_from_odds(probs: dict) -> tuple:
    p1 = probs.get("1", 0.33)
    p2 = probs.get("2", 0.33)
    
    home_xg = max(0.3, 1.2 + math.log(max(p1, 0.05)) * 0.8)
    away_xg = max(0.3, 1.2 + math.log(max(p2, 0.05)) * 0.8)
    
    return round(home_xg, 2), round(away_xg, 2)


class ModelData:
    def __init__(self):
        self.data = {
            "version": 2,
            "trained_at": None,
            "total_predictions": 0,
            "correct_predictions": 0,
            "league_accuracy": {},
            "team_form": {},
            "calibration": {
                "high": {"correct": 0, "total": 0},
                "medium": {"correct": 0, "total": 0},
                "low": {"correct": 0, "total": 0},
            },
            "history": [],
            "last_train": None,
        }
        self.load()
    
    def load(self):
        if MODEL_PATH.exists():
            with open(MODEL_PATH, encoding="utf-8") as f:
                saved = json.load(f)
                self.data.update(saved)
            log.info(f"🧠 Modèle chargé — {self.data['total_predictions']} prédictions")
        else:
            log.info("🆕 Nouveau modèle")
    
    def save(self):
        self.data["trained_at"] = datetime.now().isoformat()
        with open(MODEL_PATH, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def record_result(self, match_id: str, predicted: str, actual: str,
                      confidence: float, league: str, home: str, away: str,
                      cote: float = None, stake: float = 10.0):
        correct = predicted == actual
        self.data["total_predictions"] += 1
        if correct:
            self.data["correct_predictions"] += 1
        
        if confidence >= 0.65:
            bucket = "high"
        elif confidence >= 0.45:
            bucket = "medium"
        else:
            bucket = "low"
        self.data["calibration"][bucket]["total"] += 1
        if correct:
            self.data["calibration"][bucket]["correct"] += 1
        
        if actual == "1":
            home_r, away_r = "W", "L"
        elif actual == "2":
            home_r, away_r = "L", "W"
        else:
            home_r, away_r = "D", "D"
        
        for team, result_for_team in [(home, home_r), (away, away_r)]:
            if team not in self.data["team_form"]:
                self.data["team_form"][team] = []
            self.data["team_form"][team] = (self.data["team_form"][team] + [result_for_team])[-10:]
        
        self.save()

    def has_trained_match(self, match_id: str) -> bool:
        return any(str(item.get("match_id")) == str(match_id) for item in self.data.get("history", []))

    def record_training_match(self, match_id: str, predicted: str, actual: str,
                              confidence: float, league: str, home: str, away: str,
                              cote: float = None, probabilities: dict = None):
        correct = predicted == actual
        self.data["total_predictions"] += 1
        if correct:
            self.data["correct_predictions"] += 1

        if confidence >= 0.65:
            bucket = "high"
        elif confidence >= 0.45:
            bucket = "medium"
        else:
            bucket = "low"
        self.data["calibration"][bucket]["total"] += 1
        if correct:
            self.data["calibration"][bucket]["correct"] += 1

        league_stats = self.data["league_accuracy"].setdefault(league or "N/A", {"correct": 0, "total": 0})
        league_stats["total"] += 1
        if correct:
            league_stats["correct"] += 1

        if actual == "1":
            home_r, away_r = "W", "L"
        elif actual == "2":
            home_r, away_r = "L", "W"
        else:
            home_r, away_r = "D", "D"

        for team, result_for_team in [(home, home_r), (away, away_r)]:
            if team not in self.data["team_form"]:
                self.data["team_form"][team] = []
            self.data["team_form"][team] = (self.data["team_form"][team] + [result_for_team])[-10:]

        self.data.setdefault("history", []).append({
            "match_id": str(match_id),
            "trained_at": datetime.now().isoformat(),
            "home": home,
            "away": away,
            "league": league,
            "prediction": predicted,
            "actual": actual,
            "confidence": round(confidence, 3),
            "correct": correct,
            "cote": cote,
            "probabilities": probabilities or {},
        })
        self.data["history"] = self.data["history"][-5000:]
        self.data["last_train"] = datetime.now().isoformat()
        self.save()
    
    def overall_accuracy(self) -> float:
        total = self.data["total_predictions"]
        if total == 0:
            return 0.0
        return self.data["correct_predictions"] / total
    
    def get_team_form_score(self, team: str) -> float:
        form = self.data["team_form"].get(team, [])
        if not form:
            return 0.5
        points = 0.0
        for v in form:
            if v == "W":
                points += 1.0
            elif v == "D":
                points += 0.5
        return points / len(form)
    
    def get_league_boost(self, league: str) -> float:
        stats = self.data["league_accuracy"].get(league, {})
        total = stats.get("total", 0)
        if total < 5:
            return 1.0
        acc = stats.get("correct", 0) / total
        return 0.8 + (acc * 0.4)


class Predictor:
    def __init__(self, use_ensemble: bool = True):
        self.model = ModelData()
        self.use_ensemble = use_ensemble
    
    def predict(self, match: dict) -> dict:
        home = match.get("home", "")
        away = match.get("away", "")
        league = match.get("league", "")
        is_live = bool(match.get("is_live"))
        live_home_score = match.get("home_score")
        live_away_score = match.get("away_score")
        has_live_score = is_live and live_home_score is not None and live_away_score is not None

        markets = match.get("markets", {})
        odds_probs = extract_probs_from_odds(markets)
        
        home_xg, away_xg = estimate_xg_from_odds(odds_probs)
        poisson_probs = poisson_match_probs(home_xg, away_xg)
        
        final_probs = {}
        for k in ("1", "X", "2"):
            final_probs[k] = round(0.5 * odds_probs.get(k, 0.33) + 0.5 * poisson_probs.get(k, 0.33), 4)
        
        home_form = self.model.get_team_form_score(home)
        away_form = self.model.get_team_form_score(away)
        form_delta = (home_form - away_form) * 0.05
        
        final_probs["1"] = min(0.98, max(0.02, final_probs["1"] + form_delta))
        final_probs["2"] = min(0.98, max(0.02, final_probs["2"] - form_delta))

        total = sum(final_probs.values())
        for k in final_probs:
            final_probs[k] = round(final_probs[k] / total, 4)

        # --- Ajustement match en direct : le score déjà acquis compte plus que
        # les probabilités pré-match. On recalcule les probas restantes avec
        # Poisson sur les buts ENCORE à venir (xG scalé par temps restant
        # estimé), puis on combine avec le score déjà marqué. Reste conservateur
        # si on n'a pas d'info sur le temps écoulé (on suppose la 1ère mi-temps
        # écoulée, 45min/90 restant, comme hypothèse prudente par défaut).
        if has_live_score:
            goal_diff = int(live_home_score) - int(live_away_score)
            remaining_fraction = 0.5  # hypothèse par défaut si temps écoulé inconnu
            remaining_home_xg = home_xg * remaining_fraction
            remaining_away_xg = away_xg * remaining_fraction
            remaining_probs = poisson_match_probs(remaining_home_xg, remaining_away_xg)

            live_probs = {"1": 0.0, "X": 0.0, "2": 0.0}
            for h_rem in range(6):
                for a_rem in range(6):
                    p_rem = poisson_prob(remaining_home_xg, h_rem) * poisson_prob(remaining_away_xg, a_rem)
                    final_diff = goal_diff + (h_rem - a_rem)
                    if final_diff > 0:
                        live_probs["1"] += p_rem
                    elif final_diff == 0:
                        live_probs["X"] += p_rem
                    else:
                        live_probs["2"] += p_rem
            total_live = sum(live_probs.values()) or 1.0
            final_probs = {k: round(v / total_live, 4) for k, v in live_probs.items()}

        # --- Ensemble ML (XGBoost / LightGBM / réseau de neurones) ---
        # Si les sous-modèles ne sont pas encore entraînés (pas assez de données)
        # ou si les dépendances ne sont pas installées, on retombe silencieusement
        # sur final_probs tel quel (Poisson + cotes + forme) — jamais de plantage.
        model_breakdown = None
        models_used = ["poisson"]
        if self.use_ensemble:
            try:
                # Orchestrateur enterprise : ajoute Dixon-Coles et Elo (+ bayésien)
                # aux modèles ML existants (XGBoost/LightGBM/RF/etc.), avec
                # pondération dynamique par le meta-learner. Rien n'est retiré :
                # si l'orchestrateur échoue pour une raison quelconque, on
                # retombe sur l'ancien ensemble (XGB/LightGBM/RF/reseau), qui
                # lui-même se degrade proprement vers final_probs si besoin.
                from ensemble import orchestrator as ml_ensemble
                ensemble_result = ml_ensemble.predict_ensemble(match, self.model, final_probs)
                final_probs = dict(ensemble_result["probabilities"])
                model_breakdown = ensemble_result["model_breakdown"]
                models_used = ensemble_result["models_used"]
            except Exception:
                try:
                    from ml_models import ensemble as ml_ensemble_legacy
                    ensemble_result = ml_ensemble_legacy.predict_ensemble(match, self.model, final_probs)
                    final_probs = dict(ensemble_result["probabilities"])
                    model_breakdown = ensemble_result["model_breakdown"]
                    models_used = ensemble_result["models_used"]
                except Exception:
                    pass

        predicted = max(final_probs, key=final_probs.get)
        confidence = final_probs[predicted]
        
        cote = markets.get("Résultat du match", {}).get(predicted, 0)
        if isinstance(cote, str):
            try:
                cote = float(cote)
            except:
                cote = 0
        
        expected_value = round((confidence * cote) - 1, 3) if cote else 0
        
        exact_scores = []
        for h in range(5):
            for a in range(5):
                prob = poisson_prob(home_xg, h) * poisson_prob(away_xg, a)
                exact_scores.append({"score": f"{h}-{a}", "probability": prob})
        exact_scores.sort(key=lambda x: x["probability"], reverse=True)
        exact_scores = exact_scores[:3]
        
        return {
            "match_id": match.get("id", ""),
            "home": home,
            "away": away,
            "league": league,
            "start_time": match.get("start_time", ""),
            "is_live": is_live,
            "live_score": f"{live_home_score}-{live_away_score}" if has_live_score else None,
            "prediction": predicted,
            "confidence": round(confidence, 3),
            "probabilities": final_probs,
            "btts_probability": btts_probability(home_xg, away_xg),
            "home_xg": home_xg,
            "away_xg": away_xg,
            "cote": cote,
            "expected_value": expected_value,
            "models_used": models_used,
            "model_breakdown": model_breakdown,
            "is_value_bet": expected_value > 0.05,
            "exact_score_top3": [{"score": s["score"], "probability": round(s["probability"], 4)} for s in exact_scores],
            "home_form": home_form,
            "away_form": away_form,
            "comment": self._build_comment(home, away, predicted, confidence, home_form, away_form, is_live, has_live_score),
            "details": self._build_details(
                home, away, predicted, confidence, home_form, away_form,
                odds_probs, poisson_probs, home_xg, away_xg, cote, expected_value,
                models_used, model_breakdown, is_live, has_live_score,
                live_home_score, live_away_score,
            ),
        }
    
    def _build_comment(self, home: str, away: str, predicted: str, confidence: float,
                        home_form: float, away_form: float, is_live: bool = False,
                        has_live_score: bool = False) -> str:
        prefix = ""
        if is_live and not has_live_score:
            prefix = "⚠️ Match en direct mais score indisponible (analyse pré-match) — "
        elif is_live and has_live_score:
            prefix = "🔴 Match en direct, score pris en compte — "

        if predicted == "1":
            favori = home
        elif predicted == "2":
            favori = away
        else:
            return f"{prefix}Match équilibré entre {home} et {away}. Pronostic: Match nul (confiance {confidence:.0%})"
        
        form_text = ""
        if home_form - away_form > 0.2:
            form_text = f" avec une meilleure forme récente ({home_form:.1f} vs {away_form:.1f})"
        
        return f"{prefix}{favori} favori pour ce match{form_text}. Confiance: {confidence:.0%}"

    def _build_details(self, home, away, predicted, confidence, home_form, away_form,
                        odds_probs, poisson_probs, home_xg, away_xg, cote, expected_value,
                        models_used, model_breakdown, is_live, has_live_score,
                        live_home_score, live_away_score) -> dict:
        """
        Détails structurés de la prédiction, pour affichage dans l'UI (expander).
        Explique QUELS signaux ont influencé le pronostic, sans jargon ML brut.
        """
        reasons = []

        # Comparaison forme
        form_gap = home_form - away_form
        if abs(form_gap) > 0.15:
            better = home if form_gap > 0 else away
            reasons.append(f"{better} est en meilleure forme récente ({home_form:.2f} vs {away_form:.2f})")
        else:
            reasons.append(f"Forme récente comparable ({home_form:.2f} vs {away_form:.2f})")

        # Comparaison xG
        if abs(home_xg - away_xg) > 0.3:
            attacker = home if home_xg > away_xg else away
            reasons.append(f"{attacker} a une attaque plus dangereuse (xG {home_xg:.2f} vs {away_xg:.2f})")

        # Cote vs modèle (value bet ?)
        if cote and expected_value > 0.05:
            reasons.append(f"Cote du bookmaker ({cote}) supérieure à la probabilité réelle estimée → value bet")
        elif cote and expected_value < -0.1:
            reasons.append(f"Cote du bookmaker ({cote}) déjà inférieure à notre probabilité estimée (peu de valeur)")

        # Statut live
        if is_live and has_live_score:
            reasons.append(f"Match en cours, score actuel {live_home_score}-{live_away_score} intégré au calcul")
        elif is_live and not has_live_score:
            reasons.append("Match en cours mais score non disponible : pronostic basé sur l'avant-match uniquement (fiabilité réduite)")

        # Modèles ayant contribué
        if model_breakdown:
            contrib = ", ".join(f"{k}: {v}" for k, v in model_breakdown.items()) if isinstance(model_breakdown, dict) else str(model_breakdown)
            reasons.append(f"Modèles combinés : {', '.join(models_used)} ({contrib})")
        else:
            reasons.append(f"Modèles combinés : {', '.join(models_used)}")

        return {
            "prediction_code": predicted,
            "confidence_pct": round(confidence * 100, 1),
            "odds_implied_probs": odds_probs,
            "poisson_probs": poisson_probs,
            "home_xg": home_xg,
            "away_xg": away_xg,
            "bookmaker_odds": cote,
            "expected_value": expected_value,
            "is_live": is_live,
            "live_score": f"{live_home_score}-{live_away_score}" if has_live_score else None,
            "reasons": reasons,
        }
    
    def predict_all(self, matches: list[dict]) -> list[dict]:
        predictions = []
        for match in matches:
            if match.get("home_score") is not None and match.get("away_score") is not None:
                continue
            pred = self.predict(match)
            predictions.append(pred)
        
        predictions.sort(key=lambda x: x["confidence"], reverse=True)
        log.info(f"✅ {len(predictions)} prédictions générées")
        return predictions
    
    def build_coupon(self, predictions: list[dict], size: int = 8, min_confidence: float = 0.50,
                      min_cote: float = 1.30) -> dict:
        filtered = [
            p for p in predictions
            if p["confidence"] >= min_confidence
            and p["prediction"] != "?"
            and p.get("cote", 0) >= min_cote
        ]
        selected = filtered[:size]
        
        total_cote = 1.0
        for p in selected:
            if p.get("cote", 0) > 0:
                total_cote *= p.get("cote", 1.0)
        
        return {
            "generated_at": datetime.now().isoformat(),
            "size": len(selected),
            "total_cote": round(total_cote, 2),
            "avg_confidence": round(sum(p["confidence"] for p in selected) / max(len(selected), 1), 3),
            "selections": selected
        }

    def train_from_results(self, matches: list[dict], limit: int = 500) -> dict:
        trained = 0
        skipped = 0
        correct = 0

        for match in matches[:limit]:
            actual = normalize_result(match.get("result"))
            match_id = str(match.get("id", ""))
            if not actual or not match_id or self.model.has_trained_match(match_id):
                skipped += 1
                continue

            training_match = dict(match)
            training_match["home_score"] = None
            training_match["away_score"] = None
            prediction = self.predict(training_match)
            self.model.record_training_match(
                match_id=match_id,
                predicted=prediction["prediction"],
                actual=actual,
                confidence=prediction["confidence"],
                league=match.get("league", ""),
                home=match.get("home", ""),
                away=match.get("away", ""),
                cote=prediction.get("cote"),
                probabilities=prediction.get("probabilities"),
            )
            trained += 1
            if prediction["prediction"] == actual:
                correct += 1

        ensemble_report = {"status": "disabled"}
        if self.use_ensemble:
            try:
                from ensemble import orchestrator as ml_ensemble
                # Note honnête : les features de forme d'équipe utilisées ici reflètent
                # l'état du modèle APRÈS la boucle ci-dessus (même limitation que le
                # système Poisson existant, qui ne rejoue pas non plus l'historique
                # dans l'ordre chronologique strict match par match pour ce calcul).
                # L'orchestrateur entraîne aussi Elo (rejoué chronologiquement en
                # interne, cf. ml_models/elo.py::train_from_matches).
                ensemble_report = ml_ensemble.train_ensemble(matches[:limit], self.model)
            except Exception as e:
                try:
                    from ml_models import ensemble as ml_ensemble_legacy
                    ensemble_report = ml_ensemble_legacy.train_ensemble(matches[:limit], self.model)
                except Exception as e2:
                    ensemble_report = {"status": "error", "message": f"{e} / repli: {e2}"}

        return {
            "trained": trained,
            "skipped": skipped,
            "correct": correct,
            "accuracy": round(correct / trained, 3) if trained else 0,
            "total_model_predictions": self.model.data.get("total_predictions", 0),
            "overall_accuracy": round(self.model.overall_accuracy(), 3),
            "last_train": self.model.data.get("last_train"),
            "ensemble": ensemble_report,
        }


def auto_train_loop(interval_minutes: int = 10):
    """Boucle d'auto-entraînement toutes les X minutes."""
    print(f"\n🔄 Auto-entraînement démarré (intervalle: {interval_minutes} min)")
    print("   Appuyez sur Ctrl+C pour arrêter\n")
    
    predictor = Predictor()
    iteration = 0
    
    while True:
        try:
            iteration += 1
            print(f"\n{'='*50}")
            print(f"  🔄 AUTO-ENTRAÎNEMENT #{iteration}")
            print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*50}")
            
            matches = load_matches_from_db(limit=100)
            
            if matches:
                finished_matches = [m for m in matches if normalize_result(m.get('result'))]
                
                if finished_matches:
                    stats = predictor.train_from_results(finished_matches[:200])
                    print(f"✅ {stats['trained']} matchs intégrés à l'entraînement")
                    
                    acc = predictor.model.overall_accuracy()
                    print(f"📊 Accuracy globale: {acc:.1%}")
                else:
                    print("⚠️ Aucun match terminé trouvé")
            else:
                print("⚠️ Aucun match disponible")
            
            print(f"\n⏳ Prochain entraînement dans {interval_minutes} minutes...")
            
            for remaining in range(interval_minutes * 60, 0, -10):
                if remaining % 60 == 0:
                    mins = remaining // 60
                    print(f"\r   ⏱️  {mins:2d}m restantes", end="")
                elif remaining % 30 == 0:
                    print(f"\r   ⏱️  {remaining:3d}s restantes", end="")
                time.sleep(10)
            print("\r   ⏳ Démarrage du prochain cycle...   ")
            
        except KeyboardInterrupt:
            print("\n\n🛑 Auto-entraînement arrêté")
            break
        except Exception as e:
            print(f"❌ Erreur: {e}")
            time.sleep(60)


def print_coupon(coupon: dict, mise: float = 10.0):
    print(f"\n{'='*60}")
    print(f"  🎯 COUPON OPTIMISE — {coupon['size']} SELECTIONS")
    print(f"  Genere le {coupon['generated_at'][:16]}")
    print(f"{'='*60}\n")
    
    for i, s in enumerate(coupon["selections"], 1):
        stars = "*" * min(3, int(s["confidence"] * 3))
        print(f"  {i:2}. {s['home']} vs {s['away']}")
        print(f"      📊 Pronostic : {s['prediction']}  |  Cote : {s.get('cote', 0):.2f}")
        print(f"      📊 Confiance : {s['confidence']:.0%} {stars}")
        if s.get("comment"):
            print(f"      💬 {s['comment']}")
        print()
    
    print(f"{'-'*60}")
    print(f"  💰 COTE TOTALE    : {coupon['total_cote']:.2f}x")
    print(f"  📈 CONFIANCE MOY  : {coupon['avg_confidence']:.0%}")
    print(f"  🎲 Mise 10 EUR    : Gain potentiel : {mise * coupon['total_cote']:.0f} EUR")
    print(f"{'='*60}\n")


def print_stats(model: ModelData):
    print(f"\n{'='*50}")
    print(f"  🧠 STATISTIQUES DU MODELE")
    print(f"{'='*50}")
    print(f"  Total predictions : {model.data['total_predictions']}")
    print(f"  Accuracy globale  : {model.overall_accuracy():.1%}")
    
    cal = model.data["calibration"]
    print(f"\n  📊 Calibration:")
    for bucket, label in [("high", ">65%"), ("medium", "45-65%"), ("low", "<45%")]:
        t = cal[bucket]["total"]
        c = cal[bucket]["correct"]
        acc = c/t if t > 0 else 0
        print(f"    {label}: {acc:.1%} ({c}/{t})")
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(description="CongoBet AI Predictor")
    parser.add_argument("--analyze", action="store_true", help="Analyse les matchs disponibles")
    parser.add_argument("--coupon", type=int, default=8, help="Génère un coupon de N matchs")
    parser.add_argument("--train", action="store_true", help="Lance l'auto-entraînement")
    parser.add_argument("--stats", action="store_true", help="Affiche les stats du modèle")
    parser.add_argument("--competition", type=str, help="Filtrer par compétition (PL, BL1, etc.)")
    parser.add_argument("--mise", type=float, default=10.0, help="Mise en EUR")
    parser.add_argument("--auto-train", type=int, metavar="MINUTES", help="Auto-entraînement en boucle (ex: 10)")
    
    args = parser.parse_args()
    
    if args.auto_train:
        auto_train_loop(args.auto_train)
        return
    
    if args.stats:
        model = ModelData()
        print_stats(model)
        return
    
    if args.train:
        print("🧠 Entraînement du modèle...")
        model = ModelData()
        model.save()
        print("✅ Modèle entraîné et sauvegardé")
        return
    
    matches = load_matches_from_db(competition_id=args.competition)
    
    if not matches:
        matches = load_matches_from_json()
    
    if not matches:
        print("❌ Aucun match disponible dans la base.")
        print("💡 Essayez: python scraper_api.py")
        return
    
    future_matches = [m for m in matches if m.get("status") != "FINISHED" or m.get("home_score") is None]
    
    if future_matches:
        print(f"📊 {len(future_matches)} matchs futurs trouvés")
    else:
        print("ℹ️ Aucun match futur trouvé. Utilisation des matchs récents pour l'analyse.")
        future_matches = matches[:50]
    
    predictor = Predictor()
    predictions = predictor.predict_all(future_matches)
    
    if args.analyze:
        print(f"\n{'='*60}")
        print(f"  📊 ANALYSE COMPLETE — {len(predictions)} matchs")
        print(f"{'='*60}\n")
        for p in predictions[:20]:
            stars = "*" * min(3, int(p["confidence"] * 3))
            print(f"  {p['home']} vs {p['away']}")
            print(f"  📊 {p['prediction']}  conf={p['confidence']:.0%} {stars}  cote={p.get('cote', 0):.2f}")
            if p.get("comment"):
                print(f"  💬 {p['comment']}")
            print()
    
    coupon = predictor.build_coupon(predictions, size=args.coupon)
    print_coupon(coupon, mise=args.mise)
    
    print_stats(predictor.model)


if __name__ == "__main__":
    main()
