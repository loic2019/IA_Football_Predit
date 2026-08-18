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

STATE_DIR = Path("data")


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
) -> int:
    """
    Args:
        source_tag: identifiant court de la source ("congobet", "1xbet", "premierbet")
                    -> fichier d'état séparé par source, pas de collision.
        current_live_matches: matchs actuellement en direct, chacun avec au
                    moins les clés "id", "home_score", "away_score" (et
                    idéalement "home", "away", "league" pour le diagnostic).
        db_path: chemin de la base congobet.db partagée entre toutes les sources.

    Returns:
        Nombre de matchs marqués terminés à ce cycle.
    """
    state = _load_state(source_tag)
    previously_live = state.get("live_ids", {})

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
    if previously_live:
        conn = sqlite3.connect(db_path)
        for match_id, last_snapshot in previously_live.items():
            if match_id in current_ids:
                continue  # toujours en direct, rien à faire

            hs, as_ = last_snapshot.get("home_score"), last_snapshot.get("away_score")
            if hs is None or as_ is None:
                continue  # jamais eu de score fiable pour ce match, on ne peut rien inférer

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
        conn.commit()
        conn.close()

    # Fusionne : garde les matchs toujours live + ajoute les nouveaux vus ce cycle,
    # nettoie ceux qui viennent d'être réglés (ne pas les re-traiter au prochain cycle).
    merged = {**previously_live, **current_snapshot}
    merged = {k: v for k, v in merged.items() if k in current_ids}
    _save_state(source_tag, {"live_ids": merged, "updated_at": datetime.now().isoformat()})

    return finished_count
