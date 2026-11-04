"""NMEA 0183 decoding (S20a). Declared support, exactly:

* Transport: one sentence per record, text starting with '$', optional trailing CR/LF, at most 82 characters, with the
  two-hex-digit checksum after '*' required and verified (XOR of the characters between '$' and '*').
* Sentences: `MWV` (wind speed and angle; reference R relative/apparent or T true; units N knots, M m/s, K km/h; status A) and
  `HDT` (true heading). Talker id is any two letters. Nothing else is decoded: no NMEA 2000, no AIS, no proprietary
  sentences. Unsupported or malformed input is rejected with a code; it is never guessed at.

Reference: NMEA 0183 sentence structure as commonly published (field order of MWV and HDT). The standard itself is not
kept in this repository; field order here should be checked against the edition in hand before live use.
"""

import math
from dataclasses import dataclass

MAX_LEN = 82
UNIT_TO_KT = {"N": 1.0, "M": 1.0 / 0.514444, "K": 1.0 / 1.852}


class NmeaError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Wind:
    reference: str        # 'relative' (apparent, from the bow) or 'true' (from true north)
    angle_from_deg: float
    speed_kt: float


@dataclass(frozen=True)
class Heading:
    true_deg: float


def checksum(body: str) -> str:
    x = 0
    for ch in body:
        x ^= ord(ch)
    return f"{x:02X}"


def decode(sentence: str) -> Wind | Heading:
    s = sentence.rstrip("\r\n")
    if len(s) > MAX_LEN:
        raise NmeaError("SENTENCE_TOO_LONG", f"{len(s)} characters; the limit is {MAX_LEN}")
    if not s.startswith("$"):
        raise NmeaError("BAD_FRAMING", "sentence must start with '$' (encapsulated '!' sentences are not supported)")
    if "*" not in s:
        raise NmeaError("MISSING_CHECKSUM", "checksum '*hh' is required")
    body, _, tail = s[1:].partition("*")
    if len(tail) != 2 or any(c not in "0123456789abcdefABCDEF" for c in tail):
        raise NmeaError("BAD_CHECKSUM_FORMAT", "checksum must be two hex digits")
    if checksum(body).upper() != tail.upper():
        raise NmeaError("CHECKSUM_MISMATCH", f"expected {checksum(body)}, got {tail.upper()}")
    f = body.split(",")
    head = f[0]
    if len(head) != 5 or not head.isalpha():
        raise NmeaError("UNSUPPORTED_SENTENCE", f"unrecognized address field {head!r}")
    kind = head[2:]
    if kind == "MWV":
        if len(f) < 6:
            raise NmeaError("BAD_FIELD_COUNT", "MWV needs angle, reference, speed, units, status")
        try:
            angle, speed = float(f[1]), float(f[3])
        except ValueError:
            raise NmeaError("BAD_NUMBER", "MWV angle or speed is not numeric") from None
        if f[5] != "A":
            raise NmeaError("DATA_NOT_VALID", f"MWV status {f[5]!r}; only 'A' (valid) is accepted")
        if f[2] not in ("R", "T"):
            raise NmeaError("BAD_REFERENCE", f"MWV reference {f[2]!r} must be R or T")
        if f[4] not in UNIT_TO_KT:
            raise NmeaError("BAD_UNITS", f"MWV units {f[4]!r} must be N, M or K")
        if not (0 <= angle < 360) or not math.isfinite(speed) or speed < 0 or speed > 200:
            raise NmeaError("OUT_OF_RANGE", "MWV angle must be in [0, 360) and speed in [0, 200] in the stated units")
        return Wind("relative" if f[2] == "R" else "true", angle, speed * UNIT_TO_KT[f[4]])
    if kind == "HDT":
        if len(f) < 3 or f[2] != "T":
            raise NmeaError("BAD_FIELD_COUNT", "HDT needs heading and the 'T' marker")
        try:
            h = float(f[1])
        except ValueError:
            raise NmeaError("BAD_NUMBER", "HDT heading is not numeric") from None
        if not 0 <= h < 360:
            raise NmeaError("OUT_OF_RANGE", "HDT heading must be in [0, 360)")
        return Heading(h)
    raise NmeaError("UNSUPPORTED_SENTENCE", f"sentence type {kind!r} is not supported (MWV and HDT only)")


def true_wind(apparent: Wind, heading_true_deg: float, sog_kt: float, cog_true_deg: float) -> Wind:
    """Apparent-to-true wind by vector subtraction, with explicit frames.

    Apparent wind comes FROM `apparent.angle_from_deg` relative to the bow (clockwise, 0 = bow) at `speed`. Convert to the
    true-north frame using the heading, express the wind as a velocity vector (direction it blows TOWARD), and subtract the
    vessel's velocity over ground (course over ground, speed over ground). Heading, SOG and COG must be time-synchronized
    with the apparent reading by the caller; this function has no way to check that."""
    if apparent.reference != "relative":
        raise NmeaError("NOT_APPARENT", "true_wind needs a relative (apparent) reading")
    from_true = math.radians((heading_true_deg + apparent.angle_from_deg) % 360)
    toward = from_true + math.pi
    # components in (east, north): bearing b -> (sin b, cos b)
    wa = (apparent.speed_kt * math.sin(toward), apparent.speed_kt * math.cos(toward))
    vv = (sog_kt * math.sin(math.radians(cog_true_deg)), sog_kt * math.cos(math.radians(cog_true_deg)))
    wt = (wa[0] + vv[0], wa[1] + vv[1])            # apparent = true - vessel velocity  =>  true = apparent + vessel velocity
    speed = math.hypot(*wt)
    toward_true = math.degrees(math.atan2(wt[0], wt[1])) % 360
    return Wind("true", round((toward_true + 180.0) % 360.0, 9) % 360.0, speed)
