# -*- coding: utf-8 -*-
"""
coupon_tracker.py — Suivi persistant des coupons proposés par l'IA
================================================================================
Problème corrigé : predictions_history.json était ÉCRASÉ à chaque cycle (10
min), donc impossible de savoir si "le coupon de ce matin" avait gagné une
fois les matchs terminés — il n'existait déjà plus. Ce module :

1. Sauvegarde CHAQUE coupon proposé de façon persistante (append, jamais
   écrasé) dans une table dédiée `coupon_history` (congobet.db).
2. Vérifie automatiquement, à chaque cycle, si les matchs des coupons en
   attente sont terminés (via la colonne `result` déjà remplie par
   scraper_api.py/scraper_1xbet_api.py une fois le match fini).
3. Une fois un coupon réglé (tous les matchs terminés), calcule le nombre de
   bons pronostics, le ROI, et POUSSE le résultat de chaque match vers
   ensemble/meta_learner.record_model_outcome() -> c'est la vraie boucle
   d'auto-apprentissage (le meta-learner ajuste ses poids par ligue/modèle
   en fonction des vrais résultats, pas seulement en théorie).
4. Journalise les "failles" (matchs ratés) dans `prediction_failures` pour
   analyse (quelles ligues/plages de confiance posent problème).

Utilisation (déjà branché automatiquement dans common.run_auto_cycle) :
    from coupon_tracker import save_daily_coupon, settle_pending_coupons
    save_daily_coupon(coupon, predictions)
    settle_pending_coupons()
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, date
from pathlib import Path

DB_PATH = Path("congobet.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_tables() -> None:
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS coupon_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at  TEXT,
            coupon_date   TEXT,
            matches_json  TEXT,
            status        TEXT DEFAULT 'pending',
            settled_at    TEXT,
            hits          INTEGER,
            total         INTEGER,
            total_odds    REAL,
            roi           REAL,
            results_json  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_coupon_status ON coupon_history(status);
        CREATE INDEX IF NOT EXISTS idx_coupon_date ON coupon_history(coupon_date);

        CREATE TABLE IF NOT EXISTS prediction_failures (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            coupon_id    INTEGER,
            match_id     TEXT,
            home         TEXT,
            away         TEXT,
            league       TEXT,
            predicted    TEXT,
            actual       TEXT,
            confidence   REAL,
            cote         REAL,
            logged_at    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_failures_league ON prediction_failures(league);
    """)
    conn.commit()
    conn.close()


def save_daily_coupon(coupon: dict, force: bool = False) -> dict:
    """
    Sauvegarde le coupon proposé aujourd'hui. Par défaut, ne sauvegarde
    qu'UNE FOIS par jour calendaire (évite de créer 144 coupons/jour à
    cause du cycle auto toutes les 10 min) — sauf si force=True (bouton
    manuel "Sauvegarder ce coupon" dans l'UI, qui crée une entrée dédiée).
    """
    init_tables()
    selections = coupon.get("selections", [])
    if not selections:
        return {"saved": False, "reason": "coupon vide"}

    today_str = date.today().isoformat()
    conn = _connect()
    try:
        if not force:
            existing = conn.execute(
                "SELECT id FROM coupon_history WHERE coupon_date = ? AND status = 'pending'",
                (today_str,),
            ).fetchone()
            if existing:
                return {"saved": False, "reason": "coupon du jour deja sauvegarde", "coupon_id": existing["id"]}

        matches_json = json.dumps([
            {
                "match_id": s.get("match_id") or s.get("id"),
                "home": s.get("home", ""),
                "away": s.get("away", ""),
                "league": s.get("league", ""),
                "start_time": s.get("start_time", ""),
                "prediction": s.get("prediction", ""),
                "confidence": s.get("confidence", 0),
                "cote": s.get("cote", 0),
                "model_breakdown": s.get("model_breakdown"),
            }
            for s in selections
        ], ensure_ascii=False)

        cur = conn.execute(
            """INSERT INTO coupon_history
               (generated_at, coupon_date, matches_json, status, total, total_odds)
               VALUES (?, ?, ?, 'pending', ?, ?)""",
            (
                datetime.now().isoformat(),
                today_str,
                matches_json,
                len(selections),
                coupon.get("total_cote", 0),
            ),
        )
        conn.commit()
        return {"saved": True, "coupon_id": cur.lastrowid}
    finally:
        conn.close()


