"""The stored S7 example must stay within a small tolerance of what the engine computes now (platform float noise allowed)."""
import math

from mooring.prediction_examples import build, generate


def _close(a, b, path=""):
    if isinstance(a, dict):
        assert a.keys() == b.keys(), path
        for k in a:
            _close(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{path}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        if path.endswith((".lat", ".lon")):
            tol = 1e-6                     # ~0.1 m
        else:
            tol = max(1e-3, 1e-3 * abs(b))  # relative 0.1 % (ft, kt, deg, s)
        assert math.isclose(a, b, abs_tol=tol), f"{path}: stored {b} vs engine {a}"
    else:
        assert a == b, f"{path}: stored {b!r} vs engine {a!r}"


def test_s7_example_matches_engine():
    stored, fresh = build(), generate()
    _close(fresh["predict_trajectory_request"], stored["predict_trajectory_request"], "request")
    _close(fresh["predict_trajectory_response"], stored["predict_trajectory_response"], "response")
