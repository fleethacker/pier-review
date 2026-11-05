"""Tension-only nonlinear line curves."""

import math


class UnsupportedMechanics(ValueError):
    """A specification the mechanics cannot represent faithfully (rejected, never approximated silently)."""


class TensionCurve:
    """Load fraction of effective MBS versus strain, piecewise linear, tension-only (ε <= 0 carries no load).

    Built from [fraction, strain] pairs starting at [0, 0]. Both columns must strictly increase and every value be
    finite; beyond the last point the final segment is extended linearly (the rule checks flag loads above MBS).
    """

    def __init__(self, points: list[tuple[float, float]]):
        pts = [(float(f), float(s)) for f, s in points]
        if len(pts) < 2:
            raise UnsupportedMechanics("curve needs at least two points")
        if not all(math.isfinite(v) for p in pts for v in p):
            raise UnsupportedMechanics("curve has non-finite values")
        if pts[0] != (0.0, 0.0):
            raise UnsupportedMechanics("curve must start at (0, 0)")
        if any(b[0] <= a[0] for a, b in zip(pts, pts[1:])):
            raise UnsupportedMechanics("load fractions must strictly increase")
        if any(b[1] <= a[1] for a, b in zip(pts, pts[1:])):
            raise UnsupportedMechanics("strain must strictly increase with load (non-monotone curve)")
        self.points = pts

    def fraction(self, strain: float) -> float:
        """Load fraction carried at `strain`; zero when slack (strain <= 0)."""
        if strain <= 0:
            return 0.0
        pts = self.points
        for (f0, s0), (f1, s1) in zip(pts, pts[1:]):
            if strain <= s1:
                return f0 + (strain - s0) / (s1 - s0) * (f1 - f0)
        (f0, s0), (f1, s1) = pts[-2], pts[-1]
        return f1 + (strain - s1) / (s1 - s0) * (f1 - f0)

    def strain(self, fraction: float) -> float:
        """Inverse of `fraction` (exact on the piecewise-linear curve)."""
        if fraction <= 0:
            return 0.0
        pts = self.points
        for (f0, s0), (f1, s1) in zip(pts, pts[1:]):
            if fraction <= f1:
                return s0 + (fraction - f0) / (f1 - f0) * (s1 - s0)
        (f0, s0), (f1, s1) = pts[-2], pts[-1]
        return s1 + (fraction - f1) / (f1 - f0) * (s1 - s0)

    def slope(self, strain: float) -> float:
        """d(fraction)/d(strain) on the active segment (zero when slack)."""
        if strain <= 0:
            return 0.0
        pts = self.points
        for (f0, s0), (f1, s1) in zip(pts, pts[1:]):
            if strain <= s1:
                return (f1 - f0) / (s1 - s0)
        (f0, s0), (f1, s1) = pts[-2], pts[-1]
        return (f1 - f0) / (s1 - s0)
