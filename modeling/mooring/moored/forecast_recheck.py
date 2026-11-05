"""Compare a new forecast with a stored assessment without changing or approving it.

This service performs no physics. A changed revision supplies a separate, explicit
reassessment request; the caller must submit it and obtain independent review.
"""
from datetime import timedelta

from mooring import refdata
from mooring.core import store
from mooring.core.envelopes import RESULTS, envelope, resolved_inputs_hash
from mooring.core.schemas import ManifestRecord, ResultManifest, Validity, ValidityReason
from mooring.core.schemas.forecast_planning import (
    ForecastBinding, ForecastDockingRequest, ForecastRecheckRequest,
    ForecastRecheckResponse, ForecastRecheckResult, ForecastResolutionManifest,
    ForecastResolveRequest,
)
from .forecast_service import resolve_request


def recheck(req: ForecastRecheckRequest) -> ForecastRecheckResponse:
    """Check the caller-owned prior assessment against explicitly supplied guidance."""
    # Authorize the result before touching its snapshot: snapshots have no own ACL.
    try:
        prior = RESULTS[req.prior_result_id]
    except KeyError:
        raise refdata.NotFound(f"Result '{req.prior_result_id}' not found") from None
    if prior.get('model') != 'mooring.forecast_docking':
        raise refdata.InvalidReference('prior_result_id must identify a forecast docking assessment')

    previous = current = None
    installation_tide = prior['result'].get('installed_at_water_level_mllw_ft')

    def finish(state, reasons, reassessment=None):
        result = ForecastRecheckResult(
            state=state, prior_result_id=req.prior_result_id,
            previous_forecast_manifest=previous, current_forecast_manifest=current,
            reasons=reasons, reassessment_request=reassessment,
            installed_at_water_level_mllw_ft=installation_tide,
        )
        unavailable = state == 'unavailable'
        prior_invalid = (prior.get('validity') or {}).get('state') in (None, 'unknown', 'invalid')
        validity = Validity(state='invalid' if unavailable or prior_invalid else 'limited', reasons=[
            ValidityReason(code='FORECAST_RECHECK_UNAVAILABLE' if unavailable else 'FORECAST_RECHECK_NOT_APPROVAL',
                message=('Replacement forecast cannot establish an applicable reassessment.' if unavailable else
                         'Forecast identity comparison does not perform a new physical assessment or transfer an approval.'),
                affected_components=['forecast', 'docking']),
        ])
        if prior_invalid:
            validity.reasons.append(ValidityReason(code='PRIOR_ASSESSMENT_NOT_USABLE',
                message='The prior result is invalid or has unknown validity; unchanged guidance cannot qualify it.',
                affected_components=['forecast', 'docking']))
        snapshot = {'request': req.model_dump(mode='json'), 'result': result.model_dump(mode='json')}
        digest = resolved_inputs_hash(snapshot)
        store.save_snapshot(digest, snapshot)
        manifest = ResultManifest(resolved_inputs_hash=digest, code_version='mooring.forecast_recheck@1.0.0',
            environment_hash=current.content_hash if current else None,
            records=[ManifestRecord(kind='prior_forecast_assessment', id=req.prior_result_id,
                revision=(prior.get('manifest') or {}).get('resolved_inputs_hash'))])
        return envelope(ForecastRecheckResponse, model='mooring.forecast_recheck', model_version='1.0.0',
            backend='real', request=req, result=result, manifest=manifest, validity=validity,
            status='RED' if prior.get('status') == 'RED' or unavailable else 'AMBER',
            assumptions=['Historical assessments are immutable; no prior approval transfers to a changed forecast.',
                         'This comparison does not reassess vessel loads, line handling or maneuver safety.'])

    raw_previous = prior['result'].get('forecast_manifest')
    old_digest = (prior.get('manifest') or {}).get('resolved_inputs_hash')
    if raw_previous is None or old_digest is None:
        return finish('unavailable', ['Prior assessment lacks a frozen forecast manifest; submit a new assessment.'])
    try:
        previous = ForecastResolutionManifest.model_validate(raw_previous)
    except ValueError:
        return finish('unavailable', ['Prior forecast manifest is not usable; submit a new assessment.'])
    saved = store.load_snapshot(old_digest)
    if saved is None or 'request' not in saved:
        return finish('unavailable', ['Prior resolved-input snapshot is unavailable; original operation cannot be reconstructed.'])
    try:
        saved_manifest = ForecastResolutionManifest.model_validate(saved.get('forecast_manifest'))
        old_request = ForecastDockingRequest.model_validate(saved['request'])
    except ValueError:
        return finish('unavailable', ['Prior resolved-input snapshot cannot reconstruct the assessed forecast and operation.'])
    if saved_manifest != previous:
        return finish('unavailable', ['Prior result and resolved-input snapshot disagree about forecast identity.'])
    if req.as_of_utc < old_request.as_of_utc:
        return finish('unavailable', ['Recheck as-of time precedes the original assessment as-of time.'])

    selected_arrival = prior['result'].get('selected_arrival_utc')
    if selected_arrival:
        # Reuse schema normalization rather than interpreting datetime text ourselves.
        data = old_request.model_dump(mode='json')
        data.update(arrival_from_utc=selected_arrival, arrival_to_utc=selected_arrival)
        old_request = ForecastDockingRequest.model_validate(data)
    if req.as_of_utc > old_request.arrival_from_utc:
        return finish('unavailable', ['The assessed arrival has passed; this endpoint cannot approve an operation retrospectively.'])
    end = old_request.arrival_to_utc + timedelta(hours=old_request.operation_hours + old_request.holding_hours)
    resolution_request = ForecastResolveRequest(
        berth_id=old_request.berth_id, as_of_utc=req.as_of_utc,
        from_utc=old_request.arrival_from_utc, to_utc=end, max_gap_min=old_request.max_gap_min,
        step_min=old_request.forecast_step_min,
        forecast=req.forecast, forecast_binding=req.forecast_binding,
    )
    try:
        resolved = resolve_request(resolution_request)
    except (refdata.InvalidReference, ValueError) as exc:
        return finish('unavailable', [str(exc)])
    current = ForecastResolutionManifest.model_validate(resolved.manifest())
    if problem := resolved.coverage_problem(old_request.arrival_from_utc, end):
        return finish('unavailable', [problem])

    reasons = []
    if (previous.source, previous.source_id, previous.env_scenario_id) != (
            current.source, current.source_id, current.env_scenario_id):
        reasons.append('Forecast source or environment scenario changed; recheck required.')
    if previous.revision != current.revision:
        reasons.append('Forecast revision changed; recheck required.')
    if previous.content_hash != current.content_hash:
        reasons.append('Forecast content or source provenance changed; recheck required.')
    if not reasons:
        return finish('unchanged', ['Forecast source, revision and content match the prior assessment. '
                                   'This does not transfer an approval or establish current operational suitability.'])

    replacement = old_request.model_dump(mode='json')
    replacement.update(
        as_of_utc=req.as_of_utc, allow_short_lead=True, optimize_lines=False,
        forecast=[sample.model_dump(mode='json') for sample in req.forecast] if req.forecast is not None else None,
        forecast_binding=ForecastBinding(
            source=current.source, source_id=current.source_id, env_scenario_id=current.env_scenario_id,
            revision=current.revision, expected_content_hash=current.content_hash).model_dump(mode='json'),
        config=prior['result'].get('selected_config') or prior['result']['config'],
        tugs=prior['result']['tugs'],
        installed_at_water_level_mllw_ft=installation_tide,
    )
    reassessment = ForecastDockingRequest.model_validate(replacement)
    return finish('recheck_required', reasons, reassessment)
