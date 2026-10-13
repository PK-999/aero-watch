"""Public telemetry adapters, normalization, and ordered provider failover."""

import logging
import math
import os
import re
import time
from collections.abc import Callable
from datetime import UTC
from email.utils import parsedate_to_datetime

import requests

from .config import AppConfig
from .models import AircraftObservation, Bounds, ScanResult

LOG = logging.getLogger(__name__)
USER_AGENT = "AeroWatch/2.0 (+https://github.com/PK-999/aero-watch)"


class ProviderError(Exception):
    """Safe diagnostics: never embed response bodies, URLs, tokens, or secrets."""

    def __init__(self, reason: str, status: int | None = None, retry_after: str | None = None):
        super().__init__(reason)
        self.status = status
        self.retry_after = retry_after


def request_json(session, url: str, *, timeout=(3.5, 3.5), headers=None, **kwargs) -> dict:
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    try:
        response = session.get(url, timeout=timeout, headers=request_headers, **kwargs)
        if response.status_code != 200:
            raise ProviderError(
                f"HTTP {response.status_code}",
                response.status_code,
                response.headers.get("Retry-After"),
            )
        payload = response.json()
    except requests.RequestException as error:
        raise ProviderError(f"request failed ({type(error).__name__})") from error
    except ValueError as error:
        raise ProviderError("invalid JSON response") from error
    if not isinstance(payload, dict):
        raise ProviderError("expected a JSON object")
    return payload


def finite_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def clean_text(value) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _identity(value) -> str | None:
    result = clean_text(value)
    return result.lower() if result and re.fullmatch(r"[0-9a-fA-F]{6}", result) else None


def _readsb(raw) -> AircraftObservation | None:
    if not isinstance(raw, dict):
        return None
    identity = _identity(raw.get("hex"))
    lat, lon = finite_number(raw.get("lat")), finite_number(raw.get("lon"))
    if not identity or lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if "seen_pos" in raw:
        age = finite_number(raw["seen_pos"])
        if age is None or not 0 <= age <= 60:
            return None
    baro = finite_number(raw.get("alt_baro"))
    ground = True if raw.get("alt_baro") == "ground" else False if baro is not None else None
    speed = finite_number(raw.get("gs"))
    heading = finite_number(raw.get("track"))
    geom = finite_number(raw.get("alt_geom"))
    rate = finite_number(raw.get("baro_rate"))
    return AircraftObservation(
        identity,
        clean_text(raw.get("flight")) or "",
        lat,
        lon,
        on_ground=ground,
        speed_ms=speed * 0.514444 if speed is not None and speed >= 0 else None,
        track_deg=heading % 360 if heading is not None else None,
        baro_altitude_m=0 if ground else baro * 0.3048 if baro is not None else None,
        geo_altitude_m=geom * 0.3048 if geom is not None else None,
        vertical_rate_ms=rate * 0.00508 if rate is not None else None,
        squawk=clean_text(raw.get("squawk")),
        registration=clean_text(raw.get("r")),
        model=clean_text(raw.get("desc")),
        type_code=clean_text(raw.get("t")),
    )


def _opensky(raw, timestamp: float) -> AircraftObservation | None:
    if not isinstance(raw, list) or len(raw) < 8:
        return None
    identity, lat, lon = _identity(raw[0]), finite_number(raw[6]), finite_number(raw[5])
    if not identity or lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    position_time = finite_number(raw[3])
    if position_time is not None and not 0 <= timestamp - position_time <= 60:
        return None

    def value(index):
        return raw[index] if len(raw) > index else None

    speed, track = finite_number(value(9)), finite_number(value(10))
    return AircraftObservation(
        identity,
        clean_text(raw[1]) or "",
        lat,
        lon,
        on_ground=value(8) if isinstance(value(8), bool) else None,
        speed_ms=speed if speed is not None and speed >= 0 else None,
        track_deg=track % 360 if track is not None else None,
        baro_altitude_m=finite_number(raw[7]),
        geo_altitude_m=finite_number(value(13)),
        vertical_rate_ms=finite_number(value(11)),
        squawk=clean_text(value(14)),
        country=clean_text(raw[2]),
    )


