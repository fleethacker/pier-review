from typing import Annotated

from fastapi import APIRouter, Body

from mooring import refdata
from mooring.core.schemas import (
    Berth,
    EnvironmentSnapshot,
    BerthCreated,
    BerthSummary,
    LineSpec,
    Scenario,
    ScenarioCreate,
    ShipClass,
    ShipClassSummary,
    TugSpec,
)
from mooring.examples import ex
from mooring.demo_cases import docking_cases
from mooring.core.schemas.demo import DockingDemoCase

from ..backend import scenarios
from .env import guarded

router = APIRouter(tags=["M2 Reference data"])


@router.get("/ships", response_model=list[ShipClassSummary])
def list_ships():
    return [ShipClassSummary(class_id=s.class_id, name=s.name, hull_type=s.hull_type, loa_ft=s.loa_ft,
                             beam_ft=s.beam_ft, mst_class=s.mst_class, has_fittings=bool(s.fittings))
            for s in refdata.ships()]


@router.get("/ships/{class_id}", response_model=ShipClass)
def get_ship(class_id: str):
    return refdata.ship(class_id)


@router.get("/lines", response_model=list[LineSpec])
def list_lines():
    return refdata.lines()


@router.get("/lines/{spec_id}", response_model=LineSpec)
def get_line(spec_id: str):
    return refdata.line(spec_id)


@router.get("/berths", response_model=list[BerthSummary])
def list_berths():
    return [BerthSummary(berth_id=b.berth_id, name=b.name, face_length_ft=b.face_length_ft,
                         min_depth_mllw_ft=min(p.depth_mllw_ft for p in b.depth_profile),
                         fitting_count=len(b.fittings), confidence=b.provenance.confidence)
            for b in refdata.berths()]


@router.get("/berths/{berth_id}", response_model=Berth)
def get_berth(berth_id: str):
    return refdata.berth(berth_id)


@router.post("/berths", response_model=BerthCreated, status_code=201,
             summary="Add or replace a berth (from the canvas or a confirmed vision draft)")
def create_berth(berth: Berth):
    refdata.add_berth(berth)
    return BerthCreated(berth_id=berth.berth_id)


@router.get("/tugs", response_model=list[TugSpec])
def list_tugs():
    return refdata.tugs()


@router.post("/scenarios", response_model=Scenario, status_code=201, summary="Save a scenario")
def create_scenario(req: Annotated[ScenarioCreate, Body(openapi_examples=ex("scenario"))]):
    return scenarios.create(req)


@router.get("/scenarios", response_model=list[Scenario])
def list_scenarios():
    return scenarios.list_all()


@router.get("/scenarios/{scenario_id}", response_model=Scenario)
def get_scenario(scenario_id: str):
    return scenarios.get(scenario_id)


@router.get("/scenarios/{scenario_id}/environment", response_model=EnvironmentSnapshot,
            summary="Resolve the saved scenario source; explicit mock stays synthetic")
def scenario_environment(scenario_id: str):
    return guarded(scenarios.environment_for, scenarios.get(scenario_id))


@router.get("/demo/docking-cases", response_model=list[DockingDemoCase],
            summary="Named offline demo requests (seed data; not operational plans)")
def demo_docking_cases():
    return docking_cases()


from mooring.core.schemas import ForecastSeries
from mooring.core.schemas.data_simulation import SyntheticForecastRequest
from mooring.data_simulation.forecast import generate as generate_synthetic_forecast


@router.post("/data-simulation/forecast", response_model=ForecastSeries,
             summary="Generate labeled, seeded training conditions; not a weather forecast")
def synthetic_forecast(req: SyntheticForecastRequest):
    refdata.berth(req.berth_id)
    return generate_synthetic_forecast(req)


from mooring.core.schemas.berth_drafts import BerthDraftRequest, BerthDraftResponse
from mooring.refdata.drafts import build as build_berth_draft


@router.post("/berth-drafts", response_model=BerthDraftResponse,
             summary="Build an unsaved berth draft from catalog geometry and optional image anchors")
def berth_draft(req: BerthDraftRequest):
    return build_berth_draft(req)
