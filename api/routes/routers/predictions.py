from fastapi import APIRouter, Depends

from api.routes.deps import get_current_user
from api.services import prediction_service

router = APIRouter(prefix="/predictions", tags=["predictions"], dependencies=[Depends(get_current_user)])


@router.get("")
def predictions(limit: int = 200, min_confidence: float = 0.0, min_cote: float = 1.30):
    return prediction_service.get_predictions(limit, min_confidence, min_cote)


@router.get("/combos")
def combos():
    """Analyse des tickets combinés 'Top paris' CongoBet (fiabilité, meilleur ticket)."""
    return prediction_service.get_combo_analysis()
