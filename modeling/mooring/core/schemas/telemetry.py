"""Telemetry ingest schemas (module M13): ship sensors in deployment."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Model


class TelemetryRecord(Model):
    wire_omitted_defaults = {"sensor_id": None, "vessel_id": None, "calibration_rev": None, "seq": None, "units": None, "received_utc": None}

    source: Literal["ship_nmea", "load_cell", "ais"]
    t_utc: datetime
    sentence: str | None = Field(default=None, description="Raw NMEA 0183 sentence, e.g. '$WIMWV,...'.")
    line_number: int | None = Field(default=None, description="load_cell: which mooring line.")
    tension_lbf: float | None = None
    mmsi: str | None = Field(default=None, description="ais: vessel id (tugs).")
    lat: float | None = None
    lon: float | None = None
    sensor_id: str | None = Field(default=None, description="load_cell: registered sensor/channel id (required in the validating ingest).")
    vessel_id: str | None = Field(default=None, description="Vessel the sensor is installed on; must match the sensor registry.")
    calibration_rev: str | None = Field(default=None, description="Calibration revision the reading was taken under.")
    seq: int | None = Field(default=None, ge=0, description="Sender sequence number, used to detect replays and duplicates.")
    units: str | None = Field(default=None, description="load_cell: must be 'lbf'. Any other value is rejected, not converted.")
    received_utc: datetime | None = Field(default=None, description="When the service received it (set by the service; ignored on input).")


class TelemetryBatch(Model):
    records: list[TelemetryRecord]


class TelemetryRejection(Model):
    index: int
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    message: str


class TelemetryAccepted(Model):
    wire_omitted_defaults = {"rejections": []}

    accepted: int
    rejected: int
    errors: list[str] = Field(default_factory=list)
    rejections: list[TelemetryRejection] = Field(default_factory=list, description="Machine-readable reasons; rejected records never influence any result.")
