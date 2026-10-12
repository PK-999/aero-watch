# Aero Watch portfolio refactor

## Purpose and agreed scope

Make this existing desktop flight tracker easy to clone, run, test, and explain
in a portfolio. Preserve its identity, original attribution, existing location
presets, and `python aero_watch.py <location>` launch command. Refactor the Python
application and correct demonstrated tracking bugs without adding a web UI,
database, deployment service, or background daemon.

The user approved this scope on 12 October 2026. This document is the concrete
design for review before the implementation plan.

## Baseline evidence

- The working tree was clean at commit `6fa47dc` on `main`.
- The CLI help and location listing succeeded with Python 3.14.6.
- Read-only live requests returned HTTP 200 from adsb.lol (15 aircraft),
  adsb.fi (5 aircraft), and OpenSky (2 aircraft). Counts are observations,
  not guarantees of coverage or availability.
- Test discovery found zero tests. There is no CI or package configuration.
- Simulated observations reproduced ignored warning timing, takeoff alerts when
  departure alerts were disabled, and missed exits when an outside aircraft
  headed back toward the box.
- An initial climbing sighting was classified as takeoff without an observed
  ground-to-air transition. Filtering ground aircraft removed the observations
  needed to detect that transition.
- All provider failures returned the same empty list as a successful empty scan.
  Sparse enrichment responses replaced known metadata with missing values.
- Native macOS notification display and click behavior have not been verified.

## Architecture

Use a `src/aerowatch/` package. The name avoids an import collision with the
existing `aero_watch.py` launcher. Keep the application synchronous and its only
runtime third-party dependency as `requests`. Require Python 3.11 or newer.

| Module | Responsibility |
| --- | --- |
| `models.py` | Typed aircraft observations, bounds, predictions, and alert events |
| `config.py` | Load defaults or user JSON; validate settings and geographic bounds |
| `providers.py` | HTTP transport, provider adapters, telemetry normalization, fallback |
| `metadata.py` | Best-effort aircraft and callsign enrichment with expiring caches |
| `prediction.py` | Pure local trajectory projection and compass/unit helpers |
| `tracker.py` | Observation-driven alert state machine and stale-state cleanup |
| `notifications.py` | Event presentation, console output, macOS delivery |
| `cli.py`, `__main__.py` | Arguments, polling orchestration, shutdown, exit codes |
| `data/` | Packaged default settings, locations, and synthetic demo observations |

The tracker receives normalized observations and an explicit timestamp and
returns events. It performs no HTTP calls, sleeps, or notification subprocesses.
The CLI fetches observations, feeds the tracker, enriches aircraft that actually
produce events, formats each event, and sends it through the selected notifier.
Inject the HTTP session and subprocess runner so tests cannot accidentally call
the internet or show desktop notifications.

Retire the old root implementation modules after migration. Preserve the root
launcher as a small compatibility entry point. Keep the existing `config/`
files as editable checkout configuration; ship equivalent defaults as package
resources so a wheel works outside the checkout.

## Telemetry and provider behavior

- Represent aircraft using named fields in SI units, not indexed lists.
  Missing speed, heading, altitude, and ground status remain unknown. Never
  substitute a zero heading or stationary speed for missing data.
- Validate finite coordinates and numeric telemetry. Skip an invalid aircraft
  record while continuing to process other valid records in the same response.
- Reject explicitly reported position ages above 60 seconds. Do not invent
  timestamps when a provider supplies no freshness information.
- Query providers in order: adsb.lol, adsb.fi, then OpenSky. This is deliberate
  failover rather than querying and merging all three every poll. A valid empty
  response is successful and ends the search. Document this behavior change.
- Use the documented adsb.fi v3 area endpoint and normalize its `ac` schema.
  Retain OpenSky as an optional credential-aware telemetry fallback.
- Use finite connect/read timeouts of 3.5 seconds each, no automatic retry burst,
  and a descriptive Aero Watch User-Agent. A failed adapter advances to the next
  provider and records its reason. Respect HTTP 429 `Retry-After`; if absent or
  invalid, wait at least 60 seconds before querying that provider again.
- Return a scan result that distinguishes healthy empty data, successful
  fallback, and total failure. Report provider failures through logging without
  exposing authorization headers or secrets. An outage does not create exits.

## Tracking rules

- Bounds are inclusive. An entry or exit depends on observed position,
  independently of the predicted trajectory, speed, or heading.
- Warn for a valid airborne incoming observation when
  `0 < ETA <= warning_lead_time_seconds`. Honor `predictive_warning` and the
  configured lead time. Retain the existing straight-line approximation and
  document that turning aircraft can invalidate the prediction.
- Notify on an initial airborne sighting inside the zone or an observed
  outside-to-inside transition when `notify_on_entry` is enabled. If the current
  visit already generated an incoming warning, suppress the redundant overhead
  notification, preserving the existing user-facing behavior.
- Takeoff requires an observed ground-to-air transition with both positions
  inside the target zone. A first climbing observation alone is not takeoff.
  Takeoff takes priority over an overhead event in the same observation.
- `notify_on_departure` controls both takeoff and exit notifications. Emit exit
  when a previously inside airborne aircraft is observed outside, even when its
  new heading points toward the zone or its speed/heading is unknown.
