"""Reference data loader (module M2). YAML is the seed data; confirmed runtime berths use the configured SQLite store."""

from functools import cache
from pathlib import Path
from threading import RLock

import yaml

from mooring.core import store
from mooring.core.schemas import Berth, LineSpec, ShipClass, TugSpec

ROOT = Path(__file__).parent


class NotFound(KeyError):
    """Raised when an id in the URL doesn't exist; the API turns it into HTTP 404."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else "Not found"


class InvalidReference(ValueError):
    """Raised when a request body refers to something that doesn't exist; the API turns it into HTTP 422."""


class ReferenceConflict(ValueError):
    """An existing reference ID cannot be rebound to different asset data."""


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


_BERTH_NAMESPACE = "reference_berths"
_berths_lock = RLock()


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
    with _berths_lock:
        saved = [Berth.model_validate_json(row[0]) for row in store.db().execute(
            "SELECT body FROM docs WHERE namespace=? ORDER BY key", (_BERTH_NAMESPACE,)
        )]
        seeds = _seed_berths()
        for b in saved:
            if b.berth_id in seeds and b != seeds[b.berth_id]:
                raise InvalidReference(f"Stored berth '{b.berth_id}' conflicts with the installed seed catalog")
        return [b.model_copy(deep=True) for b in [*seeds.values(), *(b for b in saved if b.berth_id not in seeds)]]


def berth(berth_id: str) -> Berth:
    with _berths_lock:
        rows = store.db().execute("SELECT body FROM docs WHERE namespace=? AND key=?", (_BERTH_NAMESPACE, berth_id))
        saved = Berth.model_validate_json(rows[0][0]) if rows else None
        seed = _seed_berths().get(berth_id)
        if saved is not None and seed is not None and saved != seed:
            raise InvalidReference(f"Stored berth '{berth_id}' conflicts with the installed seed catalog")
        found = saved or seed
        if found is None:
            raise NotFound(f"Berth '{berth_id}' not found")
        return found.model_copy(deep=True)


def add_berth(b: Berth) -> Berth:
    """Register a shared immutable reference; MOORING_DB controls restart durability.

    This catalog intentionally remains shared-readable, unlike principal-owned scenarios.
    SQLite's unique namespace/key also protects against concurrent registrations.
    """
    candidate = b.model_copy(deep=True)
    with _berths_lock:
        seed = _seed_berths().get(candidate.berth_id)
        if seed is None:
            store.db().execute("INSERT OR IGNORE INTO docs VALUES (?,?,?)",
                               (_BERTH_NAMESPACE, candidate.berth_id, candidate.model_dump_json()))
        existing = berth(candidate.berth_id)
        if existing != candidate:
            raise ReferenceConflict(f"Berth '{candidate.berth_id}' already exists with different data; use a new berth_id for a revision")
        return existing


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
