"""
Couche service pour les matchs / le dashboard.

`common.py` contient déjà des fonctions qui retournent des dicts/listes
purs (get_future_matches, get_live_matches, get_model_stats, ...) — c'est
exactement l'interface dont une API a besoin. On ne fait ici QUE de
l'agrégation/formatage pour le frontend, aucune règle métier nouvelle.
"""
import common


def get_dashboard_summary() -> dict:
    return {
        "future_matches": common.get_future_matches_count(),
        "finished_matches": common.get_finished_matches_count(),
        "live_matches": common.get_live_matches_count(),
        "model_stats": common.get_model_stats(),
    }


def get_live_matches(limit: int = 50) -> list[dict]:
    return common.get_live_matches(limit=limit)


def get_future_matches(limit: int = 50) -> list[dict]:
    return common.get_future_matches(limit=limit)


def get_recent_matches(limit: int = 50) -> list[dict]:
    return common.get_recent_matches(limit=limit)


def get_team_panel(match_id: str, home: str, away: str) -> dict:
    return common.get_team_info_panel(match_id, home, away)


def trigger_scrape(source: str) -> dict:
    """Déclenche un scraper existant (source: '1xbet' | 'besoccer' | 'premierbet' | ...)."""
    return common.run_scraper(source)
