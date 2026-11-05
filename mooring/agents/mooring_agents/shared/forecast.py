"""Consume modeling-owned forecast identities; never resolve or interpolate physics here."""

from mooring.core.schemas.forecast_planning import ForecastResolutionManifest

from ..physics.client import ModelingError


def optional_wire_schema(schema):
    """Default values omitted on the wire must remain optional in generated clients."""
    schema.pop("default", None)


def same_forecast(left: ForecastResolutionManifest | None, right: ForecastResolutionManifest | None) -> bool:
    """Source, horizon and cutoff are included in the modeling-owned binding hash."""
    if left is None or right is None:
        return left is right
    return all(getattr(left, name) == getattr(right, name)
               for name in ("revision", "content_hash", "binding_hash"))


async def resolve_forecast(tk, request, expected=None):
    """Ask the canonical logged modeling tool and refuse silent revision replacement."""
    resolved = await tk.resolve_forecast(request.model_dump(mode="json", exclude_none=True))
    result = resolved.result
    if result.berth_id != request.berth_id:
        raise ModelingError(502, "Forecast resolver returned a different berth")
    manifest = result.forecast_manifest
    if any(getattr(manifest, name) != getattr(request, name)
           for name in ("as_of_utc", "from_utc", "to_utc", "max_gap_min")):
        raise ModelingError(502, "Forecast resolver returned a different temporal binding")
    binding = request.forecast_binding
    if (manifest.source != (binding.source if binding else "supplied")
            or manifest.source_id != (binding.source_id if binding else None)
            or manifest.env_scenario_id != (binding.env_scenario_id if binding else None)):
        raise ModelingError(502, "Forecast resolver returned a different source selection")
    if expected is not None and not same_forecast(expected, result.forecast_manifest):
        raise ModelingError(409, "Forecast binding changed; create a new Intake and explicitly reassess the plan. Historical plans and approvals were not changed.")
    if not result.coverage_complete or not result.series:
        raise ModelingError(422, "Forecast coverage unavailable: " + "; ".join(result.problems or ["No usable forecast series"]))
    if resolved.validity is None or resolved.validity.state in ("invalid", "unknown"):
        raise ModelingError(422, "Forecast resolver did not establish usable input validity")
    return resolved


def bound_samples(resolved):
    """Keep actual knots relevant to the bound interval, without generating weather."""
    result = resolved.result
    start, end = result.forecast_manifest.from_utc, result.forecast_manifest.to_utc
    preceding = [sample for sample in result.series if sample.valid_at_utc <= start]
    if not preceding:
        raise ModelingError(502, "Complete forecast response has no sample at its interval start")
    return [preceding[-1].model_copy(deep=True),
            *(sample.model_copy(deep=True) for sample in result.series if start < sample.valid_at_utc <= end)]
