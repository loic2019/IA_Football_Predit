# -*- coding: utf-8 -*-
"""
live_match_inference.py — Inférence de fin de match par disparition du flux live
================================================================================
Problème commun à CongoBet, 1xBet ET Premierbet : aucune de ces sources
n'expose un endpoint "résultats terminés" fiable. Un match qui se termine
disparaît simplement du flux "live" sans jamais être explicitement confirmé
comme fini.

Solution partagée (utilisée par scraper_api.py, scraper_1xbet_api.py et
scraper_premierbet.py) : on garde en mémoire (fichier JSON par source) les
matchs vus en direct avec leur dernier score connu. Si un match live d'un
cycle précédent n'apparaît PLUS dans le flux live actuel, on considère qu'il
est terminé et on écrit son dernier score connu comme résultat final dans
congobet.db — ce qui le rend éligible à l'entraînement (get_training_matches
ne filtre pas par source) et à la vérification des coupons/tickets suivis.

Limite assumée : le score peut manquer un but marqué entre la dernière
lecture et la fin réelle du match (imprécision inhérente à cette méthode,
contrairement à un flux "finished" officiel). Le cycle auto tournant toutes
les 10 min, l'erreur est en pratique rare et mineure.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

# CORRECTIF IMPORTANT : STATE_DIR doit être un chemin ABSOLU, ancré sur
# l'emplacement de ce fichier — jamais un chemin relatif comme Path("data").
# Preuve du bug que ça causait : deux fichiers live_state_premierbet.json
# existaient en parallèle (un à la racine, vide ; un dans data/, avec le
# vrai suivi) — parce que ce module est appelé depuis plusieurs contextes
# différents (l'app Streamlit ET auto_cycle_worker.py, un process séparé,
# potentiellement lancé depuis un autre répertoire de travail). Selon lequel
# tournait, l'état était lu/écrit au mauvais endroit, remettant
# silencieusement le compteur de "cycles consécutifs sans ce match" à zéro —
# un match jamais revu restait donc "en direct" indéfiniment, puisque son
# historique de suivi disparaissait avant d'atteindre le seuil de 2.
STATE_DIR = Path(__file__).resolve().parent / "data"


def _state_path(source_tag: str) -> Path:
    return STATE_DIR / f"live_state_{source_tag}.json"


def _load_state(source_tag: str) -> dict:
    path = _state_path(source_tag)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(source_tag: str, state: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    _state_path(source_tag).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def infer_finished_by_disappearance(
    source_tag: str,
    current_live_matches: list[dict],
    db_path: str = "congobet.db",
    min_consecutive_misses: int = 2,
) -> int:
    """
    Args:
        source_tag: identifiant court de la source ("congobet", "1xbet", "premierbet")
                    -> fichier d'état séparé par source, pas de collision.
        current_live_matches: matchs actuellement en direct, chacun avec au
                    moins les clés "id", "home_score", "away_score" (et
                    idéalement "home", "away", "league" pour le diagnostic).
        db_path: chemin de la base congobet.db partagée entre toutes les sources.
        min_consecutive_misses: nombre de cycles CONSÉCUTIFS où le match doit
                    rester absent avant d'être déclaré terminé. À 1, un simple
                    accroc réseau ou une disparition temporaire (VAR, litige,
                    match suspendu des cotes) suffit à générer un faux résultat
                    ("fictif"). À 2 (défaut, ~20 min avec un cycle de 10 min),
                    on élimine l'immense majorité des faux positifs tout en
                    gardant un délai de confirmation raisonnable.

    Returns:
        Nombre de matchs marqués terminés à ce cycle.
    """
    state = _load_state(source_tag)
    # "tracked" : tous les matchs vus récemment en direct, avec leur dernier
    # score connu et leur nombre d'absences consécutives (0 = vu ce cycle-ci).
    tracked = state.get("tracked", {}) or _migrate_legacy_state(state)

    current_ids = {m["id"] for m in current_live_matches if m.get("id")}
    current_snapshot = {
        m["id"]: {
            "home_score": m.get("home_score"),
            "away_score": m.get("away_score"),
            "home": m.get("home") or m.get("home_team"),
            "away": m.get("away") or m.get("away_team"),
            "league": m.get("league"),
        }
        for m in current_live_matches if m.get("id")
    }

    finished_count = 0
    new_tracked = {}

    # Matchs vus ce cycle -> on remet le compteur d'absence à 0.
    for match_id, snap in current_snapshot.items():
        new_tracked[match_id] = {**snap, "misses": 0}

    # CORRECTIF : "adopte" les matchs is_live=1 en base qui ne sont PLUS
    # suivis dans `tracked` (ex: suivi perdu suite à un crash, un état
    # écrasé par un autre process, ou tout simplement jamais vus par CE
    # process avant aujourd'hui). Sans ça, un match qui devient orphelin
    # reste is_live=1 EN PERMANENCE : il ne peut jamais être ré-adopté
    # puisqu'il ne réapparaîtra plus jamais dans current_live_matches (il
    # est réellement terminé) — la seule porte de sortie était déjà d'être
    # dans `tracked`, une porte qui se refermait pour de bon dès que le
    # suivi était perdu. Cas réel observé : match Philadelphia Union vs
    # Seattle Sounders (26/07) toujours "EN DIRECT" 3 semaines plus tard.
    try:
        conn_scan = sqlite3.connect(db_path)
        conn_scan.row_factory = sqlite3.Row
        cols = {row[1] for row in conn_scan.execute("PRAGMA table_info(matches)").fetchall()}
        home_col = "home_team" if "home_team" in cols else ("home" if "home" in cols else None)
        away_col = "away_team" if "away_team" in cols else ("away" if "away" in cols else None)
        if home_col and away_col:
            orphan_rows = conn_scan.execute(
                f"SELECT id, home_score, away_score, {home_col} as home, {away_col} as away, league "
                f"FROM matches WHERE is_live=1"
            ).fetchall()
            for row in orphan_rows:
                mid = row["id"]
                if mid in current_ids or mid in tracked or mid in new_tracked:
                    continue  # déjà suivi normalement, rien à adopter
                tracked[mid] = {
                    "home_score": row["home_score"], "away_score": row["away_score"],
                    "home": row["home"], "away": row["away"], "league": row["league"],
                    "misses": 0,
                }
        conn_scan.close()
    except Exception:
        pass

    # Matchs suivis mais absents ce cycle -> on incrémente leur compteur.
    # Seuls ceux qui dépassent le seuil sont vraiment finalisés en base ;
    # les autres restent "en observation" pour le prochain cycle.
    conn = None
    for match_id, last in tracked.items():
        if match_id in current_ids:
            continue  # déjà remis à jour ci-dessus

        misses = int(last.get("misses", 0)) + 1
        hs, as_ = last.get("home_score"), last.get("away_score")

        if misses < min_consecutive_misses:
            new_tracked[match_id] = {**last, "misses": misses}
            continue

        if hs is None or as_ is None:
            continue  # jamais eu de score fiable pour ce match, on ne peut rien inférer

        if conn is None:
            conn = sqlite3.connect(db_path)
        result = "1" if hs > as_ else ("2" if hs < as_ else "X")
        try:
            conn.execute(
                """UPDATE matches SET home_score=?, away_score=?, result=?, state=?,
                   state_details=?, is_live=0
                   WHERE id=?""",
                (hs, as_, result, "finished", f"finished_inferred_{source_tag}", match_id),
            )
            finished_count += 1
        except Exception:
            pass
        # Ne pas remettre dans new_tracked : match réglé, on arrête de le suivre.

    if conn is not None:
        conn.commit()
        conn.close()

    _save_state(source_tag, {"tracked": new_tracked, "updated_at": datetime.now().isoformat()})

    return finished_count


def _migrate_legacy_state(state: dict) -> dict:
    """Compatibilité avec l'ancien format de fichier d'état (clé 'live_ids' à
    plat, sans compteur d'absences) — évite de perdre le suivi en cours lors
    du passage à la nouvelle logique anti faux-positifs."""
    legacy = state.get("live_ids", {})
    return {mid: {**snap, "misses": 0} for mid, snap in legacy.items()}
