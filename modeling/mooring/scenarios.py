"""In-memory scenario store (M2): the UI's save files. Swap for SQLite when persistence is needed."""

from mooring import refdata
from mooring.core.schemas import EnvironmentSnapshot, Scenario, ScenarioCreate

from mooring import environment
from mooring.core.envelopes import new_id, utcnow
from mooring.core.store import DocStore

_store = DocStore("scenario", Scenario)


def create(req: ScenarioCreate) -> Scenario:
    refdata.ship(req.ship_class_id)
    refdata.berth(req.berth_id)
    sc = Scenario(**req.model_dump(), scenario_id=new_id("scn"), created_at_utc=utcnow())
    _store[sc.scenario_id] = sc
    return sc


def get(scenario_id: str) -> Scenario:
    if scenario_id not in _store:
        raise refdata.NotFound(f"Scenario '{scenario_id}' not found")
    return _store[scenario_id]


def list_all() -> list[Scenario]:
    return list(_store.values())


def environment_for(sc: Scenario) -> EnvironmentSnapshot:
    if sc.env_source.mode == "scenario" and sc.env_source.env_scenario_id:
        return environment.scenario_snapshot(sc.env_source.env_scenario_id, utcnow())
    return environment.now(sc.berth_id)
