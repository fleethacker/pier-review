from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query

from mooring.core.schemas import (
    EnvironmentAvailability,
    EnvironmentSnapshot,
    EnvScenario,
    EnvScenarioCreate,
    ForecastSeries,
    GustModel,
    HistorySeries,
)
from mooring.examples import ex

from mooring.environment.coops import ProviderError

from ..backend import env as impl

STATUS = {"invalid_request": 422, "bad_request": 502, "malformed": 502, "no_data": 503, "unavailable": 503, "stale": 503}


def guarded(fn, *a, **kw):
    """Provider failures are documented service errors (503/502/422), never synthetic data."""
    try:
        return fn(*a, **kw)
    except ProviderError as e:
        raise HTTPException(status_code=STATUS.get(e.kind, 502), detail=f"environment provider ({e.kind}): {e}") from None

router = APIRouter(tags=["M1 Environment"])


@router.on_event("startup")
def validate_environment_configuration():
    """Fail process startup before an unknown source can fall through to synthetic data."""
    impl.validate_configuration()


@router.get("/env/now", response_model=EnvironmentSnapshot, summary="Current environment at a berth")
def env_now(
    berth_id: str,
    heading_true_deg: Annotated[float | None, Query(ge=0, lt=360, description="Adds relative bearings.")] = None,
    env_scenario_id: Annotated[str | None, Query(description="Serve a synthetic scenario instead.")] = None,
):
    return guarded(impl.now, berth_id, heading_true_deg, env_scenario_id)


@router.get(
    "/env/availability",
    response_model=EnvironmentAvailability,
    summary="Independent source and availability status for environment components",
)
def env_availability(berth_id: str):
    """Report partial status without weakening the complete `/env/now` contract."""
    from mooring import refdata

    refdata.berth(berth_id)
    return guarded(impl.availability, berth_id)


@router.get("/env/forecast", response_model=ForecastSeries, summary="Forecast series at a berth")
def env_forecast(berth_id: str, hours: Annotated[int, Query(ge=1, le=120)] = 48,
                 step_min: Annotated[int, Query(ge=6, le=180)] = 30):
    from mooring import refdata

    refdata.berth(berth_id)
    return guarded(impl.forecast, berth_id, hours, step_min)


@router.get("/env/history", response_model=HistorySeries, summary="Historical observations for replay")
def env_history(station: str, start_utc: datetime, end_utc: datetime):
    return guarded(impl.history, station, start_utc, end_utc)


@router.post("/env/scenarios", response_model=EnvScenario, status_code=201, summary="Create a synthetic environment")
def env_scenario_create(req: Annotated[EnvScenarioCreate, Body(openapi_examples=ex("env_scenario"))]):
    return impl.create_scenario(req)


@router.get("/env/scenarios/{env_scenario_id}", response_model=EnvScenario)
def env_scenario_get(env_scenario_id: str):
    return impl.get_scenario(env_scenario_id)


@router.get("/env/gust-model", response_model=GustModel, summary="Fitted gust factor and current residual model")
def env_gust_model(station: str = "8638614"):
    try:
        return impl.gust_model(station)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
