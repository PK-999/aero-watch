# Aero Watch Portfolio Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an understandable, installable flight tracker with corrected alerts, a reproducible offline demo, and meaningful verification.

**Architecture:** A synchronous `src/aerowatch/` package separates normalized data, pure tracking, provider access, optional enrichment, and delivery. The CLI connects those parts; tests inject clocks, HTTP sessions, and subprocess runners.

**Tech Stack:** Python 3.11+, requests, setuptools, pytest, Ruff, build, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-12-portfolio-refactor-design.md` (approved 13 October 2026).

## Global Constraints

- Require Python 3.11 or newer.
- Keep the application synchronous and its only runtime third-party dependency as `requests`.
- Runtime requirement: `requests>=2.32,<3`.
- Preserve its identity, original attribution, existing location presets, and `python aero_watch.py <location>` launch command.
- No web UI, database, deployment service, or background daemon.
- Telemetry provider order: adsb.lol, adsb.fi, then OpenSky; successful empty data ends fallback.
- Telemetry connect/read timeouts: 3.5 seconds each. Metadata connect/read timeouts: 2.5 seconds each.
- Position-age limit: 60 seconds. State expiry: 600 seconds.
- Aircraft metadata lifetime: 3,600 seconds. Route and failure cache lifetime: 300 seconds.
- Automatic URL opening is disabled by default. CI must not access live APIs or show notifications.
- Distinguish local checks, live API observations, and native macOS notification verification in the final report.

## Review Focus

1. A malformed or duplicate aircraft record must not hide a valid neighboring aircraft or repeat its alert (Tasks 2 and 3).
2. Unknown or stale telemetry must not invent headings, ground transitions, or departures (Tasks 2 and 3).
3. HTTP 429 with numeric or HTTP-date Retry-After must defer that provider while allowing healthy fallback (Task 2).
4. Changed callsigns and sparse/error enrichment must not attach an old route or erase known aircraft identity (Task 4).
5. Wheel execution outside the checkout and unavailable notification executables must still produce understandable output (Tasks 5 and 6).

## File Structure and Shared Types

Create the modules and packaged resources listed in the spec. Keep the root
launcher and editable `config/`; remove the five root implementation modules only
after Task 5 verifies their replacement. Tests belong in `tests/`, with synthetic
provider responses in `tests/fixtures/`. Documentation belongs in README.md,
CONTRIBUTING.md, and `docs/architecture.md`; CI in `.github/workflows/ci.yml`.

Use frozen dataclasses for values, keeping mutable per-aircraft state private to
the tracker. These are the cross-task interfaces; consumers use named attributes:

```python
Bounds(lamin: float, lamax: float, lomin: float, lomax: float)
Location(name: str, bounds: Bounds)
AircraftObservation(
    icao24: str, callsign: str, latitude: float, longitude: float,
    on_ground: bool | None = None, speed_ms: float | None = None,
    track_deg: float | None = None, baro_altitude_m: float | None = None,
    geo_altitude_m: float | None = None, vertical_rate_ms: float | None = None,
    squawk: str | None = None, country: str | None = None,
    registration: str | None = None, model: str | None = None,
    type_code: str | None = None,
)
Prediction(eta_seconds: float, boundary: str)
AlertEvent(kind: Literal['incoming', 'overhead', 'takeoff', 'departed'],
           aircraft: AircraftObservation, prediction: Prediction | None = None)
AircraftMetadata(registration: str | None = None, model: str | None = None,
                 type_code: str | None = None, operator: str | None = None,
                 airline: str | None = None, route: str | None = None,
                 flight_number: str | None = None)
ScanResult(aircraft: tuple[AircraftObservation, ...], provider: str | None,
           errors: tuple[str, ...] = ())
