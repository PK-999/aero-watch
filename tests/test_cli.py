import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from aerowatch.models import AircraftMetadata, AircraftObservation, ScanResult


def main(args):
    from aerowatch.cli import main

    return main(args)


def test_list_locations_without_network(capsys):
    assert main(["--list-locations"]) == 0
    assert "hal_area" in capsys.readouterr().out


def test_help_without_network(capsys):
    with pytest.raises(SystemExit) as error:
        main(["--help"])
    assert error.value.code == 0 and "--demo" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args",
    [[], ["missing"], ["--demo", "blr_airport"], ["--config-dir", "/nonexistent", "hal_area"]],
)
def test_usage_and_configuration_errors_are_code_2(args, capsys):
    assert main(args) == 2
    assert "error" in capsys.readouterr().err.lower()


def test_finite_offline_demo_has_expected_events(capsys):
    assert main(["--demo"]) == 0
    output = capsys.readouterr().out
    assert "synthetic" in output.lower()
    assert output.count("INCOMING") == 1 and output.count("TAKEOFF") == 1
    assert output.count("DEPARTED") == 2 and "ON GROUND" not in output


def install_scan(monkeypatch, *results):
    import aerowatch.cli as cli

    pending = list(results)

    class Service:
        def __init__(self, *args, **kwargs):
            pass

        def fetch(self, bounds):
            if not pending:
                raise KeyboardInterrupt
            result = pending.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result

    monkeypatch.setattr(cli, "TelemetryService", Service)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)


@pytest.mark.parametrize(
    "result,code", [(ScanResult((), "adsb.lol"), 0), (ScanResult((), None, ("offline",)), 1)]
)
def test_once_reports_provider_health(monkeypatch, result, code, capsys, caplog):
    install_scan(monkeypatch, result)
    assert main(["hal_area", "--once", "--no-notifications"]) == code
    output = capsys.readouterr().out
    assert "offline" in caplog.text if code else "adsb.lol" in output


def test_continuous_outage_recovers_and_ctrl_c_is_clean(monkeypatch, capsys):
    install_scan(monkeypatch, ScanResult((), None, ("offline",)), ScanResult((), "adsb.fi"))
    assert main(["hal_area", "--no-notifications"]) == 0
    assert "adsb.fi" in capsys.readouterr().out


def test_ctrl_c_during_sleep_returns_zero(monkeypatch):
    import aerowatch.cli as cli

    install_scan(monkeypatch, ScanResult((), "adsb.lol"))

    def interrupt(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", interrupt)
    assert main(["hal_area", "--no-notifications"]) == 0


def test_metadata_only_for_alerts_and_failures_still_deliver(monkeypatch, capsys):
    import aerowatch.cli as cli

    airplane = AircraftObservation("abc123", "TEST", 12.95, 77.67, False, 100, 90)
    outside = replace(airplane, icao24="def456", longitude=77.85)
    install_scan(monkeypatch, ScanResult((airplane, outside), "adsb.lol"))
    seen = []

    class Metadata:
        def lookup(self, aircraft):
            seen.append(aircraft.icao24)
            return AircraftMetadata()

    monkeypatch.setattr(cli, "MetadataService", Metadata)
    assert main(["hal_area", "--once", "--no-notifications", "--verbose"]) == 0
    assert seen == ["abc123"] and "OVERHEAD" in capsys.readouterr().out


def test_legacy_launcher_is_usable():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / "aero_watch.py"), "--list-locations"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0 and "blr_airport" in result.stdout
