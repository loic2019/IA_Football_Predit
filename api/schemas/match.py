from pydantic import BaseModel


class MatchOut(BaseModel):
    id: str
    home: str
    away: str
    league: str | None = None
    date: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    result: str | None = None


class DashboardSummary(BaseModel):
    future_matches: int
    finished_matches: int
    live_matches: int
    model_stats: dict
