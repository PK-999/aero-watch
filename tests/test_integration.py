from http_fakes import Response, Session

from aerowatch.config import load_config
from aerowatch.models import AircraftMetadata
from aerowatch.providers import TelemetryService
from aerowatch.tracker import FlightTracker


def test_fixture_to_event_to_console_without_network_or_desktop(capsys):
    from dataclasses import replace

    from aerowatch.notifications import NotificationManager, format_notification

    config = load_config()
    tracker = FlightTracker(
        config.locations["hal_area"], replace(config.tracking, ignore_ground_aircraft=True)
    )
    notifier = NotificationManager(replace(config.notifications, enabled=False))
    records = [
        {"hex": "abc123", "lat": 12.95, "lon": 77.59, "alt_baro": 3000, "gs": 200, "track": 90},
        {"hex": "abc123", "lat": 12.95, "lon": 77.67, "alt_baro": 3000, "gs": 200, "track": 90},
        {"hex": "abc123", "lat": 12.95, "lon": 77.73, "alt_baro": 3000, "gs": 200, "track": 90},
        {"hex": "def456", "lat": 12.95, "lon": 77.67, "alt_baro": "ground", "gs": 0},
        {"hex": "def456", "lat": 12.95, "lon": 77.67, "alt_baro": 300, "gs": 100, "track": 90},
        {"hex": "def456", "lat": 12.95, "lon": 77.73, "alt_baro": 3000, "gs": 200, "track": 90},
    ]
    service = TelemetryService(
        config, session=Session(*[Response({"ac": [record]}) for record in records])
    )
    kinds = []
    for index in range(len(records)):
        result = service.fetch(config.locations["hal_area"].bounds.expanded(0.15))
        for event in tracker.process(result.aircraft, index * 10):
            kinds.append(event.kind)
            notifier.send(
                format_notification(
                    event, config.locations["hal_area"], AircraftMetadata(), config.radar_base_url
                )
            )
    assert kinds == ["incoming", "departed", "takeoff", "departed"]
    assert "https://globe.adsbexchange.com/?icao=def456" in capsys.readouterr().out
