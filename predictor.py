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
import os
import io

# Forcer l'encodage UTF-8 sur la console Windows : sans ça, tout print()
# contenant un caractere hors cp1252 (emoji, box-drawing...) peut planter
# avec "UnicodeEncodeError: 'charmap' codec can't encode character".
#
# IMPORTANT : ce bloc ne doit s'exécuter QUE si predictor.py est lancé
# directement en CLI (python predictor.py ...), jamais sur un simple
# `import predictor`/`from predictor import Predictor` — sinon, importé
# depuis l'intérieur d'un process Streamlit (pronostics.py, common.py,
# congobet_combos.py, backtest_ui.py, chatbot_ai.py y font tous appel), ce
# remplacement global de sys.stdout par un TextIOWrapper entre en conflit
# avec le cycle de ré-exécution de Streamlit et provoque des erreurs
# aléatoires "I/O operation on closed file" (observées en usage réel). Voir
# la même correction faite sur app_dashboard.py. Le code déplacé plus bas,
# dans `if __name__ == "__main__":`, préserve le comportement CLI original.

import json
import sqlite3
import math
import random
import argparse
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict, OrderedDict

log = logging.getLogger("predictor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_PATH = Path("congobet.db")
JSON_PATH = Path("congobet_matches.json")
MODEL_PATH = Path("model_data.json")
NN_WEIGHTS_PATH = Path("nn_weights.json")

# ---------------------------------------------------------------------------
# Capacité du modèle (mémoire/historique — pas des "paramètres" au sens ML)
# ---------------------------------------------------------------------------
MAX_HISTORY = 100_000       # nombre max de matchs conservés dans l'historique d'entraînement
MAX_TEAMS_TRACKED = 1000    # nombre max d'équipes suivies simultanément (éviction LRU au-delà)
CALIBRATION_BUCKETS = 30    # granularité de calibration confiance -> précision réelle (3% par bucket)

# ---------------------------------------------------------------------------
# Réseau de neurones interne (feedforward, backprop manuelle, zéro dépendance)
# ---------------------------------------------------------------------------
NN_FEATURE_NAMES = [
    "odds_p1", "odds_px", "odds_p2",
    "poisson_p1", "poisson_px", "poisson_p2",
    "home_xg", "away_xg",
    "home_form", "away_form", "form_delta",
    "league_boost", "is_live",
]
NN_INPUT_SIZE = len(NN_FEATURE_NAMES)   # 13
NN_HIDDEN1 = 64
NN_HIDDEN2 = 32
NN_OUTPUT_SIZE = 3                       # P(1), P(X), P(2)
NN_BLEND_WEIGHT = 0.30                   # poids du NN dans le blend final (le reste = Poisson+cotes+forme)
NN_MIN_TRAINING_SAMPLES = 30             # en dessous, on refuse d'entraîner (résultats non fiables)


def build_nn_features(odds_probs: dict, poisson_probs: dict, home_xg: float, away_xg: float,
                       home_form: float, away_form: float, league_boost: float,
                       is_live: bool) -> list:
    """Construit le vecteur de features consommé par le réseau de neurones.
    Toujours dans le même ordre que NN_FEATURE_NAMES."""
    return [
        odds_probs.get("1", 0.33), odds_probs.get("X", 0.34), odds_probs.get("2", 0.33),
        poisson_probs.get("1", 0.33), poisson_probs.get("X", 0.34), poisson_probs.get("2", 0.33),
        home_xg, away_xg,
        home_form, away_form, home_form - away_form,
        league_boost, 1.0 if is_live else 0.0,
    ]


class NeuralNet:
    """
    Petit réseau feedforward (13 -> 64 -> 32 -> 3, ~3075 poids) entraîné par
    rétropropagation classique (cross-entropy + softmax), implémenté en Python
    pur (listes, pas de numpy) pour ne rien ajouter aux dépendances du projet.

    Honnêteté sur les limites : avec seulement quelques centaines/milliers de
    matchs d'historique, un réseau de cette taille peut sur-apprendre (retenir
    le bruit plutôt que le signal). La régularisation L2 et le fait qu'il ne
    pèse que 30% dans le blend final limitent ce risque, mais ne l'éliminent
    pas — à surveiller via `last_accuracy` après entraînement.
    """

    def __init__(self, input_size=NN_INPUT_SIZE, hidden1=NN_HIDDEN1,
                 hidden2=NN_HIDDEN2, output_size=NN_OUTPUT_SIZE, seed=42):
        self.input_size = input_size
        self.hidden1 = hidden1
        self.hidden2 = hidden2
        self.output_size = output_size

        rnd = random.Random(seed)

        def he_init(n_in, n_out):
            scale = math.sqrt(2.0 / n_in)
            return [[rnd.gauss(0.0, scale) for _ in range(n_out)] for _ in range(n_in)]

        self.W1 = he_init(input_size, hidden1)
        self.b1 = [0.0] * hidden1
        self.W2 = he_init(hidden1, hidden2)
        self.b2 = [0.0] * hidden2
        self.W3 = he_init(hidden2, output_size)
        self.b3 = [0.0] * output_size

        self.feature_mean = [0.0] * input_size
        self.feature_std = [1.0] * input_size
        self.trained_epochs = 0
        self.trained_samples = 0
        self.last_loss = None
        self.last_accuracy = None

    def total_weights(self) -> int:
        return (self.input_size * self.hidden1 + self.hidden1
                + self.hidden1 * self.hidden2 + self.hidden2
                + self.hidden2 * self.output_size + self.output_size)

    def _normalize(self, x_raw):
        return [
            (x_raw[i] - self.feature_mean[i]) / (self.feature_std[i] or 1.0)
            for i in range(len(x_raw))
        ]

    @staticmethod
    def _relu(v):
        return [val if val > 0.0 else 0.0 for val in v]

    @staticmethod
    def _relu_deriv(v):
        return [1.0 if val > 0.0 else 0.0 for val in v]

    @staticmethod
    def _softmax(v):
        m = max(v)
        exps = [math.exp(val - m) for val in v]
        s = sum(exps) or 1e-9
        return [e / s for e in exps]

    @staticmethod
    def _mat_vec(W, x, b):
        # W: liste de n_in lignes de longueur n_out ; x: vecteur n_in ; b: biais n_out
        out = list(b)
        for i, xi in enumerate(x):
            if xi == 0.0:
                continue
            row = W[i]
            for j in range(len(row)):
                out[j] += xi * row[j]
        return out

    def _forward(self, x_raw):
        x = self._normalize(x_raw)
        z1 = self._mat_vec(self.W1, x, self.b1)
        a1 = self._relu(z1)
        z2 = self._mat_vec(self.W2, a1, self.b2)
        a2 = self._relu(z2)
        z3 = self._mat_vec(self.W3, a2, self.b3)
        a3 = self._softmax(z3)
        return x, z1, a1, z2, a2, z3, a3

    def predict_proba(self, x_raw) -> list:
        """Retourne [P(1), P(X), P(2)]."""
        *_, a3 = self._forward(x_raw)
        return a3

    def _train_batch(self, X_batch, y_idx_batch, lr, l2):
        n = len(X_batch)
        gW1 = [[0.0] * self.hidden1 for _ in range(self.input_size)]
        gb1 = [0.0] * self.hidden1
        gW2 = [[0.0] * self.hidden2 for _ in range(self.hidden1)]
        gb2 = [0.0] * self.hidden2
        gW3 = [[0.0] * self.output_size for _ in range(self.hidden2)]
        gb3 = [0.0] * self.output_size

        total_loss = 0.0
        correct = 0

        for x_raw, y_idx in zip(X_batch, y_idx_batch):
            x, z1, a1, z2, a2, z3, a3 = self._forward(x_raw)

            p = max(a3[y_idx], 1e-9)
            total_loss += -math.log(p)
            if max(range(self.output_size), key=lambda i: a3[i]) == y_idx:
                correct += 1

            # Dérivée combinée softmax + cross-entropy
            dz3 = list(a3)
            dz3[y_idx] -= 1.0

            for i in range(self.hidden2):
                ai = a2[i]
                if ai != 0.0:
                    row = gW3[i]
                    for j in range(self.output_size):
                        row[j] += ai * dz3[j]
            for j in range(self.output_size):
                gb3[j] += dz3[j]

            da2 = [0.0] * self.hidden2
            for i in range(self.hidden2):
                s = 0.0
                row = self.W3[i]
                for j in range(self.output_size):
                    s += row[j] * dz3[j]
                da2[i] = s
            relu_d2 = self._relu_deriv(z2)
            dz2 = [da2[i] * relu_d2[i] for i in range(self.hidden2)]

            for i in range(self.hidden1):
                ai = a1[i]
                if ai != 0.0:
                    row = gW2[i]
                    for j in range(self.hidden2):
                        row[j] += ai * dz2[j]
            for j in range(self.hidden2):
                gb2[j] += dz2[j]

            da1 = [0.0] * self.hidden1
            for i in range(self.hidden1):
                s = 0.0
                row = self.W2[i]
                for j in range(self.hidden2):
                    s += row[j] * dz2[j]
                da1[i] = s
            relu_d1 = self._relu_deriv(z1)
            dz1 = [da1[i] * relu_d1[i] for i in range(self.hidden1)]

            for i in range(self.input_size):
                xi = x[i]
                if xi != 0.0:
                    row = gW1[i]
                    for j in range(self.hidden1):
                        row[j] += xi * dz1[j]
            for j in range(self.hidden1):
                gb1[j] += dz1[j]

        inv_n = 1.0 / n
        for i in range(self.input_size):
            row_w, row_g = self.W1[i], gW1[i]
            for j in range(self.hidden1):
                row_w[j] -= lr * (row_g[j] * inv_n + l2 * row_w[j])
        for j in range(self.hidden1):
            self.b1[j] -= lr * (gb1[j] * inv_n)

        for i in range(self.hidden1):
            row_w, row_g = self.W2[i], gW2[i]
            for j in range(self.hidden2):
                row_w[j] -= lr * (row_g[j] * inv_n + l2 * row_w[j])
        for j in range(self.hidden2):
            self.b2[j] -= lr * (gb2[j] * inv_n)

        for i in range(self.hidden2):
            row_w, row_g = self.W3[i], gW3[i]
            for j in range(self.output_size):
                row_w[j] -= lr * (row_g[j] * inv_n + l2 * row_w[j])
        for j in range(self.output_size):
            self.b3[j] -= lr * (gb3[j] * inv_n)

        return total_loss / n, correct / n

    def fit(self, X: list, y_idx: list, epochs=30, lr=0.03, batch_size=32, l2=1e-4, seed=42) -> dict:
        n = len(X)
        if n < NN_MIN_TRAINING_SAMPLES:
            return {"status": "insufficient_data", "samples": n, "minimum_recommended": NN_MIN_TRAINING_SAMPLES}

        self.feature_mean = [sum(row[i] for row in X) / n for i in range(self.input_size)]
        self.feature_std = []
        for i in range(self.input_size):
            mean = self.feature_mean[i]
            var = sum((row[i] - mean) ** 2 for row in X) / n
            self.feature_std.append(math.sqrt(var) or 1.0)

        rnd = random.Random(seed)
        indices = list(range(n))
        last_loss, last_acc = None, None
        t0 = time.time()

        for epoch in range(epochs):
            rnd.shuffle(indices)
            epoch_loss, epoch_acc, n_batches = 0.0, 0.0, 0
            for start in range(0, n, batch_size):
                batch_idx = indices[start:start + batch_size]
                X_batch = [X[i] for i in batch_idx]
                y_batch = [y_idx[i] for i in batch_idx]
                loss, acc = self._train_batch(X_batch, y_batch, lr=lr, l2=l2)
                epoch_loss += loss
                epoch_acc += acc
                n_batches += 1
            last_loss = epoch_loss / max(n_batches, 1)
            last_acc = epoch_acc / max(n_batches, 1)
            self.trained_epochs += 1
            log.info(f"  🧬 Epoch {epoch + 1}/{epochs} — loss={last_loss:.4f} acc={last_acc:.1%}")

        self.trained_samples = n
        self.last_loss = round(last_loss, 4)
        self.last_accuracy = round(last_acc, 4)
        elapsed = round(time.time() - t0, 1)
        return {
            "status": "trained",
            "epochs": epochs,
            "samples": n,
            "final_loss": self.last_loss,
            "final_accuracy": self.last_accuracy,
            "total_weights": self.total_weights(),
            "elapsed_seconds": elapsed,
        }

    def to_dict(self) -> dict:
        return {
            "input_size": self.input_size, "hidden1": self.hidden1,
            "hidden2": self.hidden2, "output_size": self.output_size,
            "W1": self.W1, "b1": self.b1, "W2": self.W2, "b2": self.b2,
            "W3": self.W3, "b3": self.b3,
            "feature_mean": self.feature_mean, "feature_std": self.feature_std,
            "trained_epochs": self.trained_epochs, "trained_samples": self.trained_samples,
            "last_loss": self.last_loss, "last_accuracy": self.last_accuracy,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NeuralNet":
        obj = cls(d["input_size"], d["hidden1"], d["hidden2"], d["output_size"])
        obj.W1, obj.b1 = d["W1"], d["b1"]
        obj.W2, obj.b2 = d["W2"], d["b2"]
        obj.W3, obj.b3 = d["W3"], d["b3"]
        obj.feature_mean = d.get("feature_mean", obj.feature_mean)
        obj.feature_std = d.get("feature_std", obj.feature_std)
        obj.trained_epochs = d.get("trained_epochs", 0)
        obj.trained_samples = d.get("trained_samples", 0)
        obj.last_loss = d.get("last_loss")
        obj.last_accuracy = d.get("last_accuracy")
        return obj

    def save(self, path: Path = NN_WEIGHTS_PATH):
        # Même écriture atomique que ModelData.save() — voir le commentaire
        # là-bas pour le pourquoi (protection contre les écritures
        # concurrentes qui corrompent le fichier).
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f)
        os.replace(tmp_path, path)

    @classmethod
    def load(cls, path: Path = NN_WEIGHTS_PATH):
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("input_size") != NN_INPUT_SIZE:
                log.warning("⚠️ Format de nn_weights.json incompatible (features modifiées) — réseau réinitialisé")
                return None
            return cls.from_dict(d)
        except Exception as e:
            log.warning(f"⚠️ Impossible de charger nn_weights.json ({e}) — réseau réinitialisé")
            return None


# ---------------------------------------------------------------------------
# Gestion stricte du cycle de vie des matchs
# ---------------------------------------------------------------------------
def parse_match_datetime(value):
    """Convertit une date de match en datetime UTC-aware."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            dt = None
            for fmt in (
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
            ):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    pass
            if dt is None:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def match_start_datetime(match: dict):
    for key in ("start_time", "utc_date", "date", "match_date", "kickoff"):
        dt = parse_match_datetime(match.get(key))
        if dt is not None:
            return dt
    return None


def match_is_live(match: dict) -> bool:
    status = str(match.get("status") or "").strip().upper()
    return bool(match.get("is_live")) or status in {
        "LIVE", "IN_PLAY", "PLAYING", "1H", "2H", "HT", "PAUSED"
    }


def match_is_finished(match: dict) -> bool:
    status = str(match.get("status") or "").strip().upper()
    if status in {
        "FINISHED", "FT", "ENDED", "END", "COMPLETED",
        "POST_MATCH", "AWARDED", "CANCELLED", "CANCELED", "ABANDONED"
    }:
        return True
    home_score = match.get("home_score")
    away_score = match.get("away_score")
    if (home_score is not None and away_score is not None
            and status not in {"LIVE", "IN_PLAY", "PLAYING", "1H", "2H", "HT", "PAUSED"}):
        return True
    return False


def filter_upcoming_matches(matches: list[dict], now=None):
    """Retourne (futurs, live, passés) et bloque les matchs anciens."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    future, live, past = [], [], []
    seen = set()
    for original in matches:
        match = dict(original)
        match_id = str(match.get("id") or match.get("match_id") or "").strip()
        start_dt = match_start_datetime(match)
        is_live = match_is_live(match)
        is_finished = match_is_finished(match)

        home = str(match.get("home") or "").strip().lower()
        away = str(match.get("away") or "").strip().lower()
        key = match_id or f"{home}|{away}|{start_dt.isoformat() if start_dt else ''}"
        if key in seen:
            continue
        seen.add(key)

        if is_live and not is_finished:
            live.append(match)
        elif start_dt is not None and start_dt > now and not is_finished:
            future.append(match)
        else:
            # Date absente/invalide = on ne prend aucun risque : pas de prédiction.
            past.append(match)

    future.sort(key=lambda m: match_start_datetime(m) or datetime.max.replace(tzinfo=timezone.utc))
    live.sort(key=lambda m: match_start_datetime(m) or datetime.min.replace(tzinfo=timezone.utc))
    past.sort(key=lambda m: match_start_datetime(m) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return future, live, past

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
    
    query += f", {date_col} as start_time"
    if has_status:
        query += ", status"
    
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
        # team_form géré comme LRU (OrderedDict) pour appliquer MAX_TEAMS_TRACKED
        # sans perdre la compatibilité avec un fichier model_data.json existant.
        self.data["team_form"] = OrderedDict(self.data.get("team_form", {}))
    
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
        # OrderedDict -> dict standard pour la sérialisation JSON
        to_dump = dict(self.data)
        to_dump["team_form"] = dict(self.data["team_form"])
        # Écriture atomique : on écrit d'abord dans un fichier temporaire,
        # puis on le fait glisser à la place de model_data.json en une seule
        # opération système (os.replace). Sans ça, si deux processus
        # écrivent en même temps dans le même fichier (ex: le cycle
        # automatique de l'appli Streamlit ET une commande CLI lancée en
        # parallèle), l'un peut couper l'écriture de l'autre en plein
        # milieu — produisant un JSON à moitié écrit, donc corrompu et
        # illisible au prochain chargement. os.replace() garantit que le
        # fichier final est TOUJOURS soit l'ancienne version complète, soit
        # la nouvelle version complète — jamais un mélange des deux.
        tmp_path = MODEL_PATH.with_suffix(MODEL_PATH.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(to_dump, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, MODEL_PATH)

    def _touch_team(self, team: str, result_for_team: str):
        """Met à jour la forme d'une équipe et la remonte en tête de la LRU.
        Si le nombre d'équipes suivies dépasse MAX_TEAMS_TRACKED, l'équipe la
        moins récemment mise à jour est évincée (capacité mémoire bornée pour
        pouvoir suivre jusqu'à ~1000 équipes sans croissance illimitée)."""
        if team not in self.data["team_form"]:
            self.data["team_form"][team] = []
        self.data["team_form"][team] = (self.data["team_form"][team] + [result_for_team])[-10:]
        self.data["team_form"].move_to_end(team)
        while len(self.data["team_form"]) > MAX_TEAMS_TRACKED:
            evicted, _ = self.data["team_form"].popitem(last=False)
            log.info(f"♻️ Équipe évincée du suivi (limite {MAX_TEAMS_TRACKED} atteinte) : {evicted}")

    def _calibration_bucket(self, confidence: float) -> str:
        """Bucket fin (granularité CALIBRATION_BUCKETS) en plus des 3 buckets
        historiques high/medium/low, pour une calibration plus précise."""
        idx = min(CALIBRATION_BUCKETS - 1, int(confidence * CALIBRATION_BUCKETS))
        return f"b{idx:02d}"

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
            self._touch_team(team, result_for_team)
        
        self.save()

    def has_trained_match(self, match_id: str) -> bool:
        return any(str(item.get("match_id")) == str(match_id) for item in self.data.get("history", []))

    def record_training_match(self, match_id: str, predicted: str, actual: str,
                              confidence: float, league: str, home: str, away: str,
                              cote: float = None, probabilities: dict = None,
                              nn_features: list = None, source: str = "unknown",
                              match_date: str = None, defer_save: bool = False):
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

        # Calibration fine (granularité CALIBRATION_BUCKETS), stockée à part
        # pour ne pas casser la compatibilité du format high/medium/low existant.
        fine = self.data.setdefault("calibration_fine", {})
        fb = fine.setdefault(self._calibration_bucket(confidence), {"correct": 0, "total": 0})
        fb["total"] += 1
        if correct:
            fb["correct"] += 1

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
            self._touch_team(team, result_for_team)

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
            "nn_features": nn_features,  # snapshot des features pré-match, pour entraîner le NN plus tard
            "source": source,  # "real_odds" | "real_no_odds" | "historical_generic" | "unknown"
            "match_date": match_date,  # ISO string si connue — absente avant ce correctif
        })
        # Historique porté à MAX_HISTORY (100 000) au lieu de 5000, pour
        # permettre un entraînement sur un volume de matchs beaucoup plus large.
        self.data["history"] = self.data["history"][-MAX_HISTORY:]
        self.data["last_train"] = datetime.now().isoformat()
        # defer_save=True (utilisé par train_from_results en boucle) : laisse
        # l'appelant sauvegarder UNE SEULE FOIS à la fin du lot au lieu
        # d'écrire tout model_data.json à chaque match — sans ça, entraîner
        # ~3000 matchs réécrit le fichier ~3000 fois, un fichier qui grossit
        # à chaque itération (coût cumulé en O(N²), pas O(N)). Comportement
        # par défaut (defer_save=False) inchangé pour les autres appelants
        # (ex: record_result, appelé au règlement d'un seul coupon à la fois).
        if not defer_save:
            self.save()

    def reconcile(self, dry_run: bool = False) -> dict:
        """
        Corrige le désynchronisation possible entre `total_predictions` (un
        compteur cumulatif jamais recalculé) et le contenu réel de `history`
        (une liste tronquée à MAX_HISTORY) — voir l'audit Partie B du prompt
        maître : un match_id peut sortir de la fenêtre tronquée puis être
        recompté une seconde fois par un cycle d'entraînement ultérieur,
        gonflant artificiellement le compteur affiché ("prédictions
        vérifiées").

        `history` reste la SEULE source de vérité après cet appel :
        - dédoublonne par match_id (garde la première occurrence)
        - recalcule total_predictions / correct_predictions / calibration /
          calibration_fine / league_accuracy UNIQUEMENT à partir de ce qui
          reste dans history (donc à partir de vrais matchs traçables)
        - team_form n'est PAS touché ici : il faudrait rejouer l'historique
          dans l'ordre chronologique pour le reconstruire fidèlement, ce qui
          dépasse le cadre de ce correctif (compteur affiché uniquement).

        dry_run=True calcule le rapport sans rien modifier ni sauvegarder —
        utile pour prévisualiser l'ampleur du problème avant d'agir.
        """
        before = {
            "total_predictions": self.data.get("total_predictions", 0),
            "correct_predictions": self.data.get("correct_predictions", 0),
            "history_len": len(self.data.get("history", [])),
        }

        seen_ids = set()
        deduped = []
        duplicates_removed = 0
        for h in self.data.get("history", []):
            mid = str(h.get("match_id") or "")
            if not mid:
                continue  # entrée sans ID fiable : jamais comptée après réconciliation
            if mid in seen_ids:
                duplicates_removed += 1
                continue
            seen_ids.add(mid)
            deduped.append(h)

        new_calibration = {
            "high": {"correct": 0, "total": 0},
            "medium": {"correct": 0, "total": 0},
            "low": {"correct": 0, "total": 0},
        }
        new_calibration_fine = {}
        new_league_accuracy = {}
        correct_count = 0

        for h in deduped:
            correct = bool(h.get("correct"))
            confidence = float(h.get("confidence") or 0.0)
            league = h.get("league") or "N/A"

            if correct:
                correct_count += 1

            bucket = "high" if confidence >= 0.65 else "medium" if confidence >= 0.45 else "low"
            new_calibration[bucket]["total"] += 1
            if correct:
                new_calibration[bucket]["correct"] += 1

            fine_bucket = self._calibration_bucket(confidence)
            fb = new_calibration_fine.setdefault(fine_bucket, {"correct": 0, "total": 0})
            fb["total"] += 1
            if correct:
                fb["correct"] += 1

            ls = new_league_accuracy.setdefault(league, {"correct": 0, "total": 0})
            ls["total"] += 1
            if correct:
                ls["correct"] += 1

        after = {
            "total_predictions": len(deduped),
            "correct_predictions": correct_count,
            "history_len": len(deduped),
        }

        report = {
            "before": before,
            "after": after,
            "duplicates_removed": duplicates_removed,
            "entries_without_id_dropped": before["history_len"] - duplicates_removed - len(deduped),
            "counter_drift_corrected": before["total_predictions"] - after["total_predictions"],
        }

        if not dry_run:
            self.data["history"] = deduped
            self.data["total_predictions"] = after["total_predictions"]
            self.data["correct_predictions"] = after["correct_predictions"]
            self.data["calibration"] = new_calibration
            self.data["calibration_fine"] = new_calibration_fine
            self.data["league_accuracy"] = new_league_accuracy
            self.save()

        return report

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
    def __init__(self, use_ensemble: bool = True, use_neural_net: bool = True):
        self.model = ModelData()
        self.use_ensemble = use_ensemble
        self.use_neural_net = use_neural_net
        self.neural_net = NeuralNet.load(NN_WEIGHTS_PATH) or NeuralNet()
    
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

        # --- Réseau de neurones interne (13 -> 64 -> 32 -> 3, ~3075 poids) ---
        # Contribue uniquement s'il a déjà été entraîné (trained_epochs > 0) ;
        # sinon on ignore silencieusement et on garde le blend Poisson+cotes+forme,
        # comme pour l'ensemble ML externe plus bas.
        league_boost = self.model.get_league_boost(league)
        nn_features = build_nn_features(
            odds_probs, poisson_probs, home_xg, away_xg,
            home_form, away_form, league_boost, is_live,
        )
        nn_used = False
        nn_probs = None
        if self.use_neural_net and self.neural_net is not None and self.neural_net.trained_epochs > 0:
            nn_raw = self.neural_net.predict_proba(nn_features)
            nn_probs = {"1": nn_raw[0], "X": nn_raw[1], "2": nn_raw[2]}
            blended = {
                k: (1 - NN_BLEND_WEIGHT) * final_probs.get(k, 0.33) + NN_BLEND_WEIGHT * nn_probs.get(k, 0.33)
                for k in ("1", "X", "2")
            }
            total_blend = sum(blended.values()) or 1.0
            final_probs = {k: round(v / total_blend, 4) for k, v in blended.items()}
            nn_used = True

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

        # --- Ensemble ML (XGBoost / LightGBM / Elo / Dixon-Coles / meta-learner) ---
        # Si les sous-modèles ne sont pas encore entraînés (pas assez de données)
        # ou si les dépendances/modules ne sont pas installés (ex: `ensemble/` et
        # `ml_models/` absents de l'environnement), on retombe silencieusement sur
        # final_probs tel quel (Poisson + cotes + forme + réseau interne) — jamais
        # de plantage. Le réseau de neurones interne (celui de ce fichier, sans
        # dépendance externe) reste TOUJOURS dans model_breakdown/models_used,
        # que l'orchestrateur externe tourne ou non : il ne doit jamais disparaître
        # de l'explication "🧠 Pourquoi ce pronostic ?" affichée côté dashboard.
        model_breakdown = {}
        models_used = ["poisson"]
        if nn_used:
            models_used.append("neural_net_interne")
            model_breakdown["neural_net_interne"] = {
                "probabilities": {k: round(v, 4) for k, v in nn_probs.items()},
                "weight": NN_BLEND_WEIGHT,
            }
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
                model_breakdown = {**model_breakdown, **(ensemble_result.get("model_breakdown") or {})}
                models_used = models_used + [m for m in ensemble_result.get("models_used", []) if m not in models_used]
            except Exception:
                try:
                    from ml_models import ensemble as ml_ensemble_legacy
                    ensemble_result = ml_ensemble_legacy.predict_ensemble(match, self.model, final_probs)
                    final_probs = dict(ensemble_result["probabilities"])
                    model_breakdown = {**model_breakdown, **(ensemble_result.get("model_breakdown") or {})}
                    models_used = models_used + [m for m in ensemble_result.get("models_used", []) if m not in models_used]
                except Exception:
                    pass
        model_breakdown = model_breakdown or None

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
        top_exact_score = exact_scores[0]["score"] if exact_scores else None
        
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
            "exact_score_predicted": top_exact_score,
            "home_form": home_form,
            "away_form": away_form,
            "nn_features": nn_features,
            "nn_used": nn_used,
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

        # Réseau de neurones interne
        if "neural_net_interne" in models_used:
            reasons.append(
                f"Réseau de neurones interne intégré ({self.neural_net.total_weights()} poids, "
                f"entraîné sur {self.neural_net.trained_samples} matchs, "
                f"{self.neural_net.trained_epochs} époques cumulées)"
            )

        # Modèles ayant contribué (résumé lisible : nom + poids dans le blend,
        # pas le dict brut — le détail complet reste disponible via model_breakdown
        # pour l'UI qui veut l'afficher elle-même, ex: pronostics.py).
        if model_breakdown and isinstance(model_breakdown, dict):
            parts = []
            for name, detail in model_breakdown.items():
                weight = detail.get("weight") if isinstance(detail, dict) else None
                parts.append(f"{name} ({weight:.0%})" if isinstance(weight, (int, float)) else name)
            reasons.append(f"Modèles combinés : {', '.join(parts) if parts else ', '.join(models_used)}")
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
        """Génère des prédictions uniquement pour des matchs futurs."""
        predictions = []
        future_matches, _live_matches, _past_matches = filter_upcoming_matches(matches)
        for match in future_matches:
            pred = self.predict(match)
            predictions.append(pred)

        predictions.sort(key=lambda x: x["confidence"], reverse=True)
        log.info(f"✅ {len(predictions)} prédictions générées sur matchs futurs")
        return predictions

    def build_coupon(self, predictions: list[dict], size: int = 8, min_confidence: float = 0.50,
                      min_cote: float = 1.30, min_expected_value: float = 0.0, label: str = None) -> dict:
        """
        IMPORTANT — pourquoi min_expected_value existe :
        Confiance élevée ne veut PAS dire bon pari. Un pick à 52% de confiance
        avec une cote à 1.39 a une valeur espérée de 0.52*1.39-1 = -27.7% : le
        modèle "a raison" plus d'une fois sur deux, mais la cote ne compense
        pas assez ce risque pour être rentable sur la durée. Avant ce
        correctif, cette fonction ne triait QUE par confiance et ignorait
        totalement la cote — elle pouvait donc remplir un coupon entier de
        paris structurellement perdants même quand le modèle "avait raison"
        sur le favori.

        On priorise maintenant les picks à valeur espérée positive (l'edge
        réel par rapport au marché), et seulement s'il n'y en a pas assez
        pour atteindre `size`, on complète avec les picks restants (triés
        par confiance) — ceux-ci sont signalés séparément dans le retour
        (`fallback_count`) car ils n'ont PAS d'edge statistique démontré.

        Aucune garantie de gain pour autant : la valeur espérée est une
        moyenne de long terme sur beaucoup de paris indépendants, pas une
        prédiction sur UN match ni sur UN ticket combiné (où il suffit d'un
        seul échec pour tout perdre — voir avg_confidence puissance size).
        """
        filtered = [
            p for p in predictions
            if p["confidence"] >= min_confidence
            and p["prediction"] != "?"
            and p.get("cote", 0) >= min_cote
        ]

        value_bets = sorted(
            (p for p in filtered if p.get("expected_value", 0) is not None and p.get("expected_value", -1) >= min_expected_value),
            key=lambda p: p.get("expected_value", -1),
            reverse=True,
        )
        value_ids = {id(p) for p in value_bets}
        fallback_pool = sorted(
            (p for p in filtered if id(p) not in value_ids),
            key=lambda p: p["confidence"],
            reverse=True,
        )

        selected = value_bets[:size]
        value_bet_count = len(selected)
        if len(selected) < size:
            selected = selected + fallback_pool[:size - len(selected)]
        fallback_count = len(selected) - value_bet_count

        total_cote = 1.0
        for p in selected:
            if p.get("cote", 0) > 0:
                total_cote *= p.get("cote", 1.0)

        avg_ev = round(sum(p.get("expected_value", 0) or 0 for p in selected) / max(len(selected), 1), 4)

        return {
            "label": label or f"Ticket {size} matchs",
            "generated_at": datetime.now().isoformat(),
            "size": len(selected),
            "total_cote": round(total_cote, 2),
            "avg_confidence": round(sum(p["confidence"] for p in selected) / max(len(selected), 1), 3),
            "avg_expected_value": avg_ev,
            "value_bet_count": value_bet_count,
            "fallback_count": fallback_count,
            "selections": selected
        }

    def build_multiple_coupons(self, predictions: list[dict], group_size: int = 10,
                                min_confidence: float = 0.0, min_cote: float = 1.10,
                                max_coupons: int | None = None) -> list[dict]:
        """Découpe TOUS les matchs éligibles (triés par confiance décroissante,
        comme predict_all() les fournit déjà) en plusieurs coupons de
        `group_size` matchs chacun : le coupon n°1 regroupe les matchs les
        plus sûrs, le n°2 les suivants les plus sûrs, etc. — jusqu'à épuiser
        les matchs disponibles (ou max_coupons si fixé).

        min_confidence/min_cote sont volontairement plus permissifs que
        build_coupon() par défaut : l'objectif ici n'est pas de ne garder que
        les meilleurs, mais de RÉPARTIR tous les matchs valables en plusieurs
        tickets classés du plus sûr au plus risqué, pour laisser le choix.
        """
        filtered = [
            p for p in predictions
            if p["confidence"] >= min_confidence
            and p["prediction"] != "?"
            and p.get("cote", 0) >= min_cote
        ]

        coupons = []
        for i in range(0, len(filtered), group_size):
            if max_coupons is not None and len(coupons) >= max_coupons:
                break
            chunk = filtered[i:i + group_size]
            if len(chunk) < group_size:
                break  # dernier paquet incomplet : pas assez de matchs pour un coupon plein

            total_cote = 1.0
            for p in chunk:
                if p.get("cote", 0) > 0:
                    total_cote *= p.get("cote", 1.0)

            avg_conf = sum(p["confidence"] for p in chunk) / len(chunk)
            risk_label = (
                "🟢 Le plus sûr" if len(coupons) == 0 else
                "🟡 Modéré" if len(coupons) == 1 else
                "🟠 Risqué" if len(coupons) == 2 else
                "🔴 Très risqué"
            )

            coupons.append({
                "label": f"Coupon {len(coupons) + 1} — {risk_label}",
                "generated_at": datetime.now().isoformat(),
                "size": len(chunk),
                "total_cote": round(total_cote, 2),
                "avg_confidence": round(avg_conf, 3),
                "selections": chunk,
            })

        return coupons

    def train_from_results(self, matches: list[dict], limit: int = 500) -> dict:
        trained = 0
        skipped = 0
        correct = 0

        for match in matches[:limit]:
            actual = normalize_result(match.get("result"))
            match_id = str(match.get("id", ""))
            home = str(match.get("home") or "").strip()
            away = str(match.get("away") or "").strip()
            if not actual or not match_id or self.model.has_trained_match(match_id):
                skipped += 1
                continue
            if not home or not away:
                # Équipe manquante = donnée corrompue à la source (import
                # partiel, ligne mal parsée...) — jamais un vrai match
                # vérifiable. Sans ce garde-fou, ces entrées entraient dans
                # l'historique avec une ligue affichée mais aucune équipe
                # ("? vs ?"), impossibles à vérifier et faussement comptées
                # comme une prédiction correcte/incorrecte. Cas réel observé
                # et corrigé lors de l'audit (Ligue des Champions, Europa
                # Conference League — ligue présente, équipes vides).
                skipped += 1
                continue

            # Provenance : détermine la fiabilité réelle de ce match pour la
            # traçabilité (voir ModelData.record_training_match). Trois cas :
            # - "historical_generic" : historical_results.db (football-data.org),
            #   préfixe id "hist_", jamais de cotes réelles (voir historical_data.py)
            # - "real_odds" : vrai match CongoBet/1xBet/PremierBet avec au moins
            #   une cote réelle en base — le cas le plus fiable
            # - "real_no_odds" : match réel mais sans cote trouvée (rare, à
            #   surveiller — le predictor retombe sur des probabilités par défaut)
            if match_id.startswith("hist_"):
                source = "historical_generic"
            elif match.get("markets"):
                source = "real_odds"
            else:
                source = "real_no_odds"
            match_date = match.get("start_time") or match.get("date") or None

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
                nn_features=prediction.get("nn_features"),
                source=source,
                match_date=match_date,
                defer_save=True,
            )
            trained += 1
            if prediction["prediction"] == actual:
                correct += 1

        # Une seule sauvegarde pour tout le lot (voir defer_save ci-dessus) —
        # avant, chaque match du lot réécrivait model_data.json en entier ;
        # pour ~3000 matchs, ça pouvait prendre plusieurs minutes rien qu'en
        # I/O disque. Toujours sauvegarder même si trained==0, pour ne pas
        # perdre les mises à jour de last_train / calibration éventuelles.
        if trained > 0:
            self.model.save()

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
            "teams_tracked": len(self.model.data.get("team_form", {})),
            "history_size": len(self.model.data.get("history", [])),
        }

    def train_neural_net(self, epochs: int = 30, lr: float = 0.03, batch_size: int = 32, l2: float = 1e-4,
                          max_samples: int = 5000) -> dict:
        """Entraîne le réseau de neurones interne sur les features déjà
        capturées dans l'historique (self.model.data['history']). Ne
        nécessite pas de recharger les matchs : il réutilise ce qui a été
        accumulé lors des précédents --train / auto-entraînements.

        max_samples borne le coût d'un appel : cette méthode est pensée pour
        être rappelée automatiquement à chaque cycle (voir common.run_training_
        pipeline côté dashboard), donc même avec MAX_HISTORY=100 000 matchs
        accumulés, un seul appel reste rapide (Python pur, sans numpy). On
        garde les entrées les plus RÉCENTES (l'historique est en ordre
        d'ajout), et les poids déjà appris sont conservés d'un appel à l'autre
        (self.neural_net est chargé depuis nn_weights.json à l'init) : c'est
        un entraînement continu, pas une remise à zéro à chaque cycle."""
        label_to_idx = {"1": 0, "X": 1, "2": 2}
        X, y = [], []
        for item in self.model.data.get("history", []):
            feats = item.get("nn_features")
            actual = item.get("actual")
            if feats and actual in label_to_idx and len(feats) == self.neural_net.input_size:
                X.append(feats)
                y.append(label_to_idx[actual])

        if max_samples and len(X) > max_samples:
            X = X[-max_samples:]
            y = y[-max_samples:]

        report = self.neural_net.fit(X, y, epochs=epochs, lr=lr, batch_size=batch_size, l2=l2)
        if report.get("status") == "trained":
            self.neural_net.save(NN_WEIGHTS_PATH)
        return report


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
                    print(f"👥 Équipes suivies : {stats['teams_tracked']}/{MAX_TEAMS_TRACKED}")
                    print(f"🗃️ Historique : {stats['history_size']}/{MAX_HISTORY}")
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
    label = coupon.get("label", "COUPON OPTIMISE")
    print(f"\n{'='*60}")
    print(f"  🎯 {label.upper()} — {coupon['size']} SELECTIONS")
    print(f"  Genere le {coupon['generated_at'][:16]}")
    print(f"{'='*60}\n")
    
    for i, s in enumerate(coupon["selections"], 1):
        stars = "*" * min(3, int(s["confidence"] * 3))
        print(f"  {i:2}. {s['home']} vs {s['away']}")
        print(f"      📊 Pronostic : {s['prediction']}  |  Cote : {s.get('cote', 0):.2f}")
        print(f"      📊 Confiance : {s['confidence']:.0%} {stars}")
        exact_top3 = s.get("exact_score_top3") or []
        if exact_top3:
            top = exact_top3[0]
            others = ", ".join(f"{e['score']} ({e['probability']:.0%})" for e in exact_top3[1:])
            line = f"      🎯 Score exact probable : {top['score']} ({top['probability']:.0%})"
            if others:
                line += f"  — autres options : {others}"
            print(line)
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
    print(f"  Équipes suivies   : {len(model.data.get('team_form', {}))}/{MAX_TEAMS_TRACKED}")
    print(f"  Historique        : {len(model.data.get('history', []))}/{MAX_HISTORY}")
    
    cal = model.data["calibration"]
    print(f"\n  📊 Calibration:")
    for bucket, label in [("high", ">65%"), ("medium", "45-65%"), ("low", "<45%")]:
        t = cal[bucket]["total"]
        c = cal[bucket]["correct"]
        acc = c/t if t > 0 else 0
        print(f"    {label}: {acc:.1%} ({c}/{t})")
    print(f"{'='*50}\n")