def _lookup_result_free(conn: sqlite3.Connection, match_id: str, home: str = "", away: str = "", match_date: str = ""):
    """
    Version gratuite de la recherche de résultat — tiers 1 (congobet.db) et
    2 (historical_results.db) seulement, AUCUN appel API-Football. Utilisée
    pour l'entraînement en masse (potentiellement des centaines de matchs
    d'un coup), où appeler API-Football pour chacun épuiserait le quota
    gratuit (100/jour) en une seule fois — ce quota est réservé au
    règlement des coupons/pronostics suivis (faible volume, voir
    _lookup_result ci-dessous qui ajoute le 3e tier API-Football).
    """
    row = conn.execute(
        "SELECT result, home_score, away_score FROM matches WHERE id = ?",
        (match_id,),
    ).fetchone()
    if row and row["result"] is not None:
        return {
            "result": row["result"],
            "home_score": row["home_score"],
            "away_score": row["away_score"],
        }

    if not home or not away:
        return None

    try:
        hconn = sqlite3.connect("historical_results.db")
        hconn.row_factory = sqlite3.Row
        date_prefix = (match_date or "")[:10]
        query = """SELECT result, home_score, away_score, utc_date FROM results_history
                    WHERE home_team_name = ? AND away_team_name = ?
                      AND home_score IS NOT NULL"""
        params = [home, away]
        if date_prefix:
            query += " AND substr(utc_date,1,10) BETWEEN date(?, '-3 days') AND date(?, '+3 days')"
            params += [date_prefix, date_prefix]
        query += " ORDER BY utc_date DESC LIMIT 1"
        hrow = hconn.execute(query, params).fetchone()
        hconn.close()
        if hrow:
            result_map = {"H": "1", "D": "X", "A": "2", "1": "1", "X": "X", "2": "2"}
            return {
                "result": result_map.get(str(hrow["result"]).upper(), hrow["result"]),
                "home_score": hrow["home_score"],
                "away_score": hrow["away_score"],
            }
    except Exception:
        pass

    return None


def _lookup_result(conn: sqlite3.Connection, match_id: str, home: str = "", away: str = "", match_date: str = ""):
    """
    Cherche le résultat réel d'un match — version complète (3 tiers), pour
    le règlement des coupons et des pronostics suivis (faible volume,
    quelques dizaines de matchs/jour max, donc le coût en quota API-Football
    est négligeable). Pour l'entraînement en masse, voir _lookup_result_free.

    1. D'abord dans congobet.db (peu importe la source) — mais en pratique
       l'API CongoBet/1xBet ne renvoie JAMAIS le score final une fois le
       match terminé (c'est un flux de cotes live, pas un flux de résultats)
       : `matches.result` y est donc systématiquement NULL. Sans ce filet
       de secours, AUCUN coupon ne pouvait jamais être réglé, et l'auto-
       apprentissage ne se déclenchait donc jamais.
    2. En repli, cherche dans historical_results.db (football-data.org) par
       noms d'équipes + date proche — ne couvre que les grandes ligues
       (PL, BL1, SA, PD, FL1, CL, EL).
    3. En dernier repli, interroge API-Football (clé déjà configurée dans
       core/config.py) — couverture bien plus large (1100+ compétitions
       selon leur documentation), donc censé couvrir la plupart des ligues
       que les 2 sources précédentes ratent. Coûte 1 requête de quota par
       match cherché (gratuit : 100/jour) — silencieusement ignoré si le
       quota est épuisé ou la clé absente, pour ne jamais faire planter le
       règlement des coupons.
    """
    free_result = _lookup_result_free(conn, match_id, home, away, match_date)
    if free_result is not None:
        return free_result

    if not home or not away:
        return None

    try:
        from enrichment_api_football import get_fixture_result
        api_result = get_fixture_result(home, away, match_date)
        if api_result:
            return api_result
    except Exception:
        pass  # clé absente, quota épuisé, ou match introuvable — on abandonne proprement

    return None


