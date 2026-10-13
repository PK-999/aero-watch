def test_inclusive_bounds_and_clamped_expansion():
    from aerowatch.models import Bounds

    bounds = Bounds(89, 90, 170, 180)
    assert bounds.contains(90, 180)
    assert not bounds.contains(88, 179)
    expanded = bounds.expanded(1)
    assert (expanded.lamin, expanded.lamax, expanded.lomin, expanded.lomax) == (88, 90, 169, 180)