- Ground observations update state even with `ignore_ground_aircraft=true`;
  that option suppresses ground activity notifications. Unknown ground status
  must not establish takeoff. Ground records do not generate incoming warnings.
- Emit each event once per visit. Clear visit flags after a confirmed exit.
  Cancel an outstanding approach warning when an outside aircraft no longer
  projects into the zone, allowing a later new approach to warn again.
- Missing aircraft and failed polls are not proof of departure. Expire state
  after 600 seconds without a valid observation using a monotonic clock.

## Metadata and routes

Enrichment is optional and cannot prevent an alert from being delivered. Prefer
known live feeder fields; fill only missing values with registry results. Use
adsbdb for callsign routes and hexdb/adsbdb for aircraft details. Retain existing
useful metadata when an endpoint returns a sparse or unsuccessful response.

Cache aircraft metadata for 3,600 seconds and callsign routes for 300 seconds;
cache failed lookups for 300 seconds. Route keys include the callsign so the same
aircraft on a new flight cannot reuse an old route. Limit each metadata request
to 2.5 seconds for connect and read; stop aircraft fallbacks once the required
fields are known. Evict aircraft cache entries unused for 3,600 seconds.

Remove the historical OpenSky flights lookup from live route enrichment. Airport
distance fields must never be displayed as airport identifiers. Show unavailable
metadata honestly, and describe routes as best-effort callsign associations.

## CLI, configuration, and notification behavior

Support `aero-watch`, `python -m aerowatch`, and the existing root launcher.
Keep positional location and `--list-locations`; add `--config-dir`, `--once`,
`--demo`, `--no-notifications`, and `--verbose`. Help and location listing must
not make network requests. The demo uses synthetic observations, has finite
execution, and defaults to console output without network access.
When `--demo` is used without a location, select `hal_area`; reject other demo
locations with a clear error because the bundled scenario uses HAL coordinates.
`--once` affects live tracking only; the demo always plays its complete scenario.

Configuration precedence is explicit `--config-dir`, then `./config` if present,
then packaged defaults. A selected directory must contain both JSON files.
Reject malformed JSON, missing required fields, nonfinite bounds, out-of-range
coordinates, nonpositive polling/lead intervals, and negative buffers with a
short actionable CLI error. Normalize reversed bounds; reject zero-area boxes
and boxes crossing the antimeridian. Clamp surveillance expansion to valid
coordinate limits. Keep optional OpenSky credentials in environment variables;
continue accepting existing placeholder configuration without authentication.

Console output works on macOS, Linux, and Windows. Desktop delivery is macOS
only: prefer terminal-notifier, with AppleScript fallback. Use argument lists,
correct string escaping, and subprocess timeouts. A failed notifier logs a
warning and does not stop tracking. State clearly when fallback notifications
cannot provide click-to-open radar links. Preserve optional sound and automatic
URL opening, with automatic URL opening disabled by default.

Exit codes: 0 for successful commands, completed demos, and Ctrl+C; 2 for CLI or
configuration errors; 1 for a total provider failure with `--once`. Continuous
tracking reports an outage and tries again after the configured poll interval.
Deliver cached/unenriched alert information even when metadata cannot be fetched.

## Repository presentation and verification

Add `pyproject.toml` with the installed CLI, package data, runtime requirement
`requests>=2.32,<3`, and development tools pytest, Ruff, and build. Keep
`requirements.txt` as a documented compatibility installation path. Replace
the generic ignore file with concise entries relevant to this Python project.

Rewrite the README to lead with the problem and a reproducible demo. Include
setup, live usage, configuration, notification setup, architecture/data flow,
testing, and data-source limitations. Preserve both authors and MIT attribution.
Add a concise contributing guide and provider links/credits. Avoid unverified
claims of production readiness, route completeness, or guaranteed warning times.

Add GitHub Actions checks on Python 3.11 and 3.14 for lint, formatting, tests,
and package build. Tests use provider fixtures and mocked subprocesses. Cover
geometry, units, malformed/missing telemetry, alert settings, takeoff, exits,
repeated passes, stale state, metadata retention/expiry, failover, rate limits,
configuration, CLI exit codes, and native notification command construction.

Verification must also install the built wheel in a fresh environment and run
help, location listing, and the complete offline demo from outside the repo.
Exercise the provider-to-event-to-notifier flow with deterministic fixtures.
Keep live API probes opt-in and report their actual results separately from CI.
Desktop delivery and radar-click behavior require a macOS smoke check before
claiming native end-to-end readiness; if unavailable, state that limitation.

## Acceptance criteria

The refactor is ready when the original launch command works; installation and
the offline demo work outside the checkout; all listed behavioral regressions
have meaningful tests; lint, tests, and builds pass; and documentation matches
the verified behavior. The final report must distinguish completed local checks,
live provider observations, and any native notification checks still unverified.

## Provider references checked during assessment

- [adsb.fi API and usage limits](https://github.com/adsbfi/opendata/blob/main/README.md)
- [adsb.lol API](https://api.adsb.lol/docs)
- [OpenSky REST API and historical flight behavior](https://openskynetwork.github.io/opensky-api/rest.html)
