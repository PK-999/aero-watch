# Aero Watch ✈️

**Like birdwatching, but for planes.** A Python CLI that watches a local airspace,
projects incoming aircraft trajectories, and sends optional macOS notifications
so you know when to look up.

Built on public ADS-B telemetry. This enhanced edition adds predictive warnings,
observed takeoffs and exits, aircraft metadata, and clickable radar links. It now
ships as a small Python package with an offline demo, automated tests, and CI.

Originally created by [Pankaj Tanwar](https://github.com/Pankajtanwarbanna/aero-watch),
looking out over HAL Airport in Bengaluru. Enhanced and maintained by
[Puneeth Kakarla](https://github.com/PK-999). Both authors are credited in the
[MIT license](LICENSE).

## Try it in two minutes

Requires **Python 3.11+**. Console output works on macOS, Linux, and Windows;
desktop notifications are supported on macOS.

```bash
git clone https://github.com/PK-999/aero-watch.git
cd aero-watch
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
aero-watch --demo
```

On Windows, activate with `.venv\Scripts\activate` instead. The demo runs offline,
finishes automatically, and shows synthetic incoming, takeoff, and exit events.
It does not send desktop notifications. Its coordinates and tracking settings
are bundled defaults, so changes to your live configuration do not hide events.

Example demo output (synthetic):

```text
INCOMING (~32s ETA): VT-DEMO
HAL Area (demo)
Entering from West boundary • Heading E
Aircraft: Synthetic aircraft
Altitude: 1,000 m (3,281 ft)
Speed: 360 km/h (194 kts)
Heading: 90° E
Radar: https://globe.adsbexchange.com/?icao=abc123
```

## Watch live aircraft

```bash
aero-watch --list-locations
aero-watch hal_area --once --no-notifications
aero-watch hal_area
```

| Preset | Airspace |
| --- | --- |
| `hal_area` | HAL Airport and nearby East Bengaluru |
| `blr_airport` | Kempegowda International Airport |
| `entire_blr` | Bengaluru metropolitan area |

Other supported launch methods:

```bash
python -m aerowatch hal_area
python aero_watch.py hal_area
```

For the original script workflow, install `python -m pip install -r requirements.txt`
and run `python aero_watch.py ...` from the checkout. The installed console and
module commands require package installation.

| Option | Behavior |
| --- | --- |
| `--list-locations` | List presets without a network request |
| `--config-dir PATH` | Use settings.json and locations.json from PATH |
| `--once` | Process one live scan and exit |
| `--demo` | Run the finite offline HAL scenario; optional location is `hal_area` only |
| `--no-notifications` | Keep alerts in the console |
| `--verbose` | Include debug diagnostics |

Press Ctrl+C to stop. Exit codes are 0 for success or Ctrl+C, 2 for invalid
arguments/configuration, and 1 when every provider fails in `--once` mode.
Continuous tracking reports an outage and tries again after the polling pause.

## What triggers an alert?

- **INCOMING:** an airborne aircraft projects into the target box within your
  configured warning lead time. One warning per approach.
- **OVERHEAD:** an aircraft is first seen inside, or enters without a prior
  incoming warning. A warned visit suppresses the redundant overhead alert.
- **TAKEOFF:** consecutive observations show ground → air inside the zone.
  An initially climbing aircraft alone does not establish a takeoff.
- **DEPARTED:** an aircraft observed airborne inside is subsequently observed
  outside. Speed and heading do not decide whether it exited.

With ground notifications enabled, initial/entry ground activity appears as
**ON GROUND**. Ignoring ground activity still retains observations for takeoffs.
Missing aircraft do not produce an exit alert. A later visit can generate new
alerts; stale state expires after ten minutes.

## Configuration

Configuration precedence is `--config-dir`, then `./config` when present, then
packaged defaults. A selected directory must contain both JSON files. Invalid
values fail early with an actionable error. Checkout files are editable; package
resources let installed commands run from any directory.

Tracking settings in [config/settings.json](config/settings.json):

| Setting | Default | Meaning |
| --- | --- | --- |
| `poll_interval` | `10` | Pause in seconds after each scan is processed |
| `predictive_warning` | `true` | Enable projected-entry warnings |
| `warning_lead_time_seconds` | `60` | Warn when ETA is positive and no greater than this value |
| `surveillance_buffer_degrees` | `0.15` | Expand the fetch box around the target zone |
| `ignore_ground_aircraft` | `false` | Suppress ground activity alerts while retaining transition history |
| `notify_on_entry` | `true` | Enable overhead/ground entry activity |
| `notify_on_departure` | `true` | Enable both takeoff and exit alerts |
| `token_buffer_seconds` | `60` | Refresh optional OpenSky tokens before expiry |

Notification settings are `enabled`, `sound`, and `auto_open_url` (default
`false`). The legacy `timeout` setting is accepted for configuration compatibility;
macOS controls banner duration, and desktop subprocess waits are bounded.
`adsb_exchange.base_url` controls the radar link. Optional `opensky.base_url` and
`opensky.auth_url` retain telemetry fallback configuration.

Add custom areas to [config/locations.json](config/locations.json):

```json
{
  "my_area": {
    "name": "My viewing spot",
    "lamin": 12.91,
    "lamax": 13.00,
    "lomin": 77.62,
    "lomax": 77.72
  }
}
```

Coordinates must describe a nonzero box within valid latitude/longitude ranges.
Reversed bounds are normalized; antimeridian-spanning areas are unsupported.

## macOS notifications

Install the optional notifier for click-to-open radar links:

```bash
brew install terminal-notifier
```

Enable terminal-notifier in **System Settings → Notifications** and check Focus
settings if alerts do not appear. The app prefers terminal-notifier and falls
back to AppleScript through System Events. The fallback cannot open the radar on
click; it prints the radar URL instead. `auto_open_url=true` opens the URL
immediately when using that fallback. Notification failures keep console alerts
working. Banner duration and visibility depend on macOS notification settings.
See the [terminal-notifier documentation](https://github.com/julienXX/terminal-notifier).

## Data sources and limits

Telemetry uses ordered failover: [adsb.lol](https://www.adsb.lol/),
[adsb.fi](https://adsb.fi/), then [OpenSky Network](https://opensky-network.org/).
A healthy empty scan ends the search. This replaces the earlier version's
three-feed merging, so coverage can differ. Explicit positions older than 60
seconds are skipped. Failures and rate limits are reported separately from empty
skies; provider-specific cooldowns honor Retry-After.

Aircraft identity comes from live feeder fields and best-effort
[hexdb](https://hexdb.io/) / [adsbdb](https://www.adsbdb.com/) lookups. Routes are
cached callsign associations from adsbdb and may be missing or inaccurate. The
[OpenSky historical flights endpoint](https://openskynetwork.github.io/opensky-api/rest.html)
is not used to infer current routes. Optional OpenSky credentials use
`OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET` environment variables; no keys are
needed for the default community telemetry providers.

Public data depends on receiver coverage, freshness, and provider availability.
Warnings assume a straight-line trajectory, so turns can change the ETA. Network
and optional enrichment time add latency; the polling pause is not a guaranteed
alert cadence. This is a hobby aircraft-spotting tool and has no operational
aviation role. Follow each provider's usage terms, including the
[adsb.fi personal/noncommercial terms and request limits](https://github.com/adsbfi/opendata).

## Development and verification

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m build
python scripts/verify_install.py dist/*.whl
```

Tests use synthetic provider fixtures and blocked live HTTP. CI checks Python
3.11 and 3.14, lint/format, tests, and package builds. The install verifier creates
a fresh virtual environment, downloads the wheel's dependencies, and runs help,
location listing, and both demo entry points outside the repo with networking
blocked during those application commands. A successful mock notification test
does not prove desktop visibility or radar clicks; those need a macOS smoke check.

Read [the architecture](docs/architecture.md) for module boundaries and data flow,
and [the contributing guide](CONTRIBUTING.md) for the development workflow.

See the [verification record](docs/verification.md) for checks performed locally
and the native desktop check still outstanding.
