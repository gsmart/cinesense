from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.adapters.tmdb import TmdbAdapter
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.lookup import LookupRequest, LookupResponse
from app.services import LookupService

router = APIRouter(tags=["lookup"])


@router.post("/lookup", response_model=LookupResponse)
async def lookup_movie(payload: LookupRequest, db: Session = Depends(get_db)) -> LookupResponse:
    service = LookupService(db, TmdbAdapter(get_settings()))
    try:
        result = await service.lookup(
            title=payload.title,
            year=payload.year,
            region=payload.region,
            media_type=payload.media_type,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return LookupResponse.model_validate(result)

