"""The coefficient register in docs/PORT_TRANSIT.md must carry every constant of the model."""

from pathlib import Path

from mooring.transit.coefficients import COEFFICIENT_TABLE

DOC = (Path(__file__).resolve().parents[2] / "docs" / "PORT_TRANSIT.md").read_text()


def test_every_coefficient_is_documented_with_source_and_status():
    for c in COEFFICIENT_TABLE:
        row = f"| {c.name} | {c.value} | {c.source} | {c.status} |"
        assert row in DOC, c.name
    assert all(c.source and c.status for c in COEFFICIENT_TABLE)
