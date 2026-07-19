from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.adapters.tmdb import TmdbAdapter
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.discovery import DiscoveryRequest, DiscoveryResponse
from app.schemas.lookup import LookupRequest, LookupResponse
from app.schemas.recommendations import RecommendationsRequest, RecommendationsResponse
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


@router.post("/recommendations", response_model=RecommendationsResponse)
async def recommend_movies(payload: RecommendationsRequest, db: Session = Depends(get_db)) -> RecommendationsResponse:
    service = LookupService(db, TmdbAdapter(get_settings()))
    try:
        result = await service.recommend_from_seed_movie(
            seed_movie_id=str(payload.seed_movie_id),
            region=payload.region,
            limit=payload.page_size,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result["status"] == "seed_not_found":
        raise HTTPException(status_code=404, detail="Seed movie not found")
    if result["status"] == "unsupported_media_type":
        raise HTTPException(status_code=422, detail="Seed movie must have media type 'movie'")
    if result["status"] == "missing_external_id":
        raise HTTPException(status_code=422, detail="Seed movie does not have a TMDB external ID")

    if "page" not in result:
        result["page"] = {
            "page": 1,
            "requested_page_size": result.get("limit", payload.page_size),
            "returned_count": len(result.get("results", [])),
            "max_page_size": 20,
        }
    return RecommendationsResponse.model_validate(result)


@router.post("/discover", response_model=DiscoveryResponse)
async def discover_movies(payload: DiscoveryRequest, db: Session = Depends(get_db)) -> DiscoveryResponse:
    service = LookupService(db, TmdbAdapter(get_settings()))
    try:
        result = await service.discover_movies(request=payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result["status"] == "unsupported_filter":
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_filter",
                "filter": result.get("unsupported_filter", "availability_required"),
            },
        )

    result["results"] = result.get("results", [])[:20]
    if "page" in result:
        result["page"]["returned_count"] = min(result["page"].get("returned_count", len(result["results"])), len(result["results"]))
    result["request"] = payload.model_dump()
    return DiscoveryResponse.model_validate(result)