Notification(title: str, message: str, subtitle: str, url: str)
```

`ScanResult.provider is None` means total failure; a non-None provider with no
aircraft means healthy empty data. `AppConfig` contains `locations`, `tracking`,
`notifications`, `opensky`, and `radar_base_url`. Use `TrackingSettings` and
`NotificationSettings` dataclasses with the existing JSON keys as field names.
`OpenSkySettings` contains `base_url`, `auth_url`, and `token_buffer_seconds`;
credentials come only from the environment. Request/provider failures use a
`ProviderError` exception carrying a safe reason and optional HTTP status and
Retry-After value. Do not include response bodies or credentials in that reason.

## Task 1: Installable Package, Models, and Validated Configuration

**Files:** Create `pyproject.toml`, `src/aerowatch/{__init__,models,config}.py`,
`src/aerowatch/data/{settings,locations}.json`, `tests/test_config.py`, and
`tests/test_models.py`, and `tests/conftest.py`. Modify `requirements.txt` and `.gitignore`.

**Interfaces:** Produce the shared types above; `Bounds.contains(latitude: float,
longitude: float) -> bool`, `Bounds.expanded(buffer: float) -> Bounds`, and
`load_config(config_dir: Path | None = None) -> AppConfig`. Configuration errors
raise `ConfigError(ValueError)`. `load_config(None)` discovers `./config` before
using `importlib.resources` defaults; an explicit directory never falls back.

- [ ] Write failing tests for resource loading outside the repo, checkout/explicit precedence, missing files, malformed JSON, missing keys, strict booleans, NaN/infinity, invalid coordinates, zero-area boxes, antimeridian spans, reversed bounds, nonpositive intervals, negative buffers, and surveillance clamping. Assert inclusive bounds and existing preset names/coordinates.

```python
assert load_config(default_directory).tracking.warning_lead_time_seconds == 60
assert Bounds(12.91, 13.0, 77.62, 77.72).contains(12.91, 77.72)
with pytest.raises(ConfigError):
    load_config(directory_with_negative_poll_interval)
