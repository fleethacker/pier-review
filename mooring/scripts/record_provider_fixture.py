"""Manually record one public JSON provider response in canonical form."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx

from mooring.environment.providers import canonical_fixture_bytes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("output", type=Path)
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args()
    if os.getenv("MOORING_FIXTURE_RECORD") != "1":
        parser.error("set MOORING_FIXTURE_RECORD=1 to acknowledge a live provider call")
    params = dict(item.split("=", 1) for item in args.param)
    response = httpx.get(
        args.url,
        params=params,
        timeout=10.0,
        headers={"User-Agent": "mooring-fixture-recorder/0.1", "Accept": "application/json"},
        follow_redirects=False,
    )
    response.raise_for_status()
    value = json.loads(response.content)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_fixture_bytes(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
