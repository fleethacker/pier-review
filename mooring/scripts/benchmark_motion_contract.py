"""Measure RM0 schema overhead only; never claim dynamics or session throughput.

Run after make contract:
  uv run --all-packages python scripts/benchmark_motion_contract.py --output docs/benchmarks/rm0-frame.json
"""

import argparse
import json
import os
import platform
import statistics
import subprocess
import time
from pathlib import Path

from mooring.core.schemas import SimFrame

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'contract' / 'examples' / 'modeling'


def measure(operation, iterations):
    for _ in range(20):
        operation()
    durations_us = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        operation()
        durations_us.append((time.perf_counter_ns() - start) / 1000)
    durations_us.sort()
    return {'p50_us': round(statistics.median(durations_us), 3),
            'p95_us': round(durations_us[(95 * iterations + 99) // 100 - 1], 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations', type=int, default=2000)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.iterations < 100:
        parser.error('--iterations must be at least 100')
    frame = json.loads((EXAMPLES / 'sim_frame.json').read_text())
    parsed = SimFrame.model_validate(frame)
    cpu = platform.processor() or 'not reported'
    if platform.system() == 'Darwin':
        result = subprocess.run(['/usr/sbin/sysctl', '-n', 'machdep.cpu.brand_string'],
                                text=True, capture_output=True, check=False)
        if result.returncode == 0:
            cpu = result.stdout.strip()
    output = {
        'scope': 'RM0 rich-frame schema validation and serialization only; no physics integration',
        'hardware': {'cpu': cpu, 'logical_cpus': os.cpu_count(), 'machine': platform.machine(),
                     'platform': platform.platform(), 'python': platform.python_version()},
        'iterations': args.iterations,
        'warmup_iterations': 20,
        'fixture': 'contract/examples/modeling/sim_frame.json',
        'validation': measure(lambda: SimFrame.model_validate(frame), args.iterations),
        'serialization': measure(parsed.model_dump_json, args.iterations),
        'compact_frame_bytes': len(parsed.model_dump_json().encode()),
        'published_file_bytes': {name: (EXAMPLES / name).stat().st_size for name in
                                 ['sim_scene.json', 'sim_frame.json', 'sim_recording_60s.json']},
        'supported_integration_step_s': None,
        'qualified_concurrent_sessions': None,
        'limitation': 'A serializer benchmark does not establish physics-step timing or real-time capacity.',
    }
    text = json.dumps(output, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
