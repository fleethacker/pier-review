"""Telemetry ingest schemas (module M13): ship sensors in deployment."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Model


class TelemetryRecord(Model):
    source: Literal["ship_nmea", "load_cell", "ais"]
    t_utc: datetime
    sentence: str | None = Field(default=None, description="Raw NMEA 0183 sentence, e.g. '$WIMWV,...'.")
    line_number: int | None = Field(default=None, description="load_cell: which mooring line.")
    tension_lbf: float | None = None
    mmsi: str | None = Field(default=None, description="ais: vessel id (tugs).")
    lat: float | None = None
    lon: float | None = None


class TelemetryBatch(Model):
    records: list[TelemetryRecord]


class TelemetryAccepted(Model):
    accepted: int
    rejected: int
    errors: list[str] = Field(default_factory=list)
