"""Command-line orchestration: fetch, track, enrich, present, repeat."""

import argparse
import json
import logging
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

from .config import ConfigError, TrackingSettings, load_config
from .metadata import MetadataService
from .models import AircraftMetadata, AircraftObservation, Bounds, Location
from .notifications import NotificationManager, format_notification
from .providers import TelemetryService
from .tracker import FlightTracker

LOG = logging.getLogger(__name__)


def _demo(config) -> int:
    scenario = json.loads(files("aerowatch").joinpath("data/demo.json").read_text(encoding="utf-8"))
    location = Location("HAL Area (demo)", Bounds(**scenario["bounds"]))
    tracker = FlightTracker(location, TrackingSettings(ignore_ground_aircraft=True))
    notifier = NotificationManager(replace(config.notifications, enabled=False))
    print("Aero Watch synthetic demo • bundled HAL bounds • no network or desktop notifications")
    for frame in scenario["frames"]:
        aircraft = [AircraftObservation(**record) for record in frame["aircraft"]]
        for event in tracker.process(aircraft, frame["time"]):
            metadata = AircraftMetadata(
                registration=event.aircraft.registration,
                model=event.aircraft.model,
                type_code=event.aircraft.type_code,
            )
            notifier.send(format_notification(event, location, metadata, config.radar_base_url))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Track nearby aircraft and predict airspace entry."
    )
    parser.add_argument("location", nargs="?", help="Location preset to track")
    parser.add_argument("--list-locations", action="store_true", help="List configured presets")
    parser.add_argument(
        "--config-dir", type=Path, help="Directory containing settings.json and locations.json"
    )
    parser.add_argument("--once", action="store_true", help="Fetch and process one live scan")
    parser.add_argument(
        "--demo", action="store_true", help="Play a finite synthetic HAL scenario offline"
    )
    parser.add_argument(
        "--no-notifications", action="store_true", help="Show alerts in the console only"
    )
    parser.add_argument("--verbose", action="store_true", help="Show debug diagnostics")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("aerowatch").setLevel(logging.DEBUG if args.verbose else logging.INFO)
    try:
        config = load_config(args.config_dir)
        if args.list_locations:
            print("Available locations:")
            for key, location in config.locations.items():
                print(f"  {key}: {location.name}")
            return 0
        if args.demo:
            if args.location not in (None, "hal_area"):
                raise ConfigError("The bundled demo supports hal_area only")
            return _demo(config)
        if not args.location:
            raise ConfigError("A location is required; use --list-locations or --demo")
        if args.location not in config.locations:
            raise ConfigError(f"Unknown location '{args.location}'; use --list-locations")
    except ConfigError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    location = config.locations[args.location]
    bounds = location.bounds.expanded(config.tracking.surveillance_buffer_degrees)
    tracker = FlightTracker(location, config.tracking)
    telemetry, metadata = TelemetryService(config), MetadataService()
    notifier = NotificationManager(
        replace(
            config.notifications, enabled=config.notifications.enabled and not args.no_notifications
        )
    )
    print(f"Aero Watch • {location.name} • polling every {config.tracking.poll_interval:g}s")
    try:
        while True:
            result = telemetry.fetch(bounds)
            if result.provider is None:
                LOG.warning("Data unavailable: %s", "; ".join(result.errors))
            else:
                print(
                    f"Provider: {result.provider} • {len(result.aircraft)} aircraft in surveillance area",
                    flush=True,
                )
            for event in tracker.process(result.aircraft, time.monotonic()):
                details = metadata.lookup(event.aircraft)
                notifier.send(format_notification(event, location, details, config.radar_base_url))
            if args.once:
                return 0 if result.provider is not None else 1
            time.sleep(config.tracking.poll_interval)
    except KeyboardInterrupt:
        print("\nFlight tracking stopped.")
        return 0
