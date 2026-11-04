from typing import Annotated

from fastapi import APIRouter, Body

from mooring.core.schemas import (
    BerthingTugRequest,
    BerthingWindowRequest,
    BerthingWindowsResponse,
    HoldTugRequest,
    TugPlanResponse,
)
from mooring.mock.examples import ex

from ..backend import tugs as impl

router = APIRouter(tags=["M6 Tugs"])


@router.post("/tugs/berthing-plan", response_model=TugPlanResponse,
             summary="Tugs needed to land and hold the ship before lines are fast")
def berthing_plan(req: Annotated[BerthingTugRequest, Body(openapi_examples=ex("tugs_berthing_plan"))]):
    return impl.berthing_plan(req)


@router.post("/tugs/hold-plan", response_model=TugPlanResponse,
             summary="Tugs needed to relieve overloaded lines on a moored ship")
def hold_plan(req: Annotated[HoldTugRequest, Body(openapi_examples=ex("tugs_hold_plan"))]):
    return impl.hold_plan(req)


@router.post("/windows/berthing", response_model=BerthingWindowsResponse,
             summary="Time windows with low current and gusts for berthing")
def berthing_windows(req: Annotated[BerthingWindowRequest, Body(openapi_examples=ex("windows_berthing"))]):
    return impl.windows(req)
