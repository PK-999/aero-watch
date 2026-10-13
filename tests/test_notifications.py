import subprocess
from dataclasses import replace

import pytest

from aerowatch.config import NotificationSettings
from aerowatch.models import (
    AircraftMetadata,
    AircraftObservation,
    AlertEvent,
    Bounds,
    Location,
    Notification,
    Prediction,
)

AIRCRAFT = AircraftObservation("abc123", "TEST123", 12.95, 77.67, False, 100, 90, 1000, None, 2)
LOCATION = Location("HAL Area", Bounds(12.91, 13, 77.62, 77.72))
NOTE = Notification(
    'A "title"', 'Line 1\nLine "2" \\ end', "Subtitle", "https://example.com/?icao=abc123"
)


class Runner:
    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.errors:
            error = self.errors.pop(0)
            if error:
                raise error
        return subprocess.CompletedProcess(argv, 0)


def manager(runner, **kwargs):
    from aerowatch.notifications import NotificationManager

    return NotificationManager(NotificationSettings(**kwargs), runner=runner, platform="darwin")


def test_formatter_contains_identity_units_prediction_and_radar():
    from aerowatch.notifications import format_notification

    note = format_notification(
        AlertEvent("incoming", AIRCRAFT, Prediction(30, "West")),
        LOCATION,
        AircraftMetadata(model="Test aircraft", route="HYD → BLR"),
        "https://globe.adsbexchange.com",
    )
    assert "INCOMING" in note.title and "30s" in note.title and "TEST123" in note.title
    assert "1,000 m" in note.message and "3,281 ft" in note.message
    assert "360 km/h" in note.message and "194 kts" in note.message and "Climbing" in note.message
    assert "West" in note.message and "HYD → BLR" in note.message
    assert note.url == "https://globe.adsbexchange.com/?icao=abc123"


def test_missing_fields_and_ground_have_honest_labels():
    from aerowatch.notifications import format_notification

    unknown = AircraftObservation("abc123", "", 12.95, 77.67)
    note = format_notification(
        AlertEvent("overhead", unknown), LOCATION, AircraftMetadata(), "https://example.com"
    )
    assert "ABC123" in note.title and "Unavailable" in note.message
    ground = format_notification(
        AlertEvent("overhead", replace(AIRCRAFT, on_ground=True)),
        LOCATION,
        AircraftMetadata(),
        "https://example.com",
    )
    assert "ON GROUND" in ground.title


def test_terminal_notifier_arguments_and_sound(capsys):
    runner = Runner()
    manager(runner).send(NOTE)
    argv, options = runner.calls[0]
    assert argv[0] == "terminal-notifier" and argv[argv.index("-open") + 1] == NOTE.url
    assert argv[argv.index("-title") + 1] == 'A "title"'
    assert "-sound" in argv and options["timeout"] == 5 and options["shell"] is False
    assert "Line 1" in capsys.readouterr().out


def test_sound_disabled_does_not_add_sound_argument():
    runner = Runner()
    manager(runner, sound=False).send(NOTE)
    assert "-sound" not in runner.calls[0][0]


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(),
        subprocess.CalledProcessError(3, ["terminal-notifier"]),
        subprocess.TimeoutExpired(["terminal-notifier"], 5),
    ],
)
def test_fallback_escapes_applescript_and_explains_click_limitation(error, caplog):
    runner = Runner(error)
    manager(runner).send(NOTE)
    argv, options = runner.calls[1]
    assert argv[0] == "osascript" and options["timeout"] == 5
    script = argv[2]
    assert (
        '\\"title\\"' in script and '\\"2\\"' in script and "\\\\ end" in script and "\\n" in script
    )
    assert "click" in caplog.text.lower()
    assert not any(call[0][0] == "open" for call in runner.calls)


def test_unavailable_desktop_is_nonfatal(caplog):
    runner = Runner(FileNotFoundError(), FileNotFoundError())
    manager(runner).send(NOTE)
    assert "unavailable" in caplog.text.lower()


def test_auto_open_is_opt_in_for_fallback():
    runner = Runner(FileNotFoundError())
    manager(runner, auto_open_url=True).send(NOTE)
    assert runner.calls[-1][0] == ["open", NOTE.url]


@pytest.mark.parametrize("platform,enabled", [("linux", True), ("win32", True), ("darwin", False)])
def test_console_output_without_desktop_execution(platform, enabled, capsys):
    from aerowatch.notifications import NotificationManager

    runner = Runner()
    NotificationManager(
        NotificationSettings(enabled=enabled), runner=runner, platform=platform
    ).send(NOTE)
    assert runner.calls == [] and 'A "title"' in capsys.readouterr().out
