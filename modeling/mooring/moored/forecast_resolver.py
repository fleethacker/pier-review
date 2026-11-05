"""Immutable supplied forecast revisions and explicit, bounded coverage checks.

This module does not acquire data or certify a provider identity. ``source_id``
and ``revision`` are declarations retained for consumers; the content hash always
identifies the actual supplied values and provenance. Scenario acquisition is a
service concern. A partial or unusable revision can still be inspected, but a
consumer must check each operation's complete interval before using its forcing.
"""
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json

from pydantic import ValidationError

from mooring import refdata
from mooring.core.envelopes import resolved_inputs_hash
from mooring.core.forecast_provenance import availability_problem
from mooring.core.schemas.environment import EnvironmentSnapshot


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise refdata.InvalidReference(f'{field} must be timezone-aware')
    return value.astimezone(UTC)


def _canonical(value):
    if isinstance(value, datetime):
        return _utc(value, 'Forecast timestamp').isoformat().replace('+00:00', 'Z')
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def input_problem(snapshot, as_of, valid_until=None):
    """Shared availability, quality and held-interval gates for a forecast sample."""
    if problem := availability_problem(snapshot, as_of, require_forecast=True):
        return problem
    if valid_until is not None:
        if valid_until.tzinfo is None or valid_until.utcoffset() is None:
            return 'Held interval end must be timezone-aware'
        if valid_until < snapshot.valid_at_utc:
            return 'Held interval end precedes its forecast snapshot'
    meta = snapshot.metadata
    for item in meta.components if meta else []:
        if item.quality in ('poor', 'suspect'):
            return f'{item.component}: source quality is poor or suspect'
        if item.valid_from_utc and snapshot.valid_at_utc < item.valid_from_utc:
            return f'{item.component}: snapshot precedes its declared validity interval'
        if item.valid_to_utc and (valid_until or snapshot.valid_at_utc) > item.valid_to_utc:
            return f'{item.component}: forecast would be held beyond its declared validity interval'
    if meta and meta.quality in ('poor', 'suspect'):
        return 'Environment quality is poor or suspect; a supported arrival cannot be established'
    if meta and meta.valid_from_utc and snapshot.valid_at_utc < meta.valid_from_utc:
        return 'Snapshot precedes its declared validity interval'
    if meta and meta.valid_to_utc and (valid_until or snapshot.valid_at_utc) > meta.valid_to_utc:
        return 'Forecast would be held beyond its declared validity interval'
    flags = {flag.lower() for quality in snapshot.quality for flag in quality.flags}
    if any(any(word in flag for word in ('missing', 'unavailable', 'stale')) for flag in flags):
        return 'Required environment component is missing, unavailable or stale'
    return None


@dataclass(frozen=True, slots=True)
class ResolvedForecast:
    """A revision contains immutable bytes, never caller-owned mutable models."""

    source: str
    source_id: str | None
    env_scenario_id: str | None
    revision: str
    content_hash: str
    binding_hash: str
    as_of_utc: datetime
    from_utc: datetime
    to_utc: datetime
    max_gap_min: int
    _snapshot_json: tuple[str, ...]
    _times: tuple[datetime, ...]

    def snapshots(self) -> tuple[EnvironmentSnapshot, ...]:
        """Return independent copies; modifying a copy cannot revise this binding."""
        return tuple(EnvironmentSnapshot.model_validate_json(item) for item in self._snapshot_json)

    def manifest(self) -> dict:
        """Return a serializable binding without allowing mutation of its identity."""
        return _canonical({
            'source': self.source, 'source_id': self.source_id,
            'env_scenario_id': self.env_scenario_id, 'revision': self.revision,
            'content_hash': self.content_hash, 'binding_hash': self.binding_hash,
            'as_of_utc': self.as_of_utc, 'from_utc': self.from_utc,
            'to_utc': self.to_utc, 'max_gap_min': self.max_gap_min,
        })

    def coverage_problem(self, start: datetime, end: datetime) -> str | None:
        """Check the entire closed operation interval, including every interior knot.

        A snapshot is held only until the next actual supplied snapshot. Even a
        short operation cannot bridge an oversized source interval. The final
        actual snapshot can be evaluated at its timestamp, never beyond it.
        """
        start, end = _utc(start, 'Coverage start'), _utc(end, 'Coverage end')
        if end < start:
            raise refdata.InvalidReference('Coverage end precedes coverage start')
        if start < self.from_utc or end > self.to_utc:
            return 'Operation lies outside the bound forecast horizon'
        first, last = bisect_right(self._times, start) - 1, bisect_right(self._times, end) - 1
        if first < 0 or self._times[-1] < end:
            return 'Forecast does not cover the full arrival, docking and holding interval'
        for index in range(first, last + 1):
            following = self._times[index + 1] if index + 1 < len(self._times) else end
            if (self._times[index] < end
                    and (following - self._times[index]).total_seconds() > self.max_gap_min * 60):
                return 'Forecast gap exceeds maximum covered interval'
            snapshot = EnvironmentSnapshot.model_validate_json(self._snapshot_json[index])
            if problem := input_problem(snapshot, self.as_of_utc, min(following, end)):
                return problem
        return None

    def require_coverage(self, start: datetime | None = None, end: datetime | None = None) -> None:
        """Reject an unusable horizon or operation rather than extrapolating it."""
        if problem := self.coverage_problem(start or self.from_utc, end or self.to_utc):
            raise refdata.InvalidReference(problem)

    def snapshot_at(self, at: datetime) -> EnvironmentSnapshot:
        """Return a copy of the actual sample held at ``at``, keeping its valid time."""
        at = _utc(at, 'Snapshot lookup time')
        self.require_coverage(at, at)
        index = bisect_right(self._times, at) - 1
        return EnvironmentSnapshot.model_validate_json(self._snapshot_json[index])


