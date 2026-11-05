"""Reference data loader (module M2). YAML in this folder is the seed data; berths added at runtime live in memory."""

from functools import cache
from pathlib import Path

import yaml

from mooring.core.schemas import Berth, LineSpec, ShipClass, TugSpec

ROOT = Path(__file__).parent


class NotFound(KeyError):
    """Raised when an id in the URL doesn't exist; the API turns it into HTTP 404."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else "Not found"


class InvalidReference(ValueError):
    """Raised when a request body refers to something that doesn't exist; the API turns it into HTTP 422."""


def _load(path: Path):
    with path.open() as f:
        return yaml.safe_load(f)


@cache
def _ships() -> dict[str, ShipClass]:
    items = [ShipClass.model_validate(_load(p)) for p in sorted((ROOT / "ships").glob("*.yaml"))]
    return {s.class_id: s for s in items}


@cache
def _lines() -> dict[str, LineSpec]:
    return {d["spec_id"]: LineSpec.model_validate(d) for d in _load(ROOT / "lines.yaml")}


@cache
def _seed_berths() -> dict[str, Berth]:
    items = [Berth.model_validate(_load(p)) for p in sorted((ROOT / "berths").glob("*.yaml"))]
    return {b.berth_id: b for b in items}


@cache
def _tugs() -> dict[str, TugSpec]:
    return {d["tug_id"]: TugSpec.model_validate(d) for d in _load(ROOT / "tugs.yaml")}


_runtime_berths: dict[str, Berth] = {}


def ships() -> list[ShipClass]:
    return [s.model_copy(deep=True) for s in _ships().values()]


def ship(class_id: str) -> ShipClass:
    try:
        return _ships()[class_id].model_copy(deep=True)  # defensive copy: callers cannot edit the catalog
    except KeyError:
        raise NotFound(f"Ship class '{class_id}' not found") from None


def lines() -> list[LineSpec]:
    return [s.model_copy(deep=True) for s in _lines().values()]


def line(spec_id: str) -> LineSpec:
    try:
        return _lines()[spec_id].model_copy(deep=True)
    except KeyError:
        raise NotFound(f"Line spec '{spec_id}' not found") from None


def berths() -> list[Berth]:
    return [b.model_copy(deep=True) for b in [*_seed_berths().values(), *_runtime_berths.values()]]


def berth(berth_id: str) -> Berth:
    found = _runtime_berths.get(berth_id) or _seed_berths().get(berth_id)
    if found is None:
        raise NotFound(f"Berth '{berth_id}' not found")
    return found.model_copy(deep=True)


def add_berth(b: Berth) -> Berth:
    _runtime_berths[b.berth_id] = b.model_copy(deep=True)
    return b


def tugs() -> list[TugSpec]:
    return [t.model_copy(deep=True) for t in _tugs().values()]


def tug(tug_id: str) -> TugSpec:
    try:
        return _tugs()[tug_id].model_copy(deep=True)
    except KeyError:
        raise NotFound(f"Tug '{tug_id}' not found") from None


def loading(ship_class: ShipClass, name: str):
    for lc in ship_class.loading_conditions:
        if lc.name == name:
            return lc
    raise NotFound(f"Loading condition '{name}' not found for {ship_class.class_id}")