def print_nn_stats(neural_net: "NeuralNet"):
    print(f"\n{'='*50}")
    print(f"  🧬 RESEAU DE NEURONES INTERNE")
    print(f"{'='*50}")
    print(f"  Architecture      : {NN_INPUT_SIZE} -> {NN_HIDDEN1} -> {NN_HIDDEN2} -> {NN_OUTPUT_SIZE}")
    print(f"  Poids entraînables: {neural_net.total_weights()}")
    if neural_net.trained_epochs > 0:
        print(f"  Statut            : entraîné ({neural_net.trained_epochs} époques cumulées, {neural_net.trained_samples} matchs)")
        print(f"  Loss / Accuracy   : {neural_net.last_loss} / {neural_net.last_accuracy:.1%}" if neural_net.last_accuracy is not None else "  Loss / Accuracy   : n/a")
        print(f"  Poids dans le blend final : {NN_BLEND_WEIGHT:.0%}")
    else:
        print(f"  Statut            : non entraîné (n'influence pas encore les pronostics)")
        print(f"  💡 Lancez : python predictor.py --train-nn 30")
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(description="CongoBet AI Predictor")
    parser.add_argument("--analyze", action="store_true", help="Analyse les matchs disponibles")
    parser.add_argument("--coupon", type=int, default=8, help="Génère un coupon de N matchs")
    parser.add_argument("--coupon2", type=int, default=15, help="Génère un 2e ticket de N matchs (0 pour désactiver)")
    parser.add_argument("--train", action="store_true", help="Lance l'auto-entraînement")
    parser.add_argument("--stats", action="store_true", help="Affiche les stats du modèle")
    parser.add_argument("--competition", type=str, help="Filtrer par compétition (PL, BL1, etc.)")
    parser.add_argument("--mise", type=float, default=10.0, help="Mise en EUR")
    parser.add_argument("--auto-train", type=int, metavar="MINUTES", help="Auto-entraînement en boucle (ex: 10)")
    parser.add_argument("--train-nn", type=int, metavar="EPOCHS", help="Entraîne le réseau de neurones interne sur l'historique déjà accumulé (ex: 30)")
    
    args = parser.parse_args()
    
    if args.auto_train:
        auto_train_loop(args.auto_train)
        return

    if args.train_nn:
        predictor = Predictor()
        print(f"🧬 Entraînement du réseau de neurones interne ({args.train_nn} époques)...")
        report = predictor.train_neural_net(epochs=args.train_nn)
        if report.get("status") == "insufficient_data":
            print(f"⚠️ Pas assez de données : {report['samples']} échantillons disponibles ({report['minimum_recommended']} minimum requis).")
            print("💡 Lancez d'abord --train / --auto-train sur des matchs terminés pour accumuler de l'historique (les features sont capturées automatiquement).")
        else:
            print(f"✅ Entraîné en {report['elapsed_seconds']}s — loss={report['final_loss']}  accuracy interne={report['final_accuracy']:.1%}  poids={report['total_weights']}")
        print_nn_stats(predictor.neural_net)
        return
    
    if args.stats:
        model = ModelData()
        predictor = Predictor()
        print_stats(model)
        print_nn_stats(predictor.neural_net)
        return
    
    if args.train:
        print("🧠 Entraînement du modèle sur les matchs terminés...")
        matches = load_matches_from_db(competition_id=args.competition)
        if not matches:
            matches = load_matches_from_json()

        # Complète avec historical_results.db (football-data.org), la même
        # source que common.py::run_training_pipeline() utilise côté appli
        # Streamlit. Sans ça, --train en CLI ne voyait QUE congobet.db, qui
        # remplit très rarement ses propres résultats — le CLI restait donc
        # bloqué à ~0 échantillon même quand historical_results.db contenait
        # des milliers de matchs utilisables (cas réel observé : 3879 lignes
        # inutilisées par le CLI).
        historical_matches = []
        try:
            from historical_data import get_historical_training_matches
            historical_matches = get_historical_training_matches(limit=10_000)
            if historical_matches:
                print(f"📚 {len(historical_matches)} matchs historiques ajoutés depuis historical_results.db")
        except Exception as e:
            print(f"⚠️ historical_results.db indisponible ({e}) — entraînement sur congobet.db uniquement")

        combined = (matches or []) + historical_matches
        if not combined:
            print("❌ Aucun match disponible (ni congobet.db, ni historical_results.db).")
            print("💡 Essayez: python scraper_api.py")
            return

        # Même correctif anti-fuite temporelle que common.py::run_training_pipeline
        # (voir l'audit) : team_form est un état mutable mis à jour au fil de la
        # boucle d'entraînement — sans ce tri chronologique croissant, un vieux
        # match pourrait être "prédit" avec la connaissance de matchs plus
        # récents déjà traités avant lui. Toujours trier avant train_from_results.
        matches_sorted = sorted(
            combined,
            key=lambda m: parse_match_datetime(m.get("start_time")) or datetime.min.replace(tzinfo=timezone.utc)
        )

        predictor = Predictor()
        stats = predictor.train_from_results(matches_sorted, limit=len(matches_sorted))
        print(f"✅ {stats['trained']} matchs entraînés, {stats['skipped']} ignorés (pas de résultat, ou déjà entraînés)")
        print(f"📊 Accuracy globale du modèle : {stats['overall_accuracy']:.1%} sur {stats['total_model_predictions']} prédictions cumulées")
        print_stats(predictor.model)
        return
    
    matches = load_matches_from_db(competition_id=args.competition)
    
    if not matches:
        matches = load_matches_from_json()
    
    if not matches:
        print("❌ Aucun match disponible dans la base.")
        print("💡 Essayez: python scraper_api.py")
        return
    
    # La page Prédire ne doit jamais recycler les anciens matchs.
    # La date/heure de coup d'envoi normalisée en UTC est le critère principal.
    future_matches, live_matches, past_matches = filter_upcoming_matches(matches)

    print(f"🗂️ Matchs chargés : {len(matches)}")
    print(f"🟢 Matchs futurs : {len(future_matches)}")
    print(f"🔴 Matchs en direct : {len(live_matches)}")
    print(f"⚪ Matchs passés/terminés : {len(past_matches)}")

    if not future_matches:
        print("ℹ️ Aucun nouveau match futur à prédire.")
        print("💡 Les anciens matchs restent disponibles pour l'entraînement et l'historique, mais ne sont pas réutilisés comme matchs futurs.")
        return

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
            if p.get("exact_score_predicted"):
                print(f"  🎯 Score exact probable : {p['exact_score_predicted']}")
            if p.get("comment"):
                print(f"  💬 {p['comment']}")
            print()
    
    # Ticket principal (taille configurable, 8 par défaut)
    coupon = predictor.build_coupon(predictions, size=args.coupon, label=f"Ticket {args.coupon} matchs")
    print_coupon(coupon, mise=args.mise)

    # Ticket secondaire de 15 matchs (activé par défaut), avec des seuils plus
    # permissifs car un ticket à 15 sélections ne peut pas se limiter aux seuls
    # matchs à très haute confiance sans quoi il n'y aurait pas assez de matchs.
    if args.coupon2 and args.coupon2 != args.coupon:
        if len(predictions) >= args.coupon2:
            coupon15 = predictor.build_coupon(
                predictions,
                size=args.coupon2,
                min_confidence=0.35,
                min_cote=1.15,
                label=f"Ticket {args.coupon2} matchs",
            )
            print_coupon(coupon15, mise=args.mise)
        else:
            print(f"ℹ️ Pas assez de matchs futurs ({len(predictions)}) pour générer un ticket de {args.coupon2} matchs.\n")
    
    print_stats(predictor.model)
    print_nn_stats(predictor.neural_net)


if __name__ == "__main__":
    # Ce wrapping ne s'applique QU'ICI (usage CLI direct), jamais sur un
    # simple import — voir le commentaire en haut du fichier.
    try:
        if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
