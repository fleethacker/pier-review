"""Regenerate the API contract from the Pydantic schemas.

Writes contract/modeling.openapi.yaml, contract/agents.openapi.yaml and contract/examples/modeling/*.json.
Run `make contract` after changing any schema or endpoint, and commit the result in the same PR.
"""

import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contract"


def render() -> dict[Path, str]:
    os.environ.setdefault("MOCK_JOB_DELAY_S", "0")
    from modeling_api.main import openapi_schema as modeling_schema
    from mooring.examples import EXAMPLES
    from mooring_agents.api.main import openapi_schema as agents_schema

    def dump(schema: dict) -> str:
        return yaml.safe_dump(schema, sort_keys=False, allow_unicode=True, width=120)

    out = {CONTRACT / "modeling.openapi.yaml": dump(modeling_schema()),
           CONTRACT / "agents.openapi.yaml": dump(agents_schema())}
    for name, body in EXAMPLES.items():
        out[CONTRACT / "examples" / "modeling" / f"{name}.json"] = json.dumps(body, indent=2) + "\n"
    return out


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for path, text in render().items():
        if check:
            if not path.exists() or path.read_text() != text:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if stale:
        print("Contract is out of date; run `make contract`:\n  " + "\n  ".join(stale))
        return 1
    print("contract up to date" if check else "contract written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
