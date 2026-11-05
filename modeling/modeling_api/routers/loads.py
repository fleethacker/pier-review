from typing import Annotated

from fastapi import APIRouter, Body, HTTPException

from mooring.core.schemas import LoadsRequest, LoadsResponse, PolarRequest, PolarResponse, WaveSurrogateRequest, WaveSurrogateResult
from mooring.data_simulation.wave_surrogate import generate as _wave_generate
from mooring.examples import ex

from ..backend import loads as impl
from ..inputs import check_loads

router = APIRouter(tags=["M3 Environmental loads"])


@router.post("/loads/environmental", response_model=LoadsResponse, summary="Wind and current forces on the ship")
def environmental(req: Annotated[LoadsRequest, Body(openapi_examples=ex("loads_environmental"))]):
    check_loads(req)
    return impl.environmental(req)


@router.post("/loads/polar", response_model=PolarResponse, summary="Forces for every relative direction (rose chart)")
def polar(req: Annotated[PolarRequest, Body(openapi_examples=ex("loads_polar"))]):
    return impl.polar(req)


@router.post("/loads/wave-surrogate", response_model=WaveSurrogateResult, tags=["S4 Wave surrogate"],
             summary="Seeded synthetic wave elevation series (visualization only; unqualified)")
def wave_surrogate(req: WaveSurrogateRequest):
    # duration_s <= 3600 and dt_s <= 10 are schema-bounded; also bound the sample count.
    if req.duration_s / req.dt_s > 6_000:
        raise HTTPException(status_code=422, detail="duration_s / dt_s exceeds 6000 samples; raise dt_s or shorten duration_s")
    return _wave_generate(req)
