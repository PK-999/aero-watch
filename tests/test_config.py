import json

import pytest
from conftest import edit_json


def test_packaged_defaults_outside_checkout(tmp_path, monkeypatch):
    from aerowatch.config import load_config

    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.locations["hal_area"].bounds.lamin == 12.91
    assert config.locations["blr_airport"].name == "BLR Airport (Kempegowda)"
    assert config.tracking.warning_lead_time_seconds == 60
    assert config.notifications.auto_open_url is False


def test_explicit_and_checkout_precedence(config_dir, monkeypatch):
    from aerowatch.config import load_config

    edit_json(config_dir, "settings.json", lambda d: d["tracking"].update(poll_interval=17))
    assert load_config(config_dir).tracking.poll_interval == 17
    root = config_dir / "checkout"
    root.mkdir()
    # Explicit selection does not depend on the caller's working directory.
    monkeypatch.chdir(root)
    assert load_config(config_dir).tracking.poll_interval == 17
    local = root / "config"
    local.mkdir()
    for name in ("settings.json", "locations.json"):
        (local / name).write_text((config_dir / name).read_text())
    assert load_config().tracking.poll_interval == 17


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), 10**400, "10", True])
@pytest.mark.parametrize("key", ["poll_interval", "warning_lead_time_seconds"])
def test_invalid_positive_intervals(config_dir, key, value):
    from aerowatch.config import ConfigError, load_config

    edit_json(config_dir, "settings.json", lambda d: d["tracking"].update({key: value}))
    with pytest.raises(ConfigError, match=key):
        load_config(config_dir)


@pytest.mark.parametrize(
    "change",
    [
        {"lamin": 91},
        {"lomax": 181},
        {"lamin": float("nan")},
        {"lamin": 13, "lamax": 13},
        {"lomin": -170, "lomax": 170},
    ],
)
def test_invalid_bounds(config_dir, change):
    from aerowatch.config import ConfigError, load_config

    edit_json(config_dir, "locations.json", lambda d: d["hal_area"].update(change))
    with pytest.raises(ConfigError, match="hal_area"):
        load_config(config_dir)


def test_reversed_bounds_are_normalized(config_dir):
    from aerowatch.config import load_config

    edit_json(config_dir, "locations.json", lambda d: d["hal_area"].update(lamin=13, lamax=12.91))
    bounds = load_config(config_dir).locations["hal_area"].bounds
    assert (bounds.lamin, bounds.lamax) == (12.91, 13)


@pytest.mark.parametrize(
    "case",
    [
        "missing_file",
        "invalid_json",
        "missing_section",
        "missing_bound",
        "boolean",
        "negative_buffer",
        "not_object",
    ],
)
def test_actionable_configuration_errors(config_dir, case):
    from aerowatch.config import ConfigError, load_config

    if case == "missing_file":
        (config_dir / "settings.json").unlink()
    elif case == "invalid_json":
        (config_dir / "settings.json").write_text("{")
    elif case == "not_object":
        (config_dir / "settings.json").write_text(json.dumps([]))
    elif case == "missing_section":
        edit_json(config_dir, "settings.json", lambda d: d.pop("tracking"))
    elif case == "missing_bound":
        edit_json(config_dir, "locations.json", lambda d: d["hal_area"].pop("lamin"))
    elif case == "boolean":
        edit_json(
            config_dir, "settings.json", lambda d: d["tracking"].update(predictive_warning="yes")
        )
    else:
        edit_json(
            config_dir,
            "settings.json",
            lambda d: d["tracking"].update(surveillance_buffer_degrees=-1),
        )
    with pytest.raises(ConfigError) as error:
        load_config(config_dir)
    assert str(error.value)
