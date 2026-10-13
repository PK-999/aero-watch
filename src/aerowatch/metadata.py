"""Optional registry and callsign lookups with separate positive/negative caches."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from urllib.parse import quote

import requests

from .models import AircraftMetadata, AircraftObservation
from .providers import ProviderError, clean_text, request_json

LOG = logging.getLogger(__name__)


@dataclass
class _CacheEntry:
    value: AircraftMetadata
    expires: float
    used: float


def _object(value) -> dict:
    return value if isinstance(value, dict) else {}


def _merge(primary: AircraftMetadata, fallback: AircraftMetadata) -> AircraftMetadata:
    return AircraftMetadata(
        **{
            field.name: getattr(primary, field.name) or getattr(fallback, field.name)
            for field in fields(AircraftMetadata)
        }
    )


def _complete(metadata: AircraftMetadata) -> bool:
    return all((metadata.registration, metadata.model, metadata.type_code, metadata.operator))


class MetadataService:
    def __init__(self, session=None, clock: Callable[[], float] = time.monotonic):
        self.session = session if session is not None else requests.Session()
        self.clock = clock
        self._aircraft: dict[str, _CacheEntry] = {}
        self._routes: dict[tuple[str, str], _CacheEntry] = {}

    def _get(self, url: str) -> dict:
        try:
            return request_json(self.session, url, timeout=(2.5, 2.5))
        except ProviderError as error:
            LOG.debug("Metadata unavailable: %s", error)
            return {}

    def _route(self, icao: str, callsign: str, now: float) -> AircraftMetadata:
        if not callsign:
            return AircraftMetadata()
        key = (icao, callsign)
        entry = self._routes.get(key)
        if entry and now < entry.expires:
            entry.used = now
            return entry.value
        payload = self._get(f"https://api.adsbdb.com/v0/callsign/{quote(callsign, safe='')}")
        route = _object(_object(payload.get("response")).get("flightroute"))
        origin, destination = _object(route.get("origin")), _object(route.get("destination"))
        departure = clean_text(origin.get("iata_code")) or clean_text(origin.get("icao_code"))
        arrival = clean_text(destination.get("iata_code")) or clean_text(
            destination.get("icao_code")
        )
        result = AircraftMetadata(
            route=f"{departure} → {arrival}" if departure and arrival else None,
            airline=clean_text(_object(route.get("airline")).get("name")),
            flight_number=clean_text(route.get("callsign_iata")),
        )
        self._routes[key] = _CacheEntry(result, now + 300, now)
        return result

    def _registry(self, icao: str, seed: AircraftMetadata) -> AircraftMetadata:
        raw = self._get(f"https://hexdb.io/api/v1/aircraft/{quote(icao, safe='')}")
        manufacturer, model = clean_text(raw.get("Manufacturer")), clean_text(raw.get("Type"))
        result = _merge(
            seed,
            AircraftMetadata(
                registration=clean_text(raw.get("Registration")),
                model=" ".join(v for v in (manufacturer, model) if v) if model else None,
                type_code=clean_text(raw.get("ICAOTypeCode")),
                operator=clean_text(raw.get("RegisteredOwners")),
            ),
        )
        if _complete(result):
            return result
        payload = self._get(f"https://api.adsbdb.com/v0/aircraft/{quote(icao, safe='')}")
        raw = _object(_object(payload.get("response")).get("aircraft"))
        manufacturer, model = clean_text(raw.get("manufacturer")), clean_text(raw.get("type"))
        return _merge(
            result,
            AircraftMetadata(
                registration=clean_text(raw.get("registration")),
                model=" ".join(v for v in (manufacturer, model) if v) if model else None,
                type_code=clean_text(raw.get("icao_type")),
                operator=clean_text(raw.get("registered_owner")),
            ),
        )

    def lookup(self, aircraft: AircraftObservation) -> AircraftMetadata:
        now = self.clock()
        self._aircraft = {
            key: entry for key, entry in self._aircraft.items() if now - entry.used < 3600
        }
        self._routes = {key: entry for key, entry in self._routes.items() if now < entry.expires}
        icao, callsign = aircraft.icao24.lower().strip(), aircraft.callsign.strip().upper()
        route = self._route(icao, callsign, now)
        live = AircraftMetadata(
            registration=aircraft.registration, model=aircraft.model, type_code=aircraft.type_code
        )
        entry = self._aircraft.get(icao)
        if entry and now < entry.expires:
            entry.used = now
            identity = _merge(live, entry.value)
            entry.value = identity
        else:
            # Preserve known fields when refreshing returns a sparse/error response.
            identity = self._registry(icao, _merge(live, entry.value) if entry else live)
            self._aircraft[icao] = _CacheEntry(
                identity, now + (3600 if _complete(identity) else 300), now
            )
        return replace(
            identity, route=route.route, airline=route.airline, flight_number=route.flight_number
        )
