import pytest

from aerowatch.models import AircraftObservation, Bounds

BOX = Bounds(-0.01, 0.01, -0.01, 0.01)


@pytest.mark.parametrize(
    "lat,lon,heading,edge",
    [
        (0, -0.02, 90, "West"),
        (0, 0.02, 270, "East"),
        (-0.02, 0, 0, "South"),
        (0.02, 0, 180, "North"),
    ],
)
def test_prediction_four_boundaries(lat, lon, heading, edge):
    from aerowatch.prediction import predict_entry

    result = predict_entry(
        BOX, AircraftObservation("abc123", "TEST", lat, lon, False, 100, heading)
    )
    assert result.boundary == edge
    assert result.eta_seconds == pytest.approx(11.1139, rel=1e-5)


@pytest.mark.parametrize(
    "lat,lon,speed,track",
    [
        (0, 0, 100, 90),
        (0, -0.01, 100, 90),
        (0, -0.02, 0, 90),
        (0, -0.02, None, 90),
        (0, -0.02, 100, None),
        (0, -0.02, 100, 270),
        (0.03, -0.02, 100, 90),
    ],
)
def test_non_entry_has_no_prediction(lat, lon, speed, track):
    from aerowatch.prediction import predict_entry

    assert (
        predict_entry(BOX, AircraftObservation("abc123", "TEST", lat, lon, False, speed, track))
        is None
    )


def test_corner_and_near_pole_are_finite():
    from aerowatch.prediction import predict_entry

    result = predict_entry(BOX, AircraftObservation("abc123", "TEST", -0.02, -0.02, False, 100, 45))
    assert result.eta_seconds == pytest.approx(15.71743, rel=1e-5)
    assert (
        predict_entry(
            Bounds(89.9, 90, 10, 20), AircraftObservation("abc123", "TEST", 90, 0, False, 100, 90)
        )
        is None
    )


def test_compass_wraparound():
    from aerowatch.prediction import compass_heading

    assert compass_heading(360) == "N"
    assert compass_heading(-90) == "W"
    assert compass_heading(92) == "E"
