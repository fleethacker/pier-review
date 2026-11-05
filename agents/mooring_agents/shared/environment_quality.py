"""Interpret declared component provenance; no physical calculations or source substitution."""
from mooring.core.schemas import EnvironmentSnapshot


def component_issues(snapshot: EnvironmentSnapshot) -> list[tuple[str, str, str, str]]:
    """Return source, issue, severity and plain description; INFO preserves explicit limitations."""
    metadata = snapshot.metadata
    issues = []
    aware = snapshot.valid_at_utc.tzinfo is not None and snapshot.valid_at_utc.utcoffset() is not None
    for item in metadata.components if metadata else []:
        source = f"{item.component}: {item.source}"
        if item.quality in ('poor', 'suspect'):
            issues.append((source, 'flagged', 'RED' if item.quality == 'poor' else 'AMBER',
                           f"Provider marks the {item.component} component {item.quality}; verify before use."))
        elif item.quality == 'unknown':
            issues.append((source, 'flagged', 'INFO',
                           f"Quality of the {item.component} component is not established."))
        if not aware:
            issues.append((source, 'out_of_range', 'RED',
                           'Component provenance cannot be checked against a snapshot without a timezone.'))
        elif ((item.valid_from_utc and snapshot.valid_at_utc < item.valid_from_utc)
                or (item.valid_to_utc and snapshot.valid_at_utc > item.valid_to_utc)):
            issues.append((source, 'out_of_range', 'RED',
                           f"A supplied {item.component} sample is outside its declared validity interval."))
        if item.basis == 'prediction' and item.issued_at_utc is None:
            issues.append((source, 'flagged', 'INFO',
                           f"The {item.component} provider issue time is unknown; retrieval is only an availability record, not proof of freshness."))
        for limitation in item.limitations:
            issues.append((source, 'flagged', 'INFO', f"{item.component} source limitation: {limitation}"))
    return issues
