"""Straight-line local projection; turning flight paths can invalidate the ETA."""

import math

from .models import AircraftObservation, Bounds, Prediction


def compass_heading(degrees: float) -> str:
    directions = (
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    )
    return directions[int((degrees % 360 + 11.25) / 22.5) % 16]


def predict_entry(bounds: Bounds, aircraft: AircraftObservation) -> Prediction | None:
    lat, lon = aircraft.latitude, aircraft.longitude
    speed, heading = aircraft.speed_ms, aircraft.track_deg
    if bounds.contains(lat, lon) or speed is None or heading is None or speed <= 0:
        return None
    if not all(math.isfinite(v) for v in (lat, lon, speed, heading)):
        return None
    latitude_scale = math.cos(math.radians(lat))
    if abs(latitude_scale) < 1e-6:
        return None
    radians = math.radians(heading)
    north = speed * math.cos(radians) / 111139
    east = speed * math.sin(radians) / (111139 * latitude_scale)
    enter, leave, boundary = -math.inf, math.inf, ""
    for position, velocity, low, high, lower_edge, upper_edge in (
        (lat, north, bounds.lamin, bounds.lamax, "South", "North"),
        (lon, east, bounds.lomin, bounds.lomax, "West", "East"),
    ):
        if abs(velocity) < 1e-12:
            if not low <= position <= high:
                return None
            continue
        first, last = (low - position) / velocity, (high - position) / velocity
        edge = lower_edge
        if first > last:
            first, last, edge = last, first, upper_edge
        if first > enter:
            enter, boundary = first, edge
        leave = min(leave, last)
    if 0 < enter <= leave and math.isfinite(enter):
        return Prediction(enter, boundary)
    return None
