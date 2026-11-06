"""Sample explicit environment scenarios without a clock or provider fallback.

Replay is a retimed training exercise, never a forecast of future conditions.
Every sample retains the complete original normalized snapshot and its hash;
source validity intervals translate with the replay clock and are not extended.
"""
from datetime import UTC, datetime, timedelta
import json

from mooring import environment, refdata
from mooring.core.envelopes import resolved_inputs_hash
from mooring.core.schemas.environment import MAX_FORECAST_SNAPSHOTS, EnvironmentMetadata, EnvironmentSnapshot, EnvScenario, StationQuality

MAX_SAMPLES = 721  # Forecast request work bound, not a physical coefficient.
MAX_STEP_MIN = 180  # Matches the maximum supported forecast hold interval.


def _utc(value, name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise refdata.InvalidReference(f'{name} must be timezone-aware')
    return value.astimezone(UTC)


def _canonical(value):
    if isinstance(value, datetime):
        return _utc(value, 'Scenario timestamp').isoformat().replace('+00:00', 'Z')
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _definition(env_scenario_id):
    # The public getter preserves ownership checks in the backing scenario store.
    scenario = environment.get_scenario(env_scenario_id)
    checked = EnvScenario.model_validate(scenario.model_dump(mode='python'))
    if checked.env_scenario_id != env_scenario_id:
        raise refdata.InvalidReference('Resolved environment scenario identity does not match the request')
    payload = _canonical(checked.model_dump(mode='python'))
    return checked, resolved_inputs_hash(payload)


def _training_snapshot(raw, scenario, revision, at, archive_at):
    raw = EnvironmentSnapshot.model_validate(raw.model_dump(mode='python'))
    original_time = _utc(raw.valid_at_utc, 'Scenario sample timestamp')
    if original_time != archive_at:
        raise refdata.InvalidReference('Scenario source did not return the requested sample time')
    original = _canonical(raw.model_dump(mode='python'))
    original_hash = resolved_inputs_hash(original)
    shift = at - archive_at
    metadata = raw.metadata.model_dump(mode='python') if raw.metadata else {}
    metadata.update(basis='scenario', source=f'Training scenario {scenario.env_scenario_id} ({scenario.kind})',
                    issued_at_utc=None)
    for field in ('valid_from_utc', 'valid_to_utc'):
        if metadata.get(field) is not None:
            metadata[field] = _utc(metadata[field], field) + shift
    for component in metadata.get('components', []):
        component.update(basis='scenario', issued_at_utc=None, retrieved_at_utc=None)
        for field in ('valid_from_utc', 'valid_to_utc'):
            if component.get(field) is not None:
                component[field] = _utc(component[field], field) + shift
        component['limitations'] = [*component.get('limitations', []),
            'Training scenario playback; original source provenance is retained in metadata.original.']
    metadata['original'] = {
        'scenario_id': scenario.env_scenario_id, 'scenario_kind': scenario.kind,
        'scenario_definition_hash': revision,
        'scenario_created_at_utc': _canonical(scenario.created_at_utc),
        'scenario_query_at_utc': _canonical(at),
        'original_snapshot_json': json.dumps(original, sort_keys=True, separators=(',', ':'), allow_nan=False),
        'original_snapshot_hash': original_hash,
        'original_valid_at_utc': _canonical(original_time), 'original_source': raw.source,
        'sampling_policy': 'Explicit training samples; original source validity is not extended.',
    }
    if scenario.kind == 'replay':
        metadata['original'].update(replay_query_at_utc=_canonical(archive_at),
            replay_source=scenario.replay_source,
            retiming_policy='Training time equals archive time plus scenario creation minus replay start.')
    output = raw.model_dump(mode='python')
    output.update(valid_at_utc=at, source='scenario', metadata=EnvironmentMetadata.model_validate(metadata),
        quality=[*raw.quality, StationQuality(station_id=f'training:{scenario.env_scenario_id}', age_s=0,
                                             flags=['scenario', 'training', 'not_a_forecast'])])
    return EnvironmentSnapshot.model_validate(output)


def sample_scenario(env_scenario_id, *, as_of_utc, from_utc, to_utc, step_min=30,
                    max_samples=MAX_SAMPLES) -> tuple[list[EnvironmentSnapshot], str]:
    """Sample every requested scenario time and both endpoints, with immutable provenance.

    The returned revision identifies the scenario definition including its creation
    anchor; the forecast resolver independently hashes the actual sampled content.
    Provider failures propagate. A finite replay ends at its declared archive end,
    including synthetic replays whose legacy sampler itself has no end check.
    """
    as_of = _utc(as_of_utc, 'Planning as-of time')
    start, end = _utc(from_utc, 'Scenario horizon start'), _utc(to_utc, 'Scenario horizon end')
    if start < as_of:
        raise refdata.InvalidReference('Scenario horizon cannot begin before planning as-of time')
    if end <= start:
        raise refdata.InvalidReference('Scenario horizon end must be after its start')
    if type(step_min) is not int or not 1 <= step_min <= MAX_STEP_MIN:
        raise refdata.InvalidReference(f'Scenario step must be an integer from 1 through {MAX_STEP_MIN} minutes')
    if type(max_samples) is not int or not 1 <= max_samples <= MAX_FORECAST_SNAPSHOTS:
        raise refdata.InvalidReference(f'Scenario sample limit must be an integer from 1 through {MAX_FORECAST_SNAPSHOTS}')
    step = timedelta(minutes=step_min)
    full_steps = (end-start) // step
    partial = (end-start) % step != timedelta(0)
    if full_steps + 1 + partial > max_samples:
        raise refdata.InvalidReference(f'Scenario forecast exceeds {max_samples} samples; shorten its horizon or increase the step')
    scenario, revision = _definition(env_scenario_id)
    created = _utc(scenario.created_at_utc, 'Scenario creation time')
    if created > as_of:
        raise refdata.InvalidReference('Environment scenario was created after planning as-of time')
    archive_start = None
    if scenario.kind == 'replay':
        archive_start = _utc(scenario.replay_start_utc, 'Replay start')
        if scenario.replay_end_utc is not None:
            archive_end = _utc(scenario.replay_end_utc, 'Replay end')
            if archive_start + (end-created) > archive_end:
                raise refdata.InvalidReference('Replay window is exhausted before the scenario horizon ends; replay never loops')
    times = [start + i*step for i in range(full_steps+1)]
    if partial:
        times.append(end)
    snapshots = []
    for at in times:
        archive_at = archive_start + (at-created) if archive_start is not None else at
        raw = environment.scenario_snapshot(env_scenario_id, at)
        snapshots.append(_training_snapshot(raw, scenario, revision, at, archive_at))
    if _definition(env_scenario_id)[1] != revision:
        raise refdata.InvalidReference('Environment scenario definition changed while it was sampled; retry with one revision')
    return snapshots, revision
