"""Persisted reference geometry captured by planning, never resolved during sheet rendering."""

from pydantic import Field

from mooring.core.envelopes import resolved_inputs_hash
from mooring.core.schemas import AnalyzeResponse, Berth, EnvironmentSnapshot, ManifestRecord, Model, MooringConfig, Offset, ShipClass

from .forecast import optional_wire_schema


class PlanGeometrySnapshot(Model):
    wire_omitted_defaults = {"reference_records": None}
    reference_records: list[ManifestRecord] | None = Field(default=None, json_schema_extra=optional_wire_schema,
        description="All immutable reference revisions used by the saved analysis; absent on legacy snapshots.")
    ship: ShipClass
    berth: Berth
    ship_revision: str
    berth_revision: str
    analysis_result_id: str
    config: MooringConfig
    offset: Offset
    environment: EnvironmentSnapshot
    unavailable_reason: str | None = None


def capture_geometry(ship: ShipClass, berth: Berth, analysis: AnalyzeResponse,
                     config: MooringConfig, environment: EnvironmentSnapshot) -> PlanGeometrySnapshot:
    """Match the saved planner references to the solver's recorded reference revisions.

    An unversioned or concurrently changed reference is not evidence for a layout. No additional
    catalog read can repair that association after the assessment has already happened.
    """
    ship = ship.model_copy(deep=True)
    berth = berth.model_copy(deep=True)
    ship_revision = resolved_inputs_hash(ship)
    berth_revision = resolved_inputs_hash(berth)
    records = analysis.manifest.records if analysis.manifest else []
    reason = None
    for kind, identifier, digest in (("ship", ship.class_id, ship_revision), ("berth", berth.berth_id, berth_revision)):
        matched = [r for r in records if r.kind == kind and r.id == identifier]
        # Current modeling records use the documented sha256 prefix (23 characters).
        if len(matched) != 1 or matched[0].revision not in (digest, digest[:23]):
            reason = f"The assessed {kind} reference revision does not match the captured geometry."
            break
    if reason is None and analysis.manifest.environment_hash != resolved_inputs_hash(environment):
        reason = "The assessed environment does not match the captured geometry conditions."
    identities = _reference_identities(records)
    if reason is None and (identities is None or any(("line_spec", line.spec_id) not in identities for line in config.lines)):
        reason = "The assessed reference revisions are incomplete or unversioned."
    return PlanGeometrySnapshot(ship=ship, berth=berth, ship_revision=ship_revision,
        berth_revision=berth_revision, analysis_result_id=analysis.result_id, unavailable_reason=reason,
        reference_records=[record.model_copy(deep=True) for record in records],
        config=config.model_copy(deep=True), offset=analysis.result.offset.model_copy(deep=True),
        environment=environment.model_copy(deep=True))


def _reference_identities(records):
    if not records:
        return None
    identities = {}
    for record in records:
        key = (record.kind, record.id)
        if not record.revision or key in identities:
            return None
        identities[key] = record.revision
    return identities


def review_geometry_matches(snapshot: PlanGeometrySnapshot | None, results) -> bool:
    """Every calculation must retain the references that determined the saved solved pose."""
    if snapshot is None or snapshot.unavailable_reason or not results:
        return False
    expected = _reference_identities(snapshot.reference_records)
    if expected is None:
        return False
    for result in results:
        manifest = getattr(result, "manifest", None)
        records = manifest.records if manifest else []
        for kind, identifier, digest in (("ship", snapshot.ship.class_id, snapshot.ship_revision),
                                         ("berth", snapshot.berth.berth_id, snapshot.berth_revision)):
            matched = [r for r in records if r.kind == kind and r.id == identifier]
            if len(matched) != 1 or matched[0].revision not in (digest, digest[:23]):
                return False
        if _reference_identities(records) != expected:
            return False
    return True
