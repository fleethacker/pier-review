"""HTTP-independent forecast binding service; acquisition is explicit and offline."""
from datetime import timedelta

from mooring import refdata
from mooring.core import store
from mooring.core.envelopes import envelope, resolved_inputs_hash
from mooring.core.schemas import ManifestRecord, ResultManifest, Validity, ValidityReason
from mooring.core.schemas.forecast_planning import (
    ForecastBinding, ForecastResolveRequest, ForecastResolvedResponse, ForecastResolvedResult,
    ForecastResolutionManifest,
)
from .forecast_resolver import resolve_forecast


def resolve_request(req: ForecastResolveRequest):
    """Resolve supplied snapshots or sample the explicitly selected scenario.

    Never consult the live environment mode or substitute a provider's current
    point. Public forecast composition is a separate data-provider responsibility.
    """
    req = ForecastResolveRequest.model_validate(req.model_dump(mode='python'))
    refdata.berth(req.berth_id)
    binding = req.forecast_binding or ForecastBinding()
    revision = binding.revision
    series = req.forecast
    if binding.source == 'scenario':
        from mooring.data_simulation.scenario_forecast import sample_scenario
        from mooring.environment.errors import ProviderError
        start = binding.sample_from_utc or req.from_utc
        end = binding.sample_to_utc or req.to_utc
        try:
            # Rechecks can retain earlier training samples for content identity.
            # The actual request cutoff still governs all resolver availability gates.
            series, scenario_revision = sample_scenario(binding.env_scenario_id,
                as_of_utc=min(req.as_of_utc, start), from_utc=start, to_utc=end, step_min=req.step_min)
        except ProviderError as exc:
            raise refdata.InvalidReference(f'Scenario source unavailable ({exc.kind}): {exc}') from None
        except ValueError as exc:
            raise refdata.InvalidReference(f'Scenario source returned invalid data: {exc}') from None
        revision = revision or scenario_revision
    return resolve_forecast(series, as_of_utc=req.as_of_utc,
        from_utc=req.from_utc, to_utc=req.to_utc, max_gap_min=req.max_gap_min,
        source=binding.source, source_id=binding.source_id, env_scenario_id=binding.env_scenario_id,
        revision=revision, expected_content_hash=binding.expected_content_hash)


def resolve_docking(req):
    return resolve_request(ForecastResolveRequest(berth_id=req.berth_id,
        as_of_utc=req.as_of_utc, from_utc=req.arrival_from_utc,
        to_utc=req.arrival_to_utc + timedelta(hours=req.operation_hours + req.holding_hours),
        max_gap_min=req.max_gap_min, step_min=req.forecast_step_min,
        forecast=req.forecast, forecast_binding=req.forecast_binding))


def resolve(req: ForecastResolveRequest) -> ForecastResolvedResponse:
    resolved = resolve_request(req)
    manifest = ForecastResolutionManifest.model_validate(resolved.manifest())
    series = list(resolved.snapshots())
    problem = resolved.coverage_problem(resolved.from_utc, resolved.to_utc)
    limitations = [
        'Coverage uses sampled, piecewise-constant forcing; unresolved intervening peaks remain possible.',
        'Resolution preserves supplied provenance; it does not qualify vessel behavior or approve a docking operation.',
        'Caller-declared source and revision identifiers are not independent proof of provider authenticity.',
    ]
    if any(s.source in ('mock', 'scenario') or (s.metadata and s.metadata.basis == 'scenario') for s in series):
        limitations.append('Input contains synthetic training scenarios; this is not a public weather forecast.')
    if any(c.basis == 'prediction' and c.issued_at_utc is None
           for s in series if s.metadata for c in s.metadata.components):
        limitations.append('Some issue times are unknown; retrieval establishes availability only, not forecast freshness.')
    result = ForecastResolvedResult(berth_id=req.berth_id, forecast_manifest=manifest, series=series,
        coverage_complete=problem is None, problems=[problem] if problem else [], limitations=limitations)
    snapshot = {'berth_id': req.berth_id, 'forecast_manifest': manifest.model_dump(mode='json'),
                'forecast': [s.model_dump(mode='json') for s in series]}
    digest = resolved_inputs_hash(snapshot)
    store.save_snapshot(digest, snapshot)
    validity = Validity(state='invalid' if problem else 'limited', reasons=[ValidityReason(
        code='FORECAST_COVERAGE_UNAVAILABLE' if problem else 'FORECAST_RESOLUTION_SAMPLED',
        message=problem or limitations[0], affected_components=['forecast'])])
    return envelope(ForecastResolvedResponse, model='mooring.forecast_resolver', model_version='1.0.0',
        backend='real', request=req, result=result, status='RED' if problem else 'AMBER', validity=validity,
        assumptions=limitations, manifest=ResultManifest(resolved_inputs_hash=digest,
            code_version='mooring.forecast_resolver@1.0.0', environment_hash=resolved.content_hash,
            records=[ManifestRecord(kind='forecast', id=resolved.binding_hash, revision=resolved.revision)],
            numerical_settings={'max_gap_min': req.max_gap_min}))