class TelemetryService:
    def __init__(
        self,
        config: AppConfig,
        session=None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ):
        self.config = config
        self.session = session if session is not None else requests.Session()
        self.clock, self.wall_clock = clock, wall_clock
        self._cooldown: dict[str, float] = {}
        self._token: str | None = None
        self._token_expires = 0.0

    def _authorization(self) -> dict[str, str]:
        client = os.environ.get("OPENSKY_CLIENT_ID")
        secret = os.environ.get("OPENSKY_CLIENT_SECRET")
        if not client or not secret:
            return {}
        if self._token and self.clock() < self._token_expires:
            return {"Authorization": f"Bearer {self._token}"}
        try:
            response = self.session.post(
                self.config.opensky.auth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client,
                    "client_secret": secret,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=(3.5, 3.5),
            )
            if response.status_code != 200:
                raise ProviderError(
                    f"authentication HTTP {response.status_code}",
                    response.status_code,
                    response.headers.get("Retry-After"),
                )
            payload = response.json()
            if not isinstance(payload, dict):
                raise ProviderError("invalid authentication response")
            token = clean_text(payload.get("access_token"))
            lifetime = finite_number(payload.get("expires_in", 1800))
            if not token or lifetime is None or lifetime <= 0:
                raise ProviderError("invalid authentication response")
            self._token = token
            self._token_expires = self.clock() + max(
                0, lifetime - self.config.opensky.token_buffer_seconds
            )
            return {"Authorization": f"Bearer {token}"}
        except requests.RequestException as error:
            raise ProviderError(f"authentication failed ({type(error).__name__})") from error
        except ValueError as error:
            raise ProviderError("invalid authentication JSON") from error

    def _retry_delay(self, header: str | None) -> float:
        try:
            delay = float(header)
            if math.isfinite(delay) and delay >= 0:
                return delay
        except (ValueError, TypeError):
            pass
        try:
            date = parsedate_to_datetime(header)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            return max(0, date.timestamp() - self.wall_clock())
        except (ValueError, TypeError, OverflowError):
            return 60

    def fetch(self, bounds: Bounds) -> ScanResult:
        lat, lon = (bounds.lamin + bounds.lamax) / 2, (bounds.lomin + bounds.lomax) / 2
        # Local diagonal estimate; longitude scale is largest at the nearest-to-equator edge.
        nearest_lat = (
            0 if bounds.lamin <= 0 <= bounds.lamax else min(abs(bounds.lamin), abs(bounds.lamax))
        )
        radius = math.ceil(
            math.hypot(
                (bounds.lamax - bounds.lamin) * 30,
                (bounds.lomax - bounds.lomin) * 30 * math.cos(math.radians(nearest_lat)),
            )
            + 5
        )
        urls = {
            "adsb.lol": f"https://api.adsb.lol/v2/point/{lat:.4f}/{lon:.4f}/{radius}",
            "adsb.fi": f"https://opendata.adsb.fi/api/v3/lat/{lat:.4f}/lon/{lon:.4f}/dist/{radius}",
            "opensky": f"{self.config.opensky.base_url}/states/all",
        }
        errors = []
        for provider, url in urls.items():
            try:
                if self.clock() < self._cooldown.get(provider, 0):
                    raise ProviderError("rate-limit cooldown")
                if provider != "opensky" and radius > 250:
                    raise ProviderError("zone exceeds 250 NM radius limit")
                kwargs = {}
                if provider == "opensky":
                    kwargs = {"headers": self._authorization(), "params": vars(bounds)}
                payload = request_json(self.session, url, **kwargs)
                key = "states" if provider == "opensky" else "ac"
                if key not in payload:
                    raise ProviderError(f"missing {key} field")
                records = payload[key]
                if provider == "opensky" and records is None:
                    records = []
                if not isinstance(records, list):
                    raise ProviderError(f"invalid {key} field")
                timestamp = finite_number(payload.get("time"))
                if timestamp is None:
                    timestamp = self.wall_clock()
                aircraft = {}
                for record in records:
                    observation = (
                        _opensky(record, timestamp) if provider == "opensky" else _readsb(record)
                    )
                    if observation and bounds.contains(observation.latitude, observation.longitude):
                        aircraft.setdefault(observation.icao24, observation)
                return ScanResult(tuple(aircraft.values()), provider, tuple(errors))
            except ProviderError as error:
                if error.status == 429:
                    self._cooldown[provider] = self.clock() + self._retry_delay(error.retry_after)
                if provider == "opensky" and error.status == 401:
                    self._token = None
                    self._token_expires = 0
                reason = f"{provider}: {error}"
                errors.append(reason)
                LOG.warning("%s", reason)
        return ScanResult((), None, tuple(errors))
