from fastapi import APIRouter, Depends

from api.routes.deps import get_current_user
from api.services import palmares_service

router = APIRouter(prefix="/palmares", tags=["palmares"], dependencies=[Depends(get_current_user)])


@router.get("")
def palmares(filter: str = "all", limit: int = 30):
    """filter: all | won | lost"""
    return palmares_service.get_palmares(filter_choice=filter, limit=limit)
