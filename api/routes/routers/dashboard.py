from fastapi import APIRouter, Depends

from api.routes.deps import get_current_user
from api.services import match_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("/summary")
def summary():
    return match_service.get_dashboard_summary()


@router.get("/matches/live")
def live_matches(limit: int = 50):
    return match_service.get_live_matches(limit)


@router.get("/matches/future")
def future_matches(limit: int = 50):
    return match_service.get_future_matches(limit)


@router.get("/matches/recent")
def recent_matches(limit: int = 50):
    return match_service.get_recent_matches(limit)


@router.get("/matches/{match_id}/team-panel")
def team_panel(match_id: str, home: str, away: str):
    return match_service.get_team_panel(match_id, home, away)
