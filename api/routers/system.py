# -*- coding: utf-8 -*-
"""api/routers/system.py — Écran Paramètres & Diagnostic.
Réutilise common.py tel quel. Inclut des déclencheurs MANUELS granulaires
(scraping par source séparée, entraînement seul, cycle complet) — la même
fonction que celle utilisée par auto_cycle_worker.py en arrière-plan pour
le cycle complet."""

import sqlite3

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from common import (
    DB_PATH,
    MODEL_PATH,
    get_db_connection,
    get_model_stats,
    get_all_matches,
    load_automation_state,
    seconds_until_next_cycle,
    run_auto_cycle,
    run_training_pipeline,
)

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
def status(current: dict = Depends(get_current_user)):
    db_info = {"exists": DB_PATH.exists(), "path": str(DB_PATH.resolve()), "tables": []}
    if db_info["exists"]:
        conn = get_db_connection()
        if conn:
            try:
                tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                for t in tables:
                    try:
                        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    except sqlite3.Error:
                        count = None
                    db_info["tables"].append({"name": t, "count": count})
            finally:
                conn.close()

    model_stats = get_model_stats()
    model_info = {
        "exists": MODEL_PATH.exists(),
        "path": str(MODEL_PATH.resolve()),
        "total_predictions": model_stats.get("total_predictions") if model_stats else None,
        "history_length": len(model_stats.get("history", [])) if model_stats else 0,
    }

    automation = load_automation_state()
    seconds_left = seconds_until_next_cycle(automation)

    return {"database": db_info, "model": model_info, "automation": {**automation, "seconds_until_next_cycle": seconds_left}}


@router.post("/run-cycle")
def run_cycle(current: dict = Depends(get_current_user)):
    """Déclenche MAINTENANT un cycle complet : scraping (Congobet + 1xBet +
    Premierbet) + entraînement + génération des pronostics — manuellement,
    sans attendre le prochain cycle automatique du worker en arrière-plan."""
    return run_auto_cycle(force=True)


@router.post("/scrape/congobet")
async def scrape_congobet(current: dict = Depends(get_current_user)):
    """Scrape UNIQUEMENT Congobet (sans entraîner ni toucher aux autres sources)."""
    from scraper_api import run_once

    before = get_all_matches()
    await run_once()
    after = get_all_matches()
    return {"source": "congobet", "matches_before": before, "matches_after": after, "added": max(0, after - before)}


@router.post("/scrape/1xbet")
def scrape_1xbet(count: int = 30, current: dict = Depends(get_current_user)):
    """Scrape UNIQUEMENT 1xBet."""
    from scraper_1xbet_api import scrape_1xbet_top_events, init_db, save_to_db

    matches = scrape_1xbet_top_events(count)
    saved = 0
    if matches:
        db = init_db(str(DB_PATH))
        saved = save_to_db(db, matches)
        db.close()
    return {"source": "1xbet", "found": len(matches), "saved": saved}


@router.post("/scrape/premierbet")
def scrape_premierbet(days_ahead: int = 3, current: dict = Depends(get_current_user)):
    """Scrape UNIQUEMENT Premierbet."""
    from scraper_premierbet import run_once as premierbet_run_once

    result = premierbet_run_once(days_ahead=days_ahead)
    return {"source": "premierbet", **result}


@router.post("/train")
def train_model(current: dict = Depends(get_current_user)):
    """Entraîne le modèle sur les données actuellement en base (vrais matchs +
    historique de calibration), SANS relancer de scraping ni de prédiction —
    c'est ce qui augmente la confiance/précision au fil du temps."""
    result = run_training_pipeline()
    return {"trained": True, "result": result}
