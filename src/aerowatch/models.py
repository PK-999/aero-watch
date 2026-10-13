"""Shared values. Provider units are converted before reaching these models."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Bounds:
    lamin: float
    lamax: float
    lomin: float
    lomax: float

    def contains(self, latitude: float, longitude: float) -> bool:
        return self.lamin <= latitude <= self.lamax and self.lomin <= longitude <= self.lomax

    def expanded(self, buffer: float) -> "Bounds":
        return Bounds(
            max(-90, self.lamin - buffer),
            min(90, self.lamax + buffer),
            max(-180, self.lomin - buffer),
            min(180, self.lomax + buffer),
        )


@dataclass(frozen=True)
class Location:
    name: str
    bounds: Bounds


@dataclass(frozen=True)
class AircraftObservation:
    icao24: str
    callsign: str
    latitude: float
    longitude: float
    on_ground: bool | None = None
    speed_ms: float | None = None
    track_deg: float | None = None
    baro_altitude_m: float | None = None
    geo_altitude_m: float | None = None
    vertical_rate_ms: float | None = None
    squawk: str | None = None
    country: str | None = None
    registration: str | None = None
    model: str | None = None
    type_code: str | None = None


@dataclass(frozen=True)
class Prediction:
    eta_seconds: float
    boundary: str


@dataclass(frozen=True)
class AlertEvent:
    kind: Literal["incoming", "overhead", "takeoff", "departed"]
    aircraft: AircraftObservation
    prediction: Prediction | None = None


@dataclass(frozen=True)
class AircraftMetadata:
    registration: str | None = None
    model: str | None = None
    type_code: str | None = None
    operator: str | None = None
    airline: str | None = None
    route: str | None = None
    flight_number: str | None = None


@dataclass(frozen=True)
class ScanResult:
    aircraft: tuple[AircraftObservation, ...]
    provider: str | None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class Notification:
    title: str
    message: str
    subtitle: str
    url: str