def get_recent_matches_with_results(days_back: int = 21, limit: int = 300) -> list[dict]:
    """
    Vrais matchs récents (CongoBet/1xBet, avec leurs VRAIES cotes déjà
    scrapées) dont le coup d'envoi est passé depuis au moins 3h, avec leur
    résultat retrouvé via le filet gratuit (congobet.db -> historical_results.db).

    Corrige le fait que get_finished_matches() (qui dépend de home_score
    rempli dans congobet.db) ne renvoyait JAMAIS aucun match : l'entraînement
    se faisait donc à 100% sur historical_results.db (grandes ligues
    européennes, jusqu'à 2 ans d'ancienneté), jamais sur de vrais matchs
    récents avec de vraies cotes de marché. Ce sont pourtant ces matchs
    récents-là qui reflètent le mieux la forme ACTUELLE des équipes.

    N'utilise PAS API-Football (voir _lookup_result_free) — potentiellement
    des centaines de matchs par appel, l'entraînement n'est pas l'endroit où
    dépenser le quota gratuit de 100 requêtes/jour.
    """
    from datetime import timedelta
    from common import get_db_connection, _get_schema

    conn = get_db_connection()
    if not conn:
        return []

    try:
        schema = _get_schema(conn)
        if not schema:
            return []

        cutoff_recent = (datetime.now() - timedelta(hours=3)).isoformat()
        cutoff_old = (datetime.now() - timedelta(days=days_back)).isoformat()
        date_col = schema.get("date_col") or "start_time"

        rows = conn.execute(f"""
            SELECT * FROM {schema['table']}
            WHERE {date_col} IS NOT NULL AND {date_col} != ''
              AND {date_col} < ? AND {date_col} > ?
              AND (home_score IS NULL OR home_score = '')
            ORDER BY {date_col} DESC
            LIMIT ?
        """, (cutoff_recent, cutoff_old, limit)).fetchall()
    except Exception:
        conn.close()
        return []

    results = []
    for row in rows:
        m = dict(row)
        home, away = m.get(schema["home_col"], ""), m.get(schema["away_col"], "")
        if not home or not away:
            continue

        match_id = m.get(schema["id_col"], "")
        res = _lookup_result_free(conn, match_id, home, away, m.get(date_col, ""))
        if res is None:
            continue  # pas (encore) trouvé dans les sources gratuites — sera retenté au prochain cycle

        markets = {}
        try:
            odds_rows = conn.execute(
                "SELECT market, label, value FROM odds WHERE match_id = ?", (match_id,)
            ).fetchall()
            for market, label, value in odds_rows:
                markets.setdefault(market, {})[label] = value
        except Exception:
            pass

        results.append({
            "id": f"recent_{match_id}",
            "home": home, "away": away,
            "league": m.get(schema["league_col"], ""),
            "start_time": m.get(date_col, ""),
            "home_score": res["home_score"], "away_score": res["away_score"],
            "result": res["result"],
            "markets": markets,
        })

    conn.close()
    return results


