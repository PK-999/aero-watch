import json
from dataclasses import replace
from pathlib import Path

import pytest
import requests
from http_fakes import Response, Session

from aerowatch.models import AircraftObservation

AIRCRAFT = AircraftObservation(
    "abc123",
    "TEST123",
    12.95,
    77.67,
    False,
    100,
    90,
    registration="VT-LIVE",
    model="Known model",
    type_code="C25A",
)


def fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text())


def service(session, **kwargs):
    from aerowatch.metadata import MetadataService

    return MetadataService(session=session, **kwargs)


def test_live_fields_survive_sparse_registry_and_route():
    result = service(Session(Response(fixture("adsbdb_route")), Response({}), Response({}))).lookup(
        AIRCRAFT
    )
    assert result.registration == "VT-LIVE" and result.model == "Known model"
    assert result.route == "HYD → BLR" and result.flight_number == "T123"


def test_hexdb_fills_only_missing_fields_and_stops_fallback():
    session = Session(Response(fixture("adsbdb_route")), Response(fixture("hexdb_aircraft")))
    result = service(session).lookup(AIRCRAFT)
    assert result.model == "Known model" and result.operator == "Test operator"
    assert len(session.calls) == 2
    assert all(c[2]["timeout"] == (2.5, 2.5) for c in session.calls)


def test_adsbdb_aircraft_fallback():
    result = service(
        Session(Response({}), Response({}), Response(fixture("adsbdb_aircraft")))
    ).lookup(replace(AIRCRAFT, registration=None, model=None, type_code=None))
    assert result.registration == "VT-TEST" and result.type_code == "C25A"
    assert result.operator == "Test operator"


@pytest.mark.parametrize(
    "failure",
    [
        Response(status_code=503),
        Response(ValueError("bad JSON")),
        Response({"response": None}),
        requests.Timeout(),
    ],
)
def test_failed_enrichment_retains_live_fields_and_is_negative_cached(failure):
    session = Session(failure, failure, failure)
    instance = service(session)
    assert instance.lookup(AIRCRAFT).registration == "VT-LIVE"
    assert instance.lookup(AIRCRAFT).registration == "VT-LIVE"
    assert len(session.calls) == 3


def test_changed_callsign_does_not_reuse_old_route():
    instance = service(
        Session(
            Response(fixture("adsbdb_route")), Response(fixture("hexdb_aircraft")), Response({})
        )
    )
    assert instance.lookup(AIRCRAFT).route == "HYD → BLR"
    changed = instance.lookup(replace(AIRCRAFT, callsign="OTHER456"))
    assert changed.route is None and changed.registration == "VT-LIVE"


def test_route_and_aircraft_lifetimes_are_independent():
    now = [0]
    session = Session(
        Response(fixture("adsbdb_route")),
        Response(fixture("hexdb_aircraft")),
        Response({}),
        Response({}),
        Response(fixture("hexdb_aircraft")),
    )
    instance = service(session, clock=lambda: now[0])
    assert instance.lookup(AIRCRAFT).route == "HYD → BLR"
    now[0] = 299
    assert instance.lookup(AIRCRAFT).route == "HYD → BLR"
    assert len(session.calls) == 2
    now[0] = 300
    assert instance.lookup(AIRCRAFT).route is None
    assert len(session.calls) == 3
    now[0] = 3600
    assert instance.lookup(AIRCRAFT).operator == "Test operator"
    assert len(session.calls) == 5


def test_failed_lookup_retries_after_300_seconds():
    now = [0]
    session = Session(
        Response({}), Response({}), Response({}), Response({}), Response(fixture("hexdb_aircraft"))
    )
    instance = service(session, clock=lambda: now[0])
    assert instance.lookup(AIRCRAFT).operator is None
    now[0] = 299
    assert instance.lookup(AIRCRAFT).operator is None
    now[0] = 300
    assert instance.lookup(AIRCRAFT).operator == "Test operator"


def test_no_callsign_skips_route_and_cached_identity_skips_registry():
    session = Session(Response(fixture("hexdb_aircraft")))
    instance = service(session)
    result = instance.lookup(replace(AIRCRAFT, callsign=""))
    assert result.route is None and result.operator == "Test operator"
    assert instance.lookup(replace(AIRCRAFT, callsign="")).model == "Known model"
    assert len(session.calls) == 1


def test_unused_aircraft_is_evicted():
    now = [0]
    session = Session(
        Response(fixture("hexdb_aircraft")),
        Response(fixture("hexdb_aircraft")),
        Response(fixture("hexdb_aircraft")),
    )
    instance = service(session, clock=lambda: now[0])
    instance.lookup(replace(AIRCRAFT, callsign=""))
    now[0] = 3601
    instance.lookup(replace(AIRCRAFT, icao24="def456", callsign=""))
    instance.lookup(replace(AIRCRAFT, callsign=""))
    assert len(session.calls) == 3
