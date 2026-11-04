from typing import Annotated

from fastapi import APIRouter, Body

from mooring.core.schemas import LoadsRequest, LoadsResponse, PolarRequest, PolarResponse
from mooring.mock.examples import ex

from ..backend import loads as impl

router = APIRouter(tags=["M3 Environmental loads"])


@router.post("/loads/environmental", response_model=LoadsResponse, summary="Wind and current forces on the ship")
def environmental(req: Annotated[LoadsRequest, Body(openapi_examples=ex("loads_environmental"))]):
    return impl.environmental(req)


@router.post("/loads/polar", response_model=PolarResponse, summary="Forces for every relative direction (rose chart)")
def polar(req: Annotated[PolarRequest, Body(openapi_examples=ex("loads_polar"))]):
    return impl.polar(req)