```

- [ ] Run `.venv/bin/python -m pytest tests/test_config.py tests/test_models.py -q`; verify failures come from the missing package/interfaces. Add development dependencies and editable installation before this run so pytest itself is available.
- [ ] Implement models, configuration, and packaged defaults. Normalize reversed bounds; reject longitude spans above 180 degrees rather than representing antimeridian boxes. Apply existing defaults to optional keys, validate required sections, and ignore legacy placeholder credentials. Configure setuptools discovery/package data, the `aero-watch = aerowatch.cli:main` entry point, pytest source/test paths, Ruff, and the dev extra. Add an autouse fixture that rejects real `requests.Session.request` calls; injected fake sessions remain usable.
- [ ] Run the Task 1 tests plus `.venv/bin/python -m ruff check src/aerowatch tests` and `.venv/bin/python -m ruff format --check src/aerowatch tests`; expect zero failures/errors. The CLI entry point becomes callable in Task 5.
- [ ] Commit only Task 1 files with `refactor: introduce package models and validated configuration`.

## Task 2: Observable Telemetry Adapters and Rate-Aware Fallback

**Files:** Create `src/aerowatch/providers.py`, `tests/test_providers.py`, and
`tests/fixtures/{adsb_lol,adsb_fi,opensky}.json`.

**Interfaces:** Consume AppConfig, Bounds, AircraftObservation, and ScanResult.
Produce `TelemetryService(config: AppConfig, session: requests.Session | None =
None, clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], float]
= time.time)` and `fetch(bounds: Bounds) -> ScanResult`. Keep provider-specific
normalizers and OpenSky token handling inside this module. One successful scan
returns at most one observation per ICAO, keeping the first valid duplicate.

- [ ] Write failing fixture tests for both readsb providers and OpenSky indexed states: SI conversions, missing motion/ground values, malformed records before valid ones, nonfinite coordinates, explicit age 60 accepted/61 rejected, duplicate ICAOs, HTTP/JSON/schema failures, and strict distinction between failed and healthy empty scans. Test the adsb.fi v3 URL and `ac` response key.

```python
assert result.aircraft[0].speed_ms == pytest.approx(100 * 0.514444)
assert unknown.aircraft[0].track_deg is None
assert healthy_empty.provider == 'adsb.lol' and healthy_empty.aircraft == ()
assert all_failed.provider is None and len(all_failed.errors) == 3
```

- [ ] Add tests for numeric and HTTP-date Retry-After, invalid-header 60-second fallback, cooldown expiry with injected clocks, timeout tuples, User-Agent, anonymous OpenSky without credentials, cached token use, expiry buffer, and 401 invalidation without immediate retries. Assert logs never contain the dummy secret or bearer token. Failed responses must not partially ingest a malformed payload as success.
- [ ] Run `.venv/bin/python -m pytest tests/test_providers.py -q`; confirm the new interface is missing.
- [ ] Implement ordered fallback, schema normalization, per-provider cooldowns, and bounded OpenSky authentication. Derive provider radius from expanded bounds with latitude-aware longitude distance; do not silently truncate a zone beyond a provider's documented range. Reject unsupported provider queries with a safe reason and permit OpenSky bounding-box fallback. Filter results to requested bounds.
- [ ] Run config/model/provider tests and Ruff checks; expect all pass. Check that valid empty primary responses make exactly one request and rate-limited primaries do not block secondary success.
- [ ] Commit Task 2 files with `fix: normalize telemetry and expose provider failures`.

## Task 3: Pure Prediction and Correct Per-Visit Alert State

**Files:** Create `src/aerowatch/{prediction,tracker}.py`,
`tests/test_prediction.py`, and `tests/test_tracker.py`.

**Interfaces:** Produce `predict_entry(bounds: Bounds, aircraft:
AircraftObservation) -> Prediction | None`; `compass_heading(degrees: float) ->
str`; and `FlightTracker(location: Location, settings: TrackingSettings)` with
`process(aircraft: Iterable[AircraftObservation], now: float) -> list[AlertEvent]`.
`now` is monotonic seconds supplied by the caller. Use bounds for actual
transitions; predictions describe only future entry. No I/O inside the tracker.

- [ ] Write failing geometry tests for all four edges, corners, parallel paths, movement away, inside/boundary positions, stationary/missing motion, and near-pole coordinates. Assert no division errors and no prediction for unknown heading or already-inside aircraft.
- [ ] Write state-sequence tests for configured lead time 5 versus ETA 30; threshold equality; prediction disabled; initial overhead; observed takeoff; first climbing sighting; departure alerts disabled; ground filtering retaining transition history; optional ground activity; unknown ground not creating takeoff; outside heading toward the box; missing exit motion; warning/overhead suppression; two complete visits; abandoned/restarted approaches; duplicate batch observations; outages and missing aircraft; expiry at 600 seconds.

```python
assert kinds(initial_climbing_inside) == ['overhead']
assert kinds(ground_then_airborne_inside) == ['takeoff']
assert kinds(inside_then_outside_heading_toward_box) == ['overhead', 'departed']
assert kinds(warn_then_enter_then_leave) == ['incoming', 'departed']
assert kinds(eta_30_with_lead_5) == []
```

- [ ] Run `.venv/bin/python -m pytest tests/test_prediction.py tests/test_tracker.py -q`; confirm failures before implementation.
- [ ] Implement the approved state rules. Takeoff requires the immediately preceding known ground observation and current known airborne observation inside the zone. Unknown ground breaks that evidence. Disabled notifications still update transitions. Do not expire active aircraft or clear state on failed scans; process an empty batch for elapsed-time cleanup only. With `ignore_ground_aircraft=false`, preserve existing initial/entry ground activity as an overhead-kind event formatted as ON GROUND; with true, suppress that event but retain state. Never generate ground predictions or takeoffs, or establish airborne exit evidence from a ground-only visit.
- [ ] Run all tests so far plus Ruff; expect all pass. Inspect the tracker to confirm no HTTP, sleep, print, or subprocess calls remain.
- [ ] Commit Task 3 files with `fix: make alert transitions observation driven`.

## Task 4: Best-Effort Enrichment with Independent Cache Lifetimes

**Files:** Create `src/aerowatch/metadata.py`, `tests/test_metadata.py`, and
`tests/fixtures/{adsbdb_route,adsbdb_aircraft,hexdb_aircraft}.json`.

**Interfaces:** Produce `MetadataService(session: requests.Session | None = None,
clock: Callable[[], float] = time.monotonic)` and
`lookup(aircraft: AircraftObservation) -> AircraftMetadata`. Consume live
registration/model/type fields; keep aircraft and callsign route caches separate.

- [ ] Write failing tests for feeder-field precedence, sparse registry responses, requests/JSON/schema failures, aircraft expiry at 3,600 seconds, route/failure expiry at 300 seconds, unused-entry eviction, changed callsigns, no callsign, no duplicate request on a negative-cache hit, and bypassing fallbacks after sufficient metadata is known.

```python
assert sparse_result.registration == 'VT-TEST'
assert sparse_result.model == 'Known model'
assert first_flight.route == 'HYD → BLR' and new_callsign.route is None
assert failed_lookup_preserves_live_fields.registration == 'VT-TEST'
```

- [ ] Run `.venv/bin/python -m pytest tests/test_metadata.py -q`; confirm failures from the missing service.
- [ ] Implement adsbdb callsign lookup and hexdb/adsbdb aircraft lookup with `(2.5, 2.5)` timeouts, safe logs, defensive parsing, and nonempty-field merges. Cache by normalized ICAO and callsign. Required aircraft fields for stopping fallbacks are registration, model, type code, and operator. Live complete aircraft identity must not trigger registry calls. Do not use OpenSky historical flight or airport-distance fields for routes.
- [ ] Run all tests so far plus Ruff; expect all pass. Confirm metadata failures return usable partial values rather than escaping into the CLI.
- [ ] Commit Task 4 files with `fix: preserve aircraft metadata and expire route caches`.

## Task 5: Notification Delivery, CLI, and Finite Offline Demo

**Files:** Create `src/aerowatch/{notifications,cli,__main__}.py`,
`src/aerowatch/data/demo.json`, `tests/test_notifications.py`,
`tests/test_cli.py`, and `tests/test_integration.py`. Modify `aero_watch.py`.
Remove `auth_manager.py`, `config_manager.py`, `flight_service.py`,
`flight_tracker.py`, and `notification_manager.py` after replacement checks pass.

**Interfaces:** Produce `format_notification(event: AlertEvent, location:
Location, metadata: AircraftMetadata, radar_base_url: str) -> Notification`;
`NotificationManager(settings: NotificationSettings, runner: Callable =
subprocess.run, platform: str = sys.platform)` with
`send(notification: Notification) -> None`; and
`main(argv: Sequence[str] | None = None) -> int`. All launchers return main's code.

- [ ] Write failing formatter and delivery tests for units, missing fields, event labels including ON GROUND, radar URLs, sound/disabled settings, native versus console platform behavior, executable absence, terminal-notifier failure, AppleScript escaping of quotes/backslashes/newlines, subprocess timeout, and disabled automatic URL opening. Native commands use argument arrays, `shell=False`, and a 5-second process timeout.
- [ ] Write CLI tests for all flags, three launch methods, config errors, missing/unknown locations, no-network help/list/demo, demo default HAL and rejection of other locations, healthy/failed `--once` exit codes, Ctrl+C during fetching and sleeping, and continuous outage recovery. Test metadata requests are made only for aircraft producing alerts and an enrichment failure still reaches the notifier.
- [ ] Create a deterministic integration scenario: incoming → inside → outside, then a different aircraft ground → airborne → outside. Assert event kinds `['incoming', 'departed', 'takeoff', 'departed']`, one event per transition, readable formatted output, and no real requests/subprocesses.
- [ ] Run the three Task 5 test files; confirm expected failures before writing implementation.
- [ ] Implement formatting, delivery fallbacks, polling, and synthetic demo playback. Load the bundled demo with package resources and fixed monotonic offsets without sleeping. Emit console output regardless of desktop availability. For a custom `hal_area` config, use the bundled HAL bounds for demo playback and label that choice in output. Do not authenticate or enrich over HTTP in demo mode.
- [ ] Replace the root launcher with a thin import of `aerowatch.cli.main`. Support a checkout installed via requirements by adding only the adjacent `src` directory when the package is unavailable; avoid interpreter switching or broad import-error masking. Verify the old root imports have no remaining consumers before removal.
- [ ] Run the entire suite and Ruff. Run `.venv/bin/python aero_watch.py --list-locations`, `.venv/bin/python -m aerowatch --demo`, and `.venv/bin/aero-watch --demo`; expect exit 0 and identical finite demo events. Default demo must show no desktop notification.
- [ ] Commit Task 5 files with `feat: add portable CLI and reproducible offline demo`.

## Task 6: Portfolio Documentation, CI, and Installed-Artifact Verification

**Files:** Rewrite `README.md`; create `CONTRIBUTING.md`,
`docs/architecture.md`, `.github/workflows/ci.yml`, and
`scripts/verify_install.py`. Preserve `LICENSE` attribution unchanged.

**Interfaces:** `scripts/verify_install.py` accepts one wheel path, creates a
temporary virtual environment, installs that wheel, and runs CLI help, listing,
and module/console demos from a directory outside the checkout. Exit 0 only when
commands succeed and demo output contains all four expected events. Installation
may download dependencies; application smoke commands remain offline.

- [ ] Document exact installation and compatibility commands, offline demo, live single/continuous scans, all settings/flags, provider failover change, source attribution/terms links, prediction and route limitations, macOS permissions/click limitations, tests, and contributor workflow. Include a compact architecture diagram and synthetic output clearly labeled as such; avoid inflated readiness claims.
- [ ] Add CI on Python 3.11 and 3.14: install `.[dev]`, run Ruff lint/format, pytest, `python -m build`, then the external-wheel smoke script. CI must use fixtures, not live provider checks. Implement the smoke script with bounded subprocess calls and temporary-directory cleanup.
- [ ] Run `.venv/bin/python -m ruff check .`, `.venv/bin/python -m ruff format --check .`, `.venv/bin/python -m pytest -q`, and `.venv/bin/python -m build`; expect zero errors/failures and both wheel/sdist artifacts.
- [ ] Run `.venv/bin/python scripts/verify_install.py <built-wheel>`; expect exit 0, working entry points, packaged defaults, and all demo events outside the repo. Validate README commands against that fresh install.
- [ ] Run one opt-in live `--once --no-notifications` smoke check with public telemetry and bounded timeouts; report provider results separately. Verify native macOS command behavior with mocks. If a visible notification/click check cannot be observed, explicitly leave native desktop delivery unverified instead of claiming end-to-end readiness.
- [ ] Review the complete diff against the spec, check `git diff --check`, and confirm no secrets, generated build artifacts, caches, or unrelated files are staged. Resolve discrepancies, rerunning only affected checks. Commit Task 6 files with `docs: prepare portfolio presentation and automated verification`.

## Execution and Final Report

Execute in the numbered order: provider, state, enrichment, and CLI tasks depend
on Task 1's types; CLI integration depends on all preceding behavior. Native
execution is recommended because this is one small, closely connected Python
application. Keep all user edits intact and use the worktree skill to determine
whether isolation is needed before implementation starts.

Report what changed, exact check results, live-provider status, and any unverified
native notification behavior. No deployment, external publishing, push, or merge
is part of this plan. The plan awaits user review and an execution-method choice.
