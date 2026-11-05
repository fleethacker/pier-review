"""Bounded static assessments across candidate arrivals, preserving forecast coverage.

Snapshots represent piecewise-constant forcing until the next sample, at most max_gap_min.
This sampling assumption cannot establish transient docking safety or resolve sub-sample peaks.
"""
from bisect import bisect_right
from datetime import timedelta

from mooring import refdata
from mooring.core.envelopes import envelope, resolved_inputs_hash
from mooring.core import store
from mooring.core.schemas import AnalyzeRequest, RecommendRequest, Validity, ValidityReason, ResultManifest, ManifestRecord
from mooring.core.schemas.forecast_planning import (
    DockingArrivalWindow, DockingConditionResult, ForecastDockingRequest, ForecastDockingResponse, ForecastDockingResult,
    ForecastBinding, ForecastResolutionManifest,
)
from mooring.tugs.validation import assignment_errors
from mooring.mechanics import equilibrium as eq
from . import search, solver
from .forecast_resolver import input_problem as _input_problem
from .forecast_service import resolve_docking

RECHECK = ['New forecast issuance or missing/stale component', 'Arrival or operation duration changes',
           'Ship, loading, berth, lines, fittings or tug availability changes',
           'Observed conditions depart from assessed forecast; repeat independent review before use']
LIMITATIONS = ['Static line/holding assessment, not a validated docking maneuver or contact simulation.',
              'Sampled forcing is held until the next sample only within the stated maximum gap; intervening peaks may be missed.',
              'Line installation length is fixed at each candidate arrival tide; no automatic tending.',
              'No qualified UKC, traffic, wake, dynamic-wave or line-handling approval is supplied.',
              'A supported window is conditional on the stated forecast, assets and continuous tug availability.']


def _assess_condition(req, config, snapshot, install_level):
    try:
        response = solver.analyze(AnalyzeRequest(ship_class_id=req.ship_class_id, loading=req.loading,
            berth_id=req.berth_id, config=config, environment=snapshot, tugs=req.tugs, mst=req.mst,
            installed_at_water_level_mllw_ft=install_level))
    except refdata.InvalidReference as exc:
        reason = ValidityReason(code='FORECAST_CONDITION_INPUT_INVALID', message=str(exc),
                                affected_components=['forecast', 'mooring'])
        return DockingConditionResult(valid_at_utc=snapshot.valid_at_utc,
            installed_at_water_level_mllw_ft=install_level, analysis_result_id=None,
            outcome='invalid', max_pct_wll=None, governing_element=None,
            validity=Validity(state='invalid', reasons=[reason]), reasons=[reason.message])
    validity = response.validity
    codes = {r.code for r in validity.reasons} if validity else set()
    outcome = ('undetermined' if 'NO_EQUILIBRIUM_FOUND' in codes else
               'invalid' if validity is None or validity.state in ('invalid', 'unknown') else
               'overloaded' if response.status == 'RED' or response.result.min_margin.pct_wll > req.target_pct_wll else
               'within_target')
    return DockingConditionResult(valid_at_utc=snapshot.valid_at_utc,
        installed_at_water_level_mllw_ft=install_level,
        analysis_result_id=response.result_id, outcome=outcome,
        max_pct_wll=response.result.min_margin.pct_wll if outcome not in ('invalid', 'undetermined') else None,
        governing_element=response.result.min_margin.element_id, validity=validity,
        reasons=[r.message for r in validity.reasons] if validity else ['Unknown validity'])


