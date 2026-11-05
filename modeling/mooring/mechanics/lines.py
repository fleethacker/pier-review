"""Installed lines: rest length, pretension/slack initialization and multi-part arrangements."""

from dataclasses import dataclass

from .curves import TensionCurve, UnsupportedMechanics

SUPPORTED_PARTS = (1, 2, 3)
DEFAULT_PRETENSION_FRACTION = 0.02  # legacy default: 2% of effective MBS when no pretension/slack/length is given


@dataclass
class LineModel:
    """One installed line (all parts together).

    Parts are modeled as identical parallel strands sharing the same strain: tension = parts x single-strand
    tension. Valid only for equal-length strands without friction at a chock; reeving that couples strands (e.g.
    a bight through a fitting) is not represented and is the caller's responsibility to flag.
    """

    curve: TensionCurve
    mbs_eff_lbf: float      # parts x MBS x wet/dry factor
    rest_length_ft: float   # unstretched length installed
    parts: int = 1

    def strain(self, length_ft: float) -> float:
        return (length_ft - self.rest_length_ft) / self.rest_length_ft

    def tension(self, length_ft: float) -> float:
        """Tension (lbf); exactly zero when slack."""
        return self.mbs_eff_lbf * self.curve.fraction(self.strain(length_ft))

    def stiffness(self, length_ft: float) -> float:
        """d(tension)/d(length) (lbf/ft); zero when slack."""
        return self.mbs_eff_lbf * self.curve.slope(self.strain(length_ft)) / self.rest_length_ft

    def taut(self, length_ft: float) -> bool:
        return length_ft > self.rest_length_ft


def init_line_model(curve_points, mbs_lbf: float, *, parts: int, wet_factor: float, initial_length_ft: float,
                    pretension_lbf: float | None = None, slack_ft: float | None = None,
                    paid_out_unstretched_length_ft: float | None = None) -> tuple[LineModel, str]:
    """Create a LineModel from the installed geometry. Returns (model, how the rest length was determined).

    Precedence is explicit, never merged: paid-out length, else positive slack, else pretension, else the legacy
    default pretension. Contradictory inputs raise.
    """
    if parts not in SUPPORTED_PARTS:
        raise UnsupportedMechanics(f"{parts} parts is not a supported arrangement")
    if not initial_length_ft > 0:
        raise UnsupportedMechanics("installed line length must be positive")
    if paid_out_unstretched_length_ft is not None and (slack_ft or pretension_lbf):
        raise UnsupportedMechanics("paid-out length cannot be combined with slack or pretension")
    if pretension_lbf and slack_ft:
        raise UnsupportedMechanics("pretension and slack contradict each other")
    curve = TensionCurve(curve_points)
    mbs_eff = mbs_lbf * parts * wet_factor
    if paid_out_unstretched_length_ft is not None:
        l0, how = paid_out_unstretched_length_ft, "paid-out unstretched length"
    elif slack_ft:
        l0, how = initial_length_ft + slack_ft, "slack"
    else:
        p = pretension_lbf if pretension_lbf is not None else DEFAULT_PRETENSION_FRACTION * mbs_eff
        how = "pretension" if pretension_lbf is not None else "default 2% pretension"
        l0 = initial_length_ft / (1 + curve.strain(p / mbs_eff))
    return LineModel(curve=curve, mbs_eff_lbf=mbs_eff, rest_length_ft=l0, parts=parts), how