def settle_pending_coupons() -> dict:
    """
    Parcourt les coupons 'pending' et règle ceux dont TOUS les matchs ont un
    résultat connu. Pousse chaque résultat vers le meta-learner (boucle
    d'auto-apprentissage réelle) et journalise les échecs pour analyse.
    """
    init_tables()
    conn = _connect()
    settled_count = 0
    still_pending = 0

    try:
        pending = conn.execute(
            "SELECT * FROM coupon_history WHERE status = 'pending'"
        ).fetchall()

        for coupon_row in pending:
            matches = json.loads(coupon_row["matches_json"])
            resolved = []
            all_resolved = True

            for m in matches:
                res = _lookup_result(conn, m["match_id"], m.get("home", ""), m.get("away", ""), m.get("start_time", ""))
                if res is None:
                    all_resolved = False
                    break
                resolved.append({**m, **res, "correct": res["result"] == m["prediction"]})

            if not all_resolved:
                still_pending += 1
                continue

            hits = sum(1 for m in resolved if m["correct"])
            total = len(resolved)
            total_odds = 1.0
            for m in resolved:
                if m["correct"] and m.get("cote"):
                    total_odds *= float(m["cote"])
            roi = round((total_odds - 1) if hits == total else -1.0, 3)

            conn.execute(
                """UPDATE coupon_history SET status='settled', settled_at=?, hits=?, 
                   results_json=?, roi=? WHERE id=?""",
                (datetime.now().isoformat(), hits, json.dumps(resolved, ensure_ascii=False), roi, coupon_row["id"]),
            )

            try:
                from community_db import create_notification
                if hits == total:
                    create_notification(
                        user_id=None,  # notification globale, visible par tous
                        type="coupon_won",
                        title="🎉 Coupon parfait !",
                        message=f"Le coupon du {coupon_row['coupon_date']} est gagnant à 100% ({hits}/{total}) !",
                        link_page="Pronostics",
                    )
                elif hits >= total * 0.6:
                    create_notification(
                        user_id=None,
                        type="coupon_good",
                        title="✅ Bon coupon",
                        message=f"Le coupon du {coupon_row['coupon_date']} a fait {hits}/{total} bons pronostics.",
                        link_page="Pronostics",
                    )
            except Exception:
                pass  # la notification est un plus, jamais bloquant pour le règlement lui-même

            # --- Boucle d'auto-apprentissage : pousse le résultat de l'ensemble
            # ET de chaque sous-modèle individuellement (Poisson, Dixon-Coles,
            # Elo, Bayésien, XGB, LightGBM...) vers le meta-learner, en
            # comparant la prédiction propre à CHAQUE sous-modèle (pas juste
            # le pronostic final de l'ensemble) au résultat réel. ---
            try:
                from ensemble.meta_learner import record_model_outcome
                for m in resolved:
                    record_model_outcome(league=m.get("league", "unknown"), model_name="ensemble", correct=m["correct"])

                    breakdown = m.get("model_breakdown")
                    if isinstance(breakdown, dict):
                        for sub_model_name, detail in breakdown.items():
                            try:
                                sub_probs = detail.get("probabilities", {})
                                if not sub_probs:
                                    continue
                                sub_prediction = max(sub_probs, key=sub_probs.get)
                                sub_correct = sub_prediction == m["result"]
                                record_model_outcome(
                                    league=m.get("league", "unknown"),
                                    model_name=sub_model_name,
                                    correct=sub_correct,
                                )
                            except Exception:
                                continue
            except Exception:
                pass  # meta-learner optionnel, ne doit jamais faire planter le settlement

            # --- Journalise les échecs pour analyse (quelles ligues posent problème) ---
            for m in resolved:
                if not m["correct"]:
                    conn.execute(
                        """INSERT INTO prediction_failures
                           (coupon_id, match_id, home, away, league, predicted, actual, confidence, cote, logged_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (
                            coupon_row["id"], m["match_id"], m["home"], m["away"], m.get("league", ""),
                            m["prediction"], m["result"], m.get("confidence", 0), m.get("cote", 0),
                            datetime.now().isoformat(),
                        ),
                    )

            settled_count += 1

        conn.commit()
    finally:
        conn.close()

    return {"settled": settled_count, "still_pending": still_pending}


def get_coupon_history(limit: int = 30) -> list:
    init_tables()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM coupon_history ORDER BY generated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_failure_analysis(limit: int = 100) -> dict:
    """Retourne un résumé des échecs récents groupés par ligue, pour identifier
    les faiblesses du modèle (ex: telle ligue est mal prédite)."""
    init_tables()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT league, COUNT(*) as failures FROM prediction_failures "
            "GROUP BY league ORDER BY failures DESC LIMIT ?",
            (limit,),
        ).fetchall()
        recent = conn.execute(
            "SELECT * FROM prediction_failures ORDER BY logged_at DESC LIMIT 20"
        ).fetchall()
        return {
            "by_league": [dict(r) for r in rows],
            "recent_failures": [dict(r) for r in recent],
        }
    finally:
        conn.close()


def get_global_stats() -> dict:
    """Statistiques globales tous coupons réglés confondus (taux de réussite réel)."""
    init_tables()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as n, SUM(hits) as hits, SUM(total) as total, AVG(roi) as avg_roi "
            "FROM coupon_history WHERE status='settled'"
        ).fetchone()
        n = row["n"] or 0
        hits = row["hits"] or 0
        total = row["total"] or 0
        return {
            "coupons_settled": n,
            "matches_correct": hits,
            "matches_total": total,
            "accuracy": round(hits / total, 3) if total else None,
            "avg_roi": round(row["avg_roi"], 3) if row["avg_roi"] is not None else None,
        }
    finally:
        conn.close()
