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


def _motion_example_json(name: str, body: dict) -> str:
    if name != "sim_recording_60s":
        return json.dumps(body, indent=2) + "\n"
    # One complete frame per line keeps the replay compact and preserves useful
    # diffs; sim_frame.json remains the readable, fully expanded reference.
    fields = []
    for key, value in body.items():
        if key == "frames":
            frames = ",\n".join("    " + json.dumps(frame, separators=(",", ":")) for frame in value)
            fields.append('  "frames": [\n' + frames + "\n  ]")
        else:
            fields.append(json.dumps({key: value}, indent=2)[2:-2])
    return "{\n" + ",\n".join(fields) + "\n}\n"


def render() -> dict[Path, str]:
    os.environ.setdefault("MOCK_JOB_DELAY_S", "0")
    from modeling_api.main import openapi_schema as modeling_schema
    from mooring.examples import EXAMPLES
    from mooring.environment.forecast_contract_examples import compose_partial_response_example
    from mooring.environment.wave_contract_examples import wave_compose_partial_response_example
    from mooring.motion_examples import MOTION_EXAMPLES
    from mooring.prediction_examples import PREDICTION_EXAMPLES
    from mooring.demo_cases import docking_cases
    from mooring.data_simulation.examples import examples as forecast_examples
    from mooring_agents.api.main import openapi_schema as agents_schema

    def dump(schema: dict) -> str:
        return yaml.safe_dump(schema, sort_keys=False, allow_unicode=True, width=120)

    out = {CONTRACT / "modeling.openapi.yaml": dump(modeling_schema()),
           CONTRACT / "agents.openapi.yaml": dump(agents_schema())}
    for name, body in EXAMPLES.items():
        out[CONTRACT / "examples" / "modeling" / f"{name}.json"] = json.dumps(body, indent=2) + "\n"
    out[CONTRACT / "examples" / "modeling" / "env_forecast_compose_partial.json"] = (
        json.dumps(compose_partial_response_example(), indent=2) + "\n"
    )
    out[CONTRACT / "examples" / "modeling" / "env_waves_compose_partial.json"] = (
        json.dumps(wave_compose_partial_response_example(), indent=2) + "\n"
    )
    for name, body in MOTION_EXAMPLES.items():
        out[CONTRACT / "examples" / "modeling" / f"{name}.json"] = _motion_example_json(name, body)
    for name, body in PREDICTION_EXAMPLES.items():
        out[CONTRACT / "examples" / "modeling" / f"{name}.json"] = json.dumps(body, indent=2) + "\n"
    for case in docking_cases():
        out[CONTRACT / "examples" / "modeling" / f"demo_{case.case_id}.json"] = case.model_dump_json(indent=2) + "\n"
    for name, body in forecast_examples().items():
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
