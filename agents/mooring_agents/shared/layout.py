"""Persisted reference geometry captured by planning, never resolved during sheet rendering."""

from mooring.core.envelopes import resolved_inputs_hash
from mooring.core.schemas import AnalyzeResponse, Berth, EnvironmentSnapshot, Model, MooringConfig, Offset, ShipClass


class PlanGeometrySnapshot(Model):
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
    return PlanGeometrySnapshot(ship=ship, berth=berth, ship_revision=ship_revision,
        berth_revision=berth_revision, analysis_result_id=analysis.result_id, unavailable_reason=reason,
        config=config.model_copy(deep=True), offset=analysis.result.offset.model_copy(deep=True),
        environment=environment.model_copy(deep=True))


def review_geometry_matches(snapshot: PlanGeometrySnapshot | None, results) -> bool:
    """Every independent-review calculation must use the same captured ship/berth references."""
    if snapshot is None or snapshot.unavailable_reason or not results:
        return False
    for result in results:
        manifest = getattr(result, "manifest", None)
        records = manifest.records if manifest else []
        for kind, identifier, digest in (("ship", snapshot.ship.class_id, snapshot.ship_revision),
                                         ("berth", snapshot.berth.berth_id, snapshot.berth_revision)):
            matched = [r for r in records if r.kind == kind and r.id == identifier]
            if len(matched) != 1 or matched[0].revision not in (digest, digest[:23]):
                return False
    return True
