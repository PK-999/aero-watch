import json
from pathlib import Path

import pytest
import requests
from http_fakes import Response, Session

from aerowatch.config import load_config
from aerowatch.models import Bounds

BOX = Bounds(12.76, 13.15, 77.47, 77.87)


def fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text())


def service(session, **kwargs):
    from aerowatch.providers import TelemetryService

    return TelemetryService(load_config(), session=session, **kwargs)


@pytest.mark.parametrize(
    "name,failures,provider",
    [
        ("adsb_lol", 0, "adsb.lol"),
        ("adsb_fi", 1, "adsb.fi"),
        ("opensky", 2, "opensky"),
    ],
)
def test_provider_normalization(name, failures, provider):
    session = Session(
        *[Response(status_code=503) for _ in range(failures)], Response(fixture(name))
    )
    result = service(session).fetch(BOX)
    assert result.provider == provider
    aircraft = result.aircraft[0]
    assert aircraft.speed_ms == pytest.approx(51.4444)
    assert aircraft.baro_altitude_m == pytest.approx(304.8)
    assert aircraft.vertical_rate_ms == pytest.approx(3.048)
    assert aircraft.callsign == "TEST123" and aircraft.on_ground is False
    assert session.calls[-1][2]["timeout"] == (3.5, 3.5)
    assert "AeroWatch" in session.calls[-1][2]["headers"]["User-Agent"]
    if provider == "adsb.fi":
        assert "/api/v3/lat/" in session.calls[-1][1]


def test_unknown_motion_and_ground_are_not_fabricated():
    result = service(
        Session(Response({"ac": [{"hex": "abc123", "lat": 12.95, "lon": 77.67}]}))
    ).fetch(BOX)
    aircraft = result.aircraft[0]
    assert aircraft.speed_ms is None and aircraft.track_deg is None and aircraft.on_ground is None


def test_bad_and_duplicate_records_do_not_hide_valid_neighbors():
    valid = fixture("adsb_lol")["ac"][0]
    payload = {
        "ac": [
            None,
            [],
            {"hex": "broken"},
            {**valid, "lat": float("nan")},
            {**valid, "seen_pos": 61},
            valid,
            valid,
        ]
    }
    result = service(Session(Response(payload))).fetch(BOX)
    assert len(result.aircraft) == 1 and result.aircraft[0].icao24 == "abc123"


def test_freshness_boundary_and_box_filter():
    valid = fixture("adsb_lol")["ac"][0]
    result = service(
        Session(
            Response({"ac": [{**valid, "seen_pos": 60}, {**valid, "hex": "def456", "lon": 80}]})
        )
    ).fetch(BOX)
    assert [a.icao24 for a in result.aircraft] == ["abc123"]


def test_empty_success_does_not_fall_back():
    session = Session(Response({"ac": []}))
    result = service(session).fetch(BOX)
    assert result.provider == "adsb.lol" and result.aircraft == () and not result.errors
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "failure",
    [
        Response(status_code=500),
        Response(ValueError("bad JSON")),
        Response({"ac": None}),
        requests.Timeout(),
    ],
)
def test_total_failure_differs_from_empty(failure):
    result = service(Session(failure, failure, failure)).fetch(BOX)
    assert result.provider is None and len(result.errors) == 3


@pytest.mark.parametrize(
    "header,until",
    [("120", 120), ("Tue, 14 Nov 2023 22:15:20 GMT", 120), ("invalid", 60), (None, 60)],
)
def test_rate_limit_defers_primary_and_permits_fallback(header, until):
    now = [0]
    session = Session(
        Response(status_code=429, headers={"Retry-After": header} if header else {}),
        Response({"ac": []}),
        Response({"ac": []}),
        Response({"ac": []}),
    )
    provider = service(session, clock=lambda: now[0], wall_clock=lambda: 1700000000)
    assert provider.fetch(BOX).provider == "adsb.fi"
    now[0] = until - 1
    assert provider.fetch(BOX).provider == "adsb.fi"
    now[0] = until
    assert provider.fetch(BOX).provider == "adsb.lol"
    assert "api.adsb.lol" in session.calls[-1][1]


def test_opensky_uses_anonymous_fallback_without_environment(monkeypatch):
    monkeypatch.delenv("OPENSKY_CLIENT_ID", raising=False)
    monkeypatch.delenv("OPENSKY_CLIENT_SECRET", raising=False)
    session = Session(
        Response(status_code=503),
        Response(status_code=503),
        Response({"states": None, "time": 1700000000}),
    )
    assert service(session).fetch(BOX).provider == "opensky"
    assert "Authorization" not in session.calls[-1][2]["headers"]


def test_opensky_token_cache_expiry_and_secret_safe_logs(monkeypatch, caplog):
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "dummy-client")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "dummy-secret")
    now = [0]
    responses = []
    for token in ("first", "unused", "second"):
        responses.extend([Response(status_code=503), Response(status_code=503)])
        if token != "unused":
            responses.append(Response({"access_token": token, "expires_in": 120}))
        responses.append(Response({"states": [], "time": 1700000000}))
    session = Session(*responses)
    provider = service(session, clock=lambda: now[0])
    for time in (0, 59, 60):
        now[0] = time
        assert provider.fetch(BOX).provider == "opensky"
    auths = [
        call[2]["headers"]["Authorization"] for call in session.calls if "states/all" in call[1]
    ]
    assert auths == ["Bearer first", "Bearer first", "Bearer second"]
    assert "dummy-secret" not in caplog.text and "Bearer" not in caplog.text


def test_opensky_unauthorized_invalidates_token_without_retry(monkeypatch):
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "dummy-client")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "dummy-secret")
    session = Session(
        Response(status_code=503),
        Response(status_code=503),
        Response({"access_token": "one", "expires_in": 120}),
        Response(status_code=401),
        Response(status_code=503),
        Response(status_code=503),
        Response({"access_token": "two", "expires_in": 120}),
        Response({"states": []}),
    )
    provider = service(session)
    assert provider.fetch(BOX).provider is None
    assert len(session.calls) == 4
    assert provider.fetch(BOX).provider == "opensky"


def test_old_opensky_position_is_skipped():
    payload = fixture("opensky")
    payload["states"][0][3] = 1699999900
    result = service(
        Session(Response(status_code=503), Response(status_code=503), Response(payload))
    ).fetch(BOX)
    assert result.provider == "opensky" and result.aircraft == ()


def test_large_zone_uses_bbox_instead_of_silently_clamping_radius():
    session = Session(Response({"states": []}))
    result = service(session).fetch(Bounds(-30, 30, -30, 30))
    assert result.provider == "opensky" and len(result.errors) == 2
    assert session.calls[0][2]["params"]["lamin"] == -30
