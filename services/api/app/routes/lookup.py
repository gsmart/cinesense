import inspect
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.adapters.tmdb import TmdbAdapter
from app.core.config import get_settings
from app.db.session import get_db
from app.interpreters import NaturalLanguageDiscoveryInterpreter, get_live_natural_language_discovery_interpreter
from app.schemas.discovery import DiscoveryRequest, DiscoveryResponse
from app.schemas.lookup import LookupRequest, LookupResponse
from app.schemas.natural_language import NaturalLanguageDiscoveryRequest, NaturalLanguageDiscoveryResponse
from app.schemas.recommendations import RecommendationsRequest, RecommendationsResponse
from app.services import LookupService

router = APIRouter(tags=["lookup"])


def get_natural_language_discovery_interpreter() -> NaturalLanguageDiscoveryInterpreter:
    return get_live_natural_language_discovery_interpreter(get_settings())


@router.post("/lookup", response_model=LookupResponse)
async def lookup_movie(payload: LookupRequest, db: Session = Depends(get_db)) -> LookupResponse:
    settings = get_settings()
    if payload.include_shadow and not settings.cinesense_enable_shadow_diagnostics:
        raise HTTPException(status_code=403, detail="Shadow diagnostics are disabled in this environment")
    service = LookupService(db, TmdbAdapter(settings))

    kwargs = {}
    sig = inspect.signature(service.lookup)
    if "include_shadow" in sig.parameters:
        kwargs["include_shadow"] = payload.include_shadow

    try:
        result = await service.lookup(
            title=payload.title,
            year=payload.year,
            region=payload.region,
            media_type=payload.media_type,
            **kwargs,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return LookupResponse.model_validate(result)


@router.post("/recommendations", response_model=RecommendationsResponse)
async def recommend_movies(payload: RecommendationsRequest, db: Session = Depends(get_db)) -> RecommendationsResponse:
    settings = get_settings()
    if payload.include_shadow and not settings.cinesense_enable_shadow_diagnostics:
        raise HTTPException(status_code=403, detail="Shadow diagnostics are disabled in this environment")
    service = LookupService(db, TmdbAdapter(settings))

    kwargs = {}
    sig = inspect.signature(service.recommend_from_seed_movie)
    if "include_shadow" in sig.parameters:
        kwargs["include_shadow"] = payload.include_shadow

    try:
        result = await service.recommend_from_seed_movie(
            seed_movie_id=str(payload.seed_movie_id),
            region=payload.region,
            limit=payload.page_size,
            **kwargs,
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
    settings = get_settings()
    if payload.include_shadow and not settings.cinesense_enable_shadow_diagnostics:
        raise HTTPException(status_code=403, detail="Shadow diagnostics are disabled in this environment")
    service = LookupService(db, TmdbAdapter(settings))
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


@router.post("/discover/natural-language", response_model=NaturalLanguageDiscoveryResponse)
async def discover_movies_natural_language(
    payload: NaturalLanguageDiscoveryRequest,
    db: Session = Depends(get_db),
    interpreter: NaturalLanguageDiscoveryInterpreter = Depends(get_natural_language_discovery_interpreter),
) -> NaturalLanguageDiscoveryResponse:
    settings = get_settings()
    if payload.include_shadow and not settings.cinesense_enable_shadow_diagnostics:
        raise HTTPException(status_code=403, detail="Shadow diagnostics are disabled in this environment")
    service = LookupService(db, TmdbAdapter(settings))
    result = await service.discover_from_natural_language(request=payload, interpreter=interpreter)

    status = result["status"]
    if status == "interpreter_unavailable":
        raise HTTPException(status_code=503, detail={"error": "interpreter_unavailable"})
    if status == "interpreter_failure":
        raise HTTPException(status_code=502, detail={"error": "interpreter_failure"})
    if status == "invalid_interpretation":
        raise HTTPException(status_code=422, detail={"error": "invalid_interpretation"})
    if status == "unrestricted_interpretation":
        raise HTTPException(status_code=422, detail={"error": "unrestricted_interpretation"})
    if status == "unsupported_filter":
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
    result["interpreted_request"] = result.pop("request")
    return NaturalLanguageDiscoveryResponse.model_validate(result)
