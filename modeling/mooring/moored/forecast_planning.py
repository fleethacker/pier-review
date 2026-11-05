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
)
from mooring.tugs.validation import assignment_errors
from . import search, solver

RECHECK = ['New forecast issuance or missing/stale component', 'Arrival or operation duration changes',
           'Ship, loading, berth, lines, fittings or tug availability changes',
           'Observed conditions depart from assessed forecast; repeat independent review before use']
LIMITATIONS = ['Static line/holding assessment, not a validated docking maneuver or contact simulation.',
              'Sampled forcing is held until the next sample only within the stated maximum gap; intervening peaks may be missed.',
              'Line installation length is fixed at each candidate arrival tide; no automatic tending.',
              'No qualified UKC, traffic, wake, dynamic-wave or line-handling approval is supplied.',
              'A supported window is conditional on the stated forecast, assets and continuous tug availability.']


def _input_problem(snapshot, as_of):
    meta = snapshot.metadata
    if meta and meta.issued_at_utc and meta.issued_at_utc > as_of:
        return 'Forecast was issued after planning as-of time'
    if snapshot.source in ('live', 'ship_sensor') and snapshot.valid_at_utc > as_of:
        return 'Future observations cannot be used as a forecast'
    flags = {flag.lower() for quality in snapshot.quality for flag in quality.flags}
    if any(any(word in flag for word in ('missing', 'unavailable', 'stale')) for flag in flags):
        return 'Required environment component is missing, unavailable or stale'
    return None


def assess(req: ForecastDockingRequest, ctx=None) -> ForecastDockingResponse:
    ship = refdata.ship(req.ship_class_id)
    refdata.berth(req.berth_id)
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
        if first < 0 or dates[-1] < end:
            reasons.append('Forecast does not cover the full arrival, docking and holding interval')
        elif any((dates[i + 1] - dates[i]).total_seconds() > req.max_gap_min * 60
                 for i in range(first, min(last + 1, len(dates) - 1)) if dates[i] < end):
            reasons.append('Forecast gap exceeds maximum covered interval')
        else:
            install_level = req.forecast[first].water_level_mllw_ft
            for index in range(first, last + 1):
                if ctx is not None:
                    ctx.check_cancelled()
                snapshot = req.forecast[index]
                key = (index, install_level)
                if key not in cache:
                    problem = _input_problem(snapshot, req.as_of_utc)
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
                        response = solver.analyze(AnalyzeRequest(ship_class_id=req.ship_class_id, loading=req.loading,
                            berth_id=req.berth_id, config=config, environment=snapshot, tugs=req.tugs, mst=req.mst,
                            installed_at_water_level_mllw_ft=install_level))
                        evaluations += 1
                        validity = response.validity
                        codes = {r.code for r in validity.reasons} if validity else set()
                        outcome = ('undetermined' if 'NO_EQUILIBRIUM_FOUND' in codes else
                                   'invalid' if validity is None or validity.state in ('invalid', 'unknown') else
                                   'overloaded' if response.status == 'RED' or response.result.min_margin.pct_wll > req.target_pct_wll else
                                   'within_target')
                        checked = DockingConditionResult(valid_at_utc=snapshot.valid_at_utc,
                            analysis_result_id=response.result_id, outcome=outcome,
                            max_pct_wll=response.result.min_margin.pct_wll if outcome not in ('invalid', 'undetermined') else None,
                            governing_element=response.result.min_margin.element_id, validity=validity,
                            reasons=[r.message for r in validity.reasons] if validity else ['Unknown validity'])
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
            outcome=outcome, max_pct_wll=peak.max_pct_wll if peak else None,
            governing_at_utc=peak.valid_at_utc if peak else None, governing_element=peak.governing_element if peak else None,
            analysis_result_ids=[c.analysis_result_id for c in checks if c.analysis_result_id],
            reasons=reasons + list(dict.fromkeys(reason for c in checks if c.outcome != 'within_target' for reason in c.reasons))))
        arrival += timedelta(minutes=req.arrival_step_min)
    supported = [w for w in windows if w.outcome in ('within_target', 'supported_limited')]
    selected = min(supported, key=lambda w: (w.max_pct_wll, w.arrival_utc)) if supported else None
    validity = Validity(state='limited', reasons=[ValidityReason(code='FORECAST_DOCKING_STATIC_ONLY',
        message='Forecast sampling and static equilibrium do not qualify a docking maneuver or line-handling evolution.',
        affected_components=['forecast', 'docking'])])
    result = ForecastDockingResult(as_of_utc=req.as_of_utc, forecast_start_utc=dates[0], forecast_end_utc=dates[-1],
        issued_at_utc=sorted({s.metadata.issued_at_utc for s in req.forecast if s.metadata and s.metadata.issued_at_utc}),
        sources=sorted({s.metadata.source or s.source if s.metadata else s.source for s in req.forecast}),
        config=config, tugs=req.tugs, recommendation_result_id=recommendation_id,
        selected_arrival_utc=selected.arrival_utc if selected else None, windows=windows, conditions=conditions,
        evaluations=evaluations, complete=complete, recheck_triggers=RECHECK,
        limitations=LIMITATIONS + (['Input contains synthetic scenario data; this is not a public weather forecast.']
                                  if any(s.source in ('scenario', 'mock') for s in req.forecast) else []))
    snapshot = {'request': req.model_dump(mode='json'), 'config': config.model_dump(mode='json'),
                'analysis_result_ids': [c.analysis_result_id for c in conditions if c.analysis_result_id],
                'recommendation_result_id': recommendation_id}
    digest = resolved_inputs_hash(snapshot)
    store.save_snapshot(digest, snapshot)
    manifest = ResultManifest(resolved_inputs_hash=digest, code_version='mooring.forecast_docking@1.0.0',
        records=[ManifestRecord(kind='analysis_result', id=rid) for rid in snapshot['analysis_result_ids']],
        environment_hash=resolved_inputs_hash({'forecast': [s.model_dump(mode='json') for s in req.forecast]}),
        numerical_settings={'max_gap_min': req.max_gap_min, 'max_evaluations': req.max_evaluations})
    return envelope(ForecastDockingResponse, model='mooring.forecast_docking', model_version='1.0.0',
        backend='real', request=req, result=result, manifest=manifest, status='AMBER' if selected else 'RED', validity=validity,
        assumptions=[f'Forecast sampled/held with maximum gap {req.max_gap_min} minutes.',
                     'Target is a utilization bound on supplied forecast conditions, not an MST design certification.',
                     *LIMITATIONS])
