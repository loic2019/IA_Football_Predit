from fastapi import APIRouter, Depends

from api.routes.deps import require_admin
from api.services import match_service

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/scrape/{source}")
def scrape(source: str):
    """Déclenche un scraper existant. Réservé aux admins (journalisé)."""
    return match_service.trigger_scrape(source)
