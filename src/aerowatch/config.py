"""Validated configuration with portable defaults and explicit overrides."""

import json
import math
from dataclasses import dataclass, fields
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from .models import Bounds, Location


class ConfigError(ValueError):
    """An actionable error in user configuration."""


@dataclass(frozen=True)
class TrackingSettings:
    poll_interval: float = 10
    token_buffer_seconds: float = 60
    ignore_ground_aircraft: bool = False
    predictive_warning: bool = True
    warning_lead_time_seconds: float = 60
    surveillance_buffer_degrees: float = 0.15
    notify_on_entry: bool = True
    notify_on_departure: bool = True


@dataclass(frozen=True)
class NotificationSettings:
    enabled: bool = True
    sound: bool = True
    timeout: float = 30
    auto_open_url: bool = False


@dataclass(frozen=True)
class OpenSkySettings:
    base_url: str = "https://opensky-network.org/api"
    auth_url: str = (
        "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
    )
    token_buffer_seconds: float = 60


@dataclass(frozen=True)
class AppConfig:
    locations: dict[str, Location]
    tracking: TrackingSettings
    notifications: NotificationSettings
    opensky: OpenSkySettings
    radar_base_url: str


def _number(value, label: str, *, minimum=None, positive=False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label} must be a finite number")
    try:
        number = float(value)
    except OverflowError as error:
        raise ConfigError(f"{label} must be a finite number") from error
    if not math.isfinite(number):
        raise ConfigError(f"{label} must be a finite number")
    if (positive and value <= 0) or (minimum is not None and value < minimum):
        raise ConfigError(f"{label} must be {'positive' if positive else f'at least {minimum}'}")
    return float(value)


def _object(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a JSON object")
    return value


def _url(value, label: str) -> str:
    if (
        not isinstance(value, str)
        or urlparse(value).scheme not in ("http", "https")
        or not urlparse(value).netloc
    ):
        raise ConfigError(f"{label} must be an HTTP(S) URL")
    return value.rstrip("/")


def _settings(cls, value: dict):
    defaults = cls()
    result = {}
    for field in fields(defaults):
        default = getattr(defaults, field.name)
        selected = value.get(field.name, default)
        if isinstance(default, bool):
            if not isinstance(selected, bool):
                raise ConfigError(f"{field.name} must be true or false")
        else:
            selected = _number(
                selected,
                field.name,
                minimum=0,
                positive=field.name in ("poll_interval", "warning_lead_time_seconds", "timeout"),
            )
        result[field.name] = selected
    return cls(**result)


def load_config(config_dir: Path | None = None) -> AppConfig:
    if config_dir is None and Path("config").is_dir():
        config_dir = Path("config")
    source = Path(config_dir) if config_dir is not None else files("aerowatch").joinpath("data")

    def read(name):
        try:
            return _object(json.loads(source.joinpath(name).read_text(encoding="utf-8")), name)
        except (OSError, ValueError) as error:
            if isinstance(error, ConfigError):
                raise
            raise ConfigError(
                f"Cannot read {source}/{name}: check the file and JSON syntax"
            ) from error

    settings = read("settings.json")
    locations = {}
    for key, raw in read("locations.json").items():
        raw = _object(raw, key)
        try:
            lat1, lat2, lon1, lon2 = (
                _number(raw[k], f"{key}.{k}") for k in ("lamin", "lamax", "lomin", "lomax")
            )
        except KeyError as error:
            raise ConfigError(f"{key} is missing {error.args[0]}") from error
        if not (
            -90 <= lat1 <= 90 and -90 <= lat2 <= 90 and -180 <= lon1 <= 180 and -180 <= lon2 <= 180
        ):
            raise ConfigError(f"{key}: latitude must be within ±90 and longitude within ±180")
        bounds = Bounds(min(lat1, lat2), max(lat1, lat2), min(lon1, lon2), max(lon1, lon2))
        if lat1 == lat2 or lon1 == lon2 or abs(lon1 - lon2) > 180:
            raise ConfigError(
                f"{key}: bounds must enclose an area without crossing the antimeridian"
            )
        name = raw.get("name", key)
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{key}.name must be a nonempty string")
        locations[key] = Location(name, bounds)
    if not locations:
        raise ConfigError("locations.json must contain at least one location")
    for required in ("tracking", "notifications"):
        if required not in settings:
            raise ConfigError(f"settings.json is missing {required}")
    tracking = _settings(TrackingSettings, _object(settings["tracking"], "tracking"))
    notifications = _settings(
        NotificationSettings, _object(settings["notifications"], "notifications")
    )
    opensky = _object(settings.get("opensky", {}), "opensky")
    defaults = OpenSkySettings()
    radar = _object(settings.get("adsb_exchange", {}), "adsb_exchange")
    return AppConfig(
        locations,
        tracking,
        notifications,
        OpenSkySettings(
            _url(opensky.get("base_url", defaults.base_url), "opensky.base_url"),
            _url(opensky.get("auth_url", defaults.auth_url), "opensky.auth_url"),
            tracking.token_buffer_seconds,
        ),
        _url(radar.get("base_url", "https://globe.adsbexchange.com"), "adsb_exchange.base_url"),
    )
