"""Readable alert presentation with optional macOS desktop delivery."""

import logging
import subprocess
import sys
from collections.abc import Callable
from urllib.parse import urlencode

from .config import NotificationSettings
from .models import AircraftMetadata, AlertEvent, Location, Notification
from .prediction import compass_heading

LOG = logging.getLogger(__name__)


def format_notification(
    event: AlertEvent, location: Location, metadata: AircraftMetadata, radar_base_url: str
) -> Notification:
    aircraft = event.aircraft
    name = (
        metadata.flight_number
        or metadata.registration
        or aircraft.callsign
        or aircraft.icao24.upper()
    )
    labels = {
        "incoming": "INCOMING",
        "overhead": "OVERHEAD",
        "takeoff": "TAKEOFF",
        "departed": "DEPARTED",
    }
    label = (
        "ON GROUND"
        if event.kind == "overhead" and aircraft.on_ground is True
        else labels[event.kind]
    )
    eta = f" (~{round(event.prediction.eta_seconds)}s ETA)" if event.prediction else ""
    title = f"{label}{eta}: {name}"
    if metadata.type_code:
        title += f" • {metadata.type_code}"
    subtitle = " • ".join(
        v for v in (location.name, metadata.operator or metadata.airline or aircraft.country) if v
    )
    lines = []
    if event.prediction:
        heading = (
            compass_heading(aircraft.track_deg) if aircraft.track_deg is not None else "Unavailable"
        )
        lines.append(f"Entering from {event.prediction.boundary} boundary • Heading {heading}")
    if metadata.model:
        lines.append(f"Aircraft: {metadata.model}")
    altitude = aircraft.baro_altitude_m
    geometric = altitude is None and aircraft.geo_altitude_m is not None
    if geometric:
        altitude = aircraft.geo_altitude_m
    if aircraft.on_ground is True:
        lines.append("Status: On ground")
    elif altitude is None:
        lines.append("Altitude: Unavailable")
    else:
        lines.append(
            f"Altitude: {round(altitude):,} m ({round(altitude * 3.28084):,} ft)"
            + (" [geometric]" if geometric else "")
        )
    if aircraft.on_ground is not True and aircraft.vertical_rate_ms is not None:
        rate = round(aircraft.vertical_rate_ms * 196.85)
        status = "Climbing" if rate > 100 else "Descending" if rate < -100 else "Level"
        lines.append(f"{status} ({rate:+,} fpm)")
    if aircraft.speed_ms is not None:
        lines.append(
            f"Speed: {round(aircraft.speed_ms * 3.6)} km/h ({round(aircraft.speed_ms * 1.94384)} kts)"
        )
    if aircraft.track_deg is not None:
        lines.append(f"Heading: {round(aircraft.track_deg)}° {compass_heading(aircraft.track_deg)}")
    if metadata.route:
        lines.append(f"Route: {metadata.route}")
    url = f"{radar_base_url.rstrip('/')}/?{urlencode({'icao': aircraft.icao24})}"
    return Notification(title, "\n".join(lines), subtitle, url)


def _applescript_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n")


class NotificationManager:
    def __init__(
        self,
        settings: NotificationSettings,
        runner: Callable = subprocess.run,
        platform: str = sys.platform,
    ):
        self.settings = settings
        self.runner = runner
        self.platform = platform
        self._fallback_warned = False

    def _run(self, command):
        return self.runner(command, check=True, capture_output=True, timeout=5, shell=False)

    def send(self, notification: Notification) -> None:
        print(
            f"\n{notification.title}\n{notification.subtitle}\n{notification.message}\nRadar: {notification.url}",
            flush=True,
        )
        if not self.settings.enabled or self.platform != "darwin":
            return
        command = [
            "terminal-notifier",
            "-title",
            notification.title,
            "-subtitle",
            notification.subtitle,
            "-message",
            notification.message,
            "-open",
            notification.url,
        ]
        if self.settings.sound:
            command.extend(["-sound", "default"])
        try:
            self._run(command)
            return
        except (OSError, subprocess.SubprocessError):
            if not self._fallback_warned:
                LOG.warning(
                    "Using AppleScript fallback; click-to-open radar is unavailable. Check terminal-notifier installation and macOS notification permissions."
                )
                self._fallback_warned = True
        title, message, subtitle = (
            _applescript_string(v)
            for v in (notification.title, notification.message, notification.subtitle)
        )
        sound = ' sound name "Glass"' if self.settings.sound else ""
        script = f'tell application "System Events" to display notification "{message}" with title "{title}" subtitle "{subtitle}"{sound}'
        try:
            self._run(["osascript", "-e", script])
            if self.settings.auto_open_url:
                self._run(["open", notification.url])
        except (OSError, subprocess.SubprocessError):
            LOG.warning("Desktop notifications unavailable; alerts remain visible in the console.")
