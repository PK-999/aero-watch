import json
from pathlib import Path

import pytest
import requests


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Tests must inject HTTP sessions, not use live APIs")

    monkeypatch.setattr(requests.Session, "request", reject)


@pytest.fixture
def config_dir(tmp_path):
    source = Path(__file__).parents[1] / "config"
    for name in ("locations.json", "settings.json"):
        (tmp_path / name).write_text((source / name).read_text())
    return tmp_path


def edit_json(directory, filename, transform):
    path = directory / filename
    value = json.loads(path.read_text())
    transform(value)
    path.write_text(json.dumps(value))
