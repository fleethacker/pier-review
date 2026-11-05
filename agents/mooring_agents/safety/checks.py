"""Deterministic Safety/Brief checks, one function per stable check id."""

from __future__ import annotations

from collections.abc import Iterable

from ..physics.client import ModelingError
from ..physics.toolkit import PhysicsToolkit, calls_for
from .schemas import CheckResult


def _check(check_id: str, title: str, passed: bool, severity: str, detail: str,
           cites: list[str] | None = None) -> CheckResult:
    return CheckResult(check_id=check_id, title=title, passed=passed,
                       severity="INFO" if passed else severity, detail=detail, cites=cites or [])


async def cites_resolve(tk: PhysicsToolkit, cites: list[str]) -> CheckResult:
    missing = []
    for result_id in cites:
        try:
            await tk.client.result(result_id)
        except ModelingError:
            missing.append(result_id)
    return _check("CITES-RESOLVE", "Every cited result exists in the modeling service", not missing, "RED",
                  "All citations resolve." if not missing else f"Unresolvable: {', '.join(missing)}", cites)


def cites_in_ledger(plan_id: str, cites: list[str]) -> CheckResult:
    ledger_ids = {call.result_id for call in calls_for(plan_id)
                  if call.caller == "planner" and call.result_id}
    unlogged = [result_id for result_id in cites if result_id not in ledger_ids]
    return _check("CITES-IN-LEDGER", "Every cited result came from a logged tool call for this plan",
                  not unlogged, "RED",
                  "All citations are in the tool-call ledger." if not unlogged
                  else f"Not in ledger: {', '.join(unlogged)}", cites)


def reanalysis_not_red(reanalysis, env) -> CheckResult:
    return _check("REANALYSIS-NOT-RED", "Independent re-analysis is not RED", reanalysis.status != "RED", "RED",
                  f"Re-analysis status {reanalysis.status} at gust {env.wind_gust_kt:.0f} kt.",
                  [reanalysis.result_id])


def margin(reanalysis, target_margin_pct_wll: float) -> CheckResult:
    top = reanalysis.result.min_margin
    return _check("MARGIN", f"Highest utilization at or below {target_margin_pct_wll:.0f}% of WLL",
                  top.pct_wll <= target_margin_pct_wll, "AMBER",
                  f"{top.element_id} at {top.pct_wll:.0f}% of WLL.", [reanalysis.result_id])


def no_red_findings(reanalysis) -> CheckResult:
    red = [finding for finding in reanalysis.result.findings if finding.severity == "RED"]
    return _check("NO-RED-FINDINGS", "No RED NSTM 582 findings", not red, "RED",
                  "None." if not red else "; ".join(f"{f.rule_id}: {f.message}" for f in red),
                  [reanalysis.result_id])


def gust_threshold(forecast_gust: float, limit_wll: float | None, result_id: str) -> CheckResult:
    ratio = forecast_gust / limit_wll if limit_wll else 0.0
    return _check("GUST-THRESHOLD", "Forecast gusts stay below 80% of the plan's limiting gust", ratio < 0.8,
                  "RED" if ratio >= 1 else "AMBER",
                  f"Forecast max gust {forecast_gust:.0f} kt vs limit {limit_wll or float('nan'):.0f} kt "
                  f"({ratio:.0%}).", [result_id])


def tugs_feasible(tug_plan) -> CheckResult:
    passed = tug_plan is None or tug_plan.feasible
    return _check("TUGS-FEASIBLE", "Available tugs cover the required force", passed, "RED",
                  "Feasible." if passed else "Required bollard pull exceeds the available tugs.")


def mst_within_ship(report) -> CheckResult:
    passed = not (report and report.mst.exceeds_ship_mst)
    return _check("MST-WITHIN-SHIP", "Forecast stays within the ship's Mooring Service Type", passed, "RED",
                  report.mst.reason if report else "No intake report; MST not assessed against the forecast.")


CHECK_IDS: tuple[str, ...] = (
    "CITES-RESOLVE", "CITES-IN-LEDGER", "REANALYSIS-NOT-RED", "MARGIN",
    "NO-RED-FINDINGS", "GUST-THRESHOLD", "TUGS-FEASIBLE", "MST-WITHIN-SHIP",
)


def validate_check_set(results: Iterable[CheckResult]) -> None:
    ids = tuple(result.check_id for result in results)
    if ids != CHECK_IDS:
        raise RuntimeError(f"Safety check set changed: {ids!r}")

