from fastapi import APIRouter, Depends

from api.routes.deps import get_current_user
from api.services import stats_service

router = APIRouter(prefix="/stats", tags=["stats"], dependencies=[Depends(get_current_user)])


@router.get("")
def full_stats():
    return stats_service.get_full_stats()