def assess(req: ForecastDockingRequest, ctx=None) -> ForecastDockingResponse:
    if ctx is not None:
        ctx.check_cancelled()
    original_request = req
    resolved = resolve_docking(req)
    req = req.model_copy(deep=True, update={'forecast': list(resolved.snapshots())})
    forecast_manifest = ForecastResolutionManifest.model_validate(resolved.manifest())
    ship = refdata.ship(req.ship_class_id)
    berth = refdata.berth(req.berth_id)
    refdata.loading(ship, req.loading)
    errors = assignment_errors(ship, req.tugs, refdata.tugs())
    if errors:
        raise refdata.InvalidReference('; '.join(errors))
    dates = [snapshot.valid_at_utc for snapshot in req.forecast]
    config, recommendation_id = req.config, None
    if req.optimize_lines:
        # Only conditions relevant to these candidate operations enter the search; no later-issued data can influence it.
        end = req.arrival_to_utc + timedelta(hours=req.operation_hours + req.holding_hours)
        relevant = [snapshot for snapshot in req.forecast
                    if req.arrival_from_utc - timedelta(minutes=req.max_gap_min) <= snapshot.valid_at_utc <= end
                    and _input_problem(snapshot, req.as_of_utc) is None]
        if relevant:
            recommendation = search.recommend(RecommendRequest(ship_class_id=req.ship_class_id, loading=req.loading,
                berth_id=req.berth_id, side_to=config.side_to, ship_x_ft=config.ship_x_ft, standoff_ft=config.standoff_ft,
                design_mst=req.mst, design_basis='forecast_only', forecast_env=relevant, tugs=req.tugs,
                tide_levels_ft=[relevant[0].water_level_mllw_ft], max_evaluations=req.search_budget, max_candidates=1), ctx)
            recommendation_id = recommendation.result_id
            if recommendation.result.candidates:
                config = recommendation.result.candidates[0].config
    cache, conditions, windows = {}, [], []
    evaluations, complete = 0, True
    arrival = req.arrival_from_utc
    while arrival <= req.arrival_to_utc:
        if ctx is not None:
            ctx.check_cancelled()
        operation_end = arrival + timedelta(hours=req.operation_hours)
        end = operation_end + timedelta(hours=req.holding_hours)
        first = bisect_right(dates, arrival) - 1
        last = bisect_right(dates, end) - 1
        reasons, checks = [], []
        install_level = None
        coverage_problem = resolved.coverage_problem(arrival, end, check_inputs=False)
        if coverage_problem:
            reasons.append(coverage_problem)
        else:
            install_level = req.forecast[first].water_level_mllw_ft
            for index in range(first, last + 1):
                if ctx is not None:
                    ctx.check_cancelled()
                snapshot = req.forecast[index]
                valid_until = min(dates[index + 1], end) if index + 1 < len(dates) else end
                problem = _input_problem(snapshot, req.as_of_utc, valid_until)
                key = (index, install_level, problem)
                if key not in cache:
                    if problem:
                        checked = DockingConditionResult(valid_at_utc=snapshot.valid_at_utc,
                            analysis_result_id=None, outcome='unavailable', max_pct_wll=None,
                            governing_element=None, validity=None, reasons=[problem])
                    elif evaluations >= req.max_evaluations:
                        complete = False
                        checked = DockingConditionResult(valid_at_utc=snapshot.valid_at_utc,
                            analysis_result_id=None, outcome='undetermined', max_pct_wll=None,
                            governing_element=None, validity=None, reasons=['Evaluation budget exhausted'])
                    else:
                        evaluations += 1
                        checked = _assess_condition(req, config, snapshot, install_level)
                        if ctx is not None:
                            ctx.progress(min(evaluations / req.max_evaluations, .95), 'Assessing forecast docking conditions')
                    cache[key] = checked
                    conditions.append(checked)
                checks.append(cache[key])
        rank = {'within_target': 0, 'overloaded': 1, 'undetermined': 2, 'invalid': 3, 'unavailable': 4}
        outcome = 'unavailable' if reasons else max((c.outcome for c in checks), key=rank.get, default='unavailable')
        peak = max((c for c in checks if c.max_pct_wll is not None), key=lambda c: c.max_pct_wll, default=None)
        if outcome == 'within_target' and any(c.validity.state == 'limited' for c in checks):
            outcome = 'supported_limited'
        windows.append(DockingArrivalWindow(arrival_utc=arrival, operation_end_utc=operation_end, holding_end_utc=end,
            installed_at_water_level_mllw_ft=install_level,
            outcome=outcome, max_pct_wll=peak.max_pct_wll if peak else None,
            governing_at_utc=peak.valid_at_utc if peak else None, governing_element=peak.governing_element if peak else None,
            analysis_result_ids=[c.analysis_result_id for c in checks if c.analysis_result_id],
            reasons=reasons + list(dict.fromkeys(reason for c in checks if c.outcome != 'within_target' for reason in c.reasons))))
        arrival += timedelta(minutes=req.arrival_step_min)
    supported = [w for w in windows if w.outcome in ('within_target', 'supported_limited')]
    selected = min(supported, key=lambda w: (w.max_pct_wll, w.arrival_utc)) if supported else None
    selected_config = None
    if selected:
        # Resolve the same installation assumption without another solve. Explicit paid-out lengths
        # let a consumer recheck later tides without accidentally reinstalling every line there.
        initial = req.forecast[bisect_right(dates, selected.arrival_utc)-1]
        system = eq.build_system(ship, berth, config, {line.spec_id: refdata.line(line.spec_id) for line in config.lines},
            initial, loading=req.loading, lines_wet=True, tugs=req.tugs,
            install_water_level_ft=selected.installed_at_water_level_mllw_ft)
        selected_config = config.model_copy(update={"lines": [line.ln.model_copy(update={
            "paid_out_unstretched_length_ft": line.model.rest_length_ft, "pretension_lbf": None, "slack_ft": None,
            "condition": "wet" if line.wet else "dry",
        }) for line in system.lines]})
    unusable = all(w.outcome in ('invalid', 'unavailable', 'undetermined') for w in windows)
    validity = Validity(state='invalid' if unusable else 'limited', reasons=[ValidityReason(code='FORECAST_DOCKING_STATIC_ONLY',
        message='Forecast sampling and static equilibrium do not qualify a docking maneuver or line-handling evolution.',
        affected_components=['forecast', 'docking'])])
    if unusable:
        validity.reasons.append(ValidityReason(code='NO_USABLE_ARRIVAL_ASSESSMENT',
            message='No arrival has a complete usable static assessment; inspect unavailable, invalid or undetermined window outcomes. This does not prove physical infeasibility.',
            affected_components=['forecast', 'docking']))
    timing_limits = (['Short-lead reassessment of supplied conditions; this does not establish a 24-hour advance forecast.']
                     if req.arrival_from_utc < req.as_of_utc + timedelta(hours=24) else [])
    component_provenance = [item for snap in req.forecast if snap.metadata for item in snap.metadata.components]
    unknown_issuance = any(item.basis == 'prediction' and item.issued_at_utc is None for item in component_provenance)
    result = ForecastDockingResult(forecast_manifest=forecast_manifest, as_of_utc=req.as_of_utc, forecast_start_utc=dates[0], forecast_end_utc=dates[-1],
        issued_at_utc=sorted({s.metadata.issued_at_utc for s in req.forecast if s.metadata and s.metadata.issued_at_utc}
                            | {item.issued_at_utc for item in component_provenance if item.issued_at_utc}),
        retrieved_at_utc=sorted({item.retrieved_at_utc for item in component_provenance if item.retrieved_at_utc}),
        sources=sorted({s.metadata.source or s.source if s.metadata else s.source for s in req.forecast}
                       | {item.source for item in component_provenance}),
        config=config, tugs=req.tugs, recommendation_result_id=recommendation_id,
        selected_config=selected_config,
        installed_at_water_level_mllw_ft=selected.installed_at_water_level_mllw_ft if selected else None,
        selected_arrival_utc=selected.arrival_utc if selected else None, windows=windows, conditions=conditions,
        evaluations=evaluations, complete=complete, recheck_triggers=RECHECK,
        limitations=LIMITATIONS + timing_limits + (['Some component issue times are unknown; retrieval establishes only an available-by bound, not issuance or forecast freshness.'] if unknown_issuance else []) + (['Input contains synthetic scenario data; this is not a public weather forecast.']
                                  if any(s.source in ('scenario', 'mock') for s in req.forecast) else []))
    # Random result IDs remain audit references, never part of reproducible input identity.
    request_snapshot = original_request.model_dump(mode='json')
    # Hash effective selection rather than optional request syntax or validation pins.
    request_snapshot['forecast_binding'] = ForecastBinding(
        source=resolved.source, source_id=resolved.source_id, env_scenario_id=resolved.env_scenario_id,
        revision=resolved.revision, expected_content_hash=resolved.content_hash).model_dump(mode='json')
    if original_request.forecast is not None:
        request_snapshot['forecast'] = [s.model_dump(mode='json') for s in req.forecast]
        request_snapshot.pop('forecast_step_min', None)  # Supplied samples are never resampled.
    analysis_ids = [c.analysis_result_id for c in conditions if c.analysis_result_id]
    assets = {'ship': ship.model_dump(mode='json'), 'berth': berth.model_dump(mode='json'),
              'lines': ({spec.spec_id: spec.model_dump(mode='json') for spec in refdata.lines()}
                        if req.optimize_lines else
                        {line.spec_id: refdata.line(line.spec_id).model_dump(mode='json') for line in config.lines}),
              'tugs': {tug.tug_id: tug.model_dump(mode='json') for tug in refdata.tugs()
                       if any(assignment.tug_id == tug.tug_id for assignment in req.tugs)}}
    snapshot = {'request': request_snapshot, 'config': config.model_dump(mode='json'),
                'selected_config': selected_config.model_dump(mode='json') if selected_config else None,
                'installed_at_water_level_mllw_ft': result.installed_at_water_level_mllw_ft,
                'forecast_manifest': forecast_manifest.model_dump(mode='json'),
                'forecast': [s.model_dump(mode='json') for s in req.forecast], 'assets': assets,
                'code_version': 'mooring.forecast_docking@1.1.0'}
    digest = resolved_inputs_hash(snapshot)
    store.save_snapshot(digest, snapshot)
    semantic_result = result.model_dump(mode='json')
    semantic_result.pop('recommendation_result_id')
    for condition in semantic_result['conditions']:
        condition.pop('analysis_result_id')
    for window in semantic_result['windows']:
        window.pop('analysis_result_ids')
    result.result_hash = resolved_inputs_hash({'resolved_inputs_hash': digest, 'result': semantic_result})
    records = [ManifestRecord(kind='analysis_result', id=rid) for rid in analysis_ids]
    if recommendation_id:
        records.append(ManifestRecord(kind='recommendation_result', id=recommendation_id))
    records.append(ManifestRecord(kind='forecast', id=resolved.binding_hash, revision=resolved.revision))
    manifest = ResultManifest(resolved_inputs_hash=digest, code_version='mooring.forecast_docking@1.1.0',
        records=records, environment_hash=resolved.content_hash,
        numerical_settings={'max_gap_min': req.max_gap_min, 'max_evaluations': req.max_evaluations})
    return envelope(ForecastDockingResponse, model='mooring.forecast_docking', model_version='1.1.0',
        backend='real', request=original_request, result=result, manifest=manifest, status='AMBER' if selected else 'RED', validity=validity,
        assumptions=[f'Forecast sampled/held with maximum gap {req.max_gap_min} minutes.',
                     'Target is a utilization bound on supplied forecast conditions, not an MST design certification.',
                     *LIMITATIONS, *timing_limits])
