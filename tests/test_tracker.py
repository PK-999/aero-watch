from dataclasses import replace

import pytest

from aerowatch.config import TrackingSettings
from aerowatch.models import AircraftObservation, Bounds, Location

LOCATION = Location("Test zone", Bounds(-0.01, 0.01, -0.01, 0.01))
INSIDE = AircraftObservation("abc123", "TEST", 0, 0, False, 100, 90, 1000, None, 2)
OUTSIDE = replace(INSIDE, longitude=0.02)
APPROACH = replace(INSIDE, longitude=-0.03699)  # Approximately 30 s at 100 m/s to western boundary
GROUND = replace(INSIDE, on_ground=True, speed_ms=0, baro_altitude_m=0)


def tracker(**settings):
    from aerowatch.tracker import FlightTracker

    return FlightTracker(LOCATION, TrackingSettings(**settings))


def run(frames, **settings):
    instance = tracker(**settings)
    return [
        event.kind for i, frame in enumerate(frames) for event in instance.process(frame, i * 10)
    ]


def test_configured_warning_lead_time_and_threshold():
    assert run([[APPROACH]], warning_lead_time_seconds=5) == []
    assert run([[APPROACH]], warning_lead_time_seconds=30) == ["incoming"]
    assert run([[APPROACH]], predictive_warning=False) == []
    assert run([[replace(APPROACH, longitude=-0.03)]], warning_lead_time_seconds=22.2278) == [
        "incoming"
    ]


def test_first_climbing_sighting_is_overhead_not_takeoff():
    assert run([[INSIDE]]) == ["overhead"]


def test_observed_takeoff_takes_priority_over_overhead():
    assert run([[GROUND], [INSIDE]], ignore_ground_aircraft=True) == ["takeoff"]


def test_disabled_departures_suppress_takeoff_and_exit():
    assert run(
        [[GROUND], [INSIDE], [OUTSIDE]], notify_on_departure=False, ignore_ground_aircraft=True
    ) == ["overhead"]


def test_ground_activity_setting_and_history():
    assert run([[GROUND], [GROUND]], ignore_ground_aircraft=False) == ["overhead"]
    assert run([[GROUND], [GROUND]], ignore_ground_aircraft=True) == []
    assert run([[GROUND], [replace(OUTSIDE, on_ground=True)]], ignore_ground_aircraft=False) == [
        "overhead"
    ]


def test_unknown_ground_breaks_takeoff_evidence():
    assert run(
        [[GROUND], [replace(INSIDE, on_ground=None)], [INSIDE]], ignore_ground_aircraft=True
    ) == ["overhead"]


@pytest.mark.parametrize(
    "exit_observation",
    [OUTSIDE, replace(OUTSIDE, track_deg=270), replace(OUTSIDE, track_deg=None, speed_ms=None)],
)
def test_exit_independent_of_prediction_and_motion(exit_observation):
    assert run([[INSIDE], [exit_observation]]) == ["overhead", "departed"]


def test_incoming_suppresses_redundant_overhead():
    assert run([[APPROACH], [INSIDE], [INSIDE], [OUTSIDE], [OUTSIDE]]) == ["incoming", "departed"]


def test_second_visit_has_fresh_warning_and_departure():
    assert run([[APPROACH], [INSIDE], [OUTSIDE], [APPROACH], [INSIDE], [OUTSIDE]]) == [
        "incoming",
        "departed",
        "incoming",
        "departed",
    ]


def test_abandoned_approach_can_warn_again():
    assert run([[APPROACH], [replace(APPROACH, track_deg=270)], [APPROACH]]) == [
        "incoming",
        "incoming",
    ]


def test_duplicate_observations_produce_one_event():
    assert run([[INSIDE, INSIDE]]) == ["overhead"]


def test_missing_aircraft_does_not_prove_exit():
    assert run([[INSIDE], [], [], [INSIDE]]) == ["overhead"]


def test_state_expires_at_600_seconds_without_refresh():
    instance = tracker()
    assert [e.kind for e in instance.process([INSIDE], 0)] == ["overhead"]
    assert instance.process([], 599) == []
    assert instance.process([INSIDE], 599) == []
    instance.process([], 1199)
    assert [e.kind for e in instance.process([INSIDE], 1200)] == ["overhead"]


def test_entry_setting_and_ground_not_predictive():
    assert run([[INSIDE]], notify_on_entry=False) == []
    assert run([[replace(APPROACH, on_ground=True)]]) == []
    assert run([[replace(APPROACH, on_ground=None)]]) == []


def test_takeoff_emits_once_per_visit_and_resets_after_exit():
    assert run([[GROUND], [INSIDE], [GROUND], [INSIDE]], ignore_ground_aircraft=True) == ["takeoff"]
    assert run(
        [[GROUND], [INSIDE], [OUTSIDE], [GROUND], [INSIDE]], ignore_ground_aircraft=True
    ) == ["takeoff", "departed", "takeoff"]