def resolve_forecast(
    series: Sequence[EnvironmentSnapshot], *, as_of_utc: datetime,
    from_utc: datetime, to_utc: datetime, max_gap_min: int = 60,
    source: str = 'supplied', source_id: str | None = None,
    env_scenario_id: str | None = None, revision: str | None = None,
    expected_content_hash: str | None = None,
) -> ResolvedForecast:
    """Freeze supplied samples and their source/as-of/horizon binding without I/O.

    The content hash covers all supplied samples and provenance. The binding hash
    additionally covers the requested horizon, cutoff, source identifiers,
    declared revision and maximum-gap policy. A caller-supplied revision never
    replaces verification of the content. Coverage errors remain inspectable via
    ``coverage_problem`` so one bad arrival does not erase other alternatives.
    """
    as_of_utc = _utc(as_of_utc, 'Planning as-of timestamp')
    from_utc, to_utc = _utc(from_utc, 'Forecast horizon start'), _utc(to_utc, 'Forecast horizon end')
    if to_utc < from_utc:
        raise refdata.InvalidReference('Forecast horizon end precedes start')
    if source not in ('supplied', 'scenario'):
        raise refdata.InvalidReference("Forecast source must be 'supplied' or 'scenario'")
    for name, value in (('source_id', source_id), ('env_scenario_id', env_scenario_id), ('revision', revision)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise refdata.InvalidReference(f'{name} must be a nonempty string when supplied')
    if (source == 'scenario') != (env_scenario_id is not None):
        raise refdata.InvalidReference('Scenario source requires env_scenario_id; supplied source forbids it')
    if type(max_gap_min) is not int or not 1 <= max_gap_min <= 180:
        raise refdata.InvalidReference('Maximum forecast gap must be an integer from 1 through 180 minutes')
    if not 2 <= len(series) <= 721:
        raise refdata.InvalidReference('Forecast series must contain between 2 and 721 snapshots')
    payloads, dates = [], []
    for snapshot in series:
        if not isinstance(snapshot, EnvironmentSnapshot):
            raise refdata.InvalidReference('Forecast series must contain EnvironmentSnapshot records')
        try:
            # Revalidate copies: model_copy and later mutation can bypass Pydantic validation.
            checked = EnvironmentSnapshot.model_validate(snapshot.model_dump(mode='python'))
            payload = _canonical(checked.model_dump(mode='python'))
        except (ValidationError, ValueError, TypeError) as exc:
            raise refdata.InvalidReference(f'Invalid forecast snapshot: {exc}') from exc
        if payload.get('metadata', {}).get('components'):
            payload['metadata']['components'].sort(key=lambda component: component['component'])
        payloads.append(payload)
        dates.append(_utc(checked.valid_at_utc, 'Forecast timestamp'))
    if any(later <= earlier for earlier, later in zip(dates, dates[1:])):
        raise refdata.InvalidReference('Forecast timestamps must be strictly increasing and unique')
    content_hash = resolved_inputs_hash({'forecast': payloads})
    if expected_content_hash is not None and expected_content_hash != content_hash:
        raise refdata.InvalidReference('Forecast content hash does not match the requested revision')
    revision = revision if revision is not None else content_hash
    binding = _canonical({
        'source': source, 'source_id': source_id, 'env_scenario_id': env_scenario_id,
        'revision': revision, 'content_hash': content_hash, 'as_of_utc': as_of_utc,
        'from_utc': from_utc, 'to_utc': to_utc, 'max_gap_min': max_gap_min,
    })
    return ResolvedForecast(
        source=source, source_id=source_id, env_scenario_id=env_scenario_id,
        revision=revision, content_hash=content_hash, binding_hash=resolved_inputs_hash(binding),
        as_of_utc=as_of_utc, from_utc=from_utc, to_utc=to_utc, max_gap_min=max_gap_min,
        _snapshot_json=tuple(json.dumps(item, sort_keys=True, separators=(',', ':'), allow_nan=False)
                             for item in payloads), _times=tuple(dates),
    )
