# Aero Watch ✈️

> **Like birdwatching, but for planes.** 🛬

Originally created by [Pankaj Tanwar](https://twitter.com/the2ndfloorguy) while sitting at [InMobi](https://www.inmobi.com/) next to a window with a view of HAL Airport in Bengaluru ([check out the original viral Twitter post](https://x.com/the2ndfloorguy/status/1945750355096310213) and [original repo](https://github.com/Pankajtanwarbanna/aero-watch)).

This enhanced edition is maintained by [Puneeth Kakarla](https://github.com/PK-999) from his desk at Quantiphi Analytics, in [Trifecta Addatto, Bengaluru](https://maps.app.goo.gl/d3s718Q8Vz1y8P8c6), overlooking the same HAL Airport and East Bengaluru flight corridors.

Flight data is publicly broadcasted through ADS-B signals and visible live on platforms like [ADS-B Exchange](https://globe.adsbexchange.com). Aero Watch monitors the skies over your airspace and sends real-time macOS notifications: *"Hey, look up!"* with complete flight dynamics, aircraft details, and routes.

---

## 🚀 Key Improvements & Changes from the Original

This fork significantly enhances the original implementation with predictive tracking, departure handling, rich aircraft intelligence, and macOS fixes:

| Feature | Original Implementation | Enhanced Edition (This Version) | Rationale / Benefit |
| :--- | :--- | :--- | :--- |
| **Predictive Early Warning** | None (notified only after plane entered bounding box) | **Trajectory Projection (~60s ETA heads-up)** | Uses 2D ray-box intersection (Liang-Barsky) with speed & heading vectors to alert you ~1 min *before* arrival, giving you time to look out the window. |
| **Takeoff & Departure Detection** | None (ground/parked planes remained silent or ignored) | **`🛫 TAKEOFF` & `🛫 DEPARTED` alerts** | Monitors ground-to-air transitions, initial climb-outs, and airspace departures so flights taking off from HAL or Kempegowda are notified. |
| **Aircraft & Operator Metadata** | Basic callsign only | **Multi-Source Enrichment (No API keys needed)** | Resolves full aircraft models (e.g. *Cessna Citation CJ2*, *Bombardier Global 6500*), registrations, corporate owners (*Hindalco Industries*), and commercial airlines (*IndiGo*). |
| **Commercial Flight Routes** | OpenSky OAuth required (401 error if unconfigured) | **Free Multi-Feeder Routing** | Queries public aviation databases (`adsbdb`, `adsb.fi`, `adsb.lol`, `hexdb.io`) to provide city routes (e.g. `HYD → CJB`) with zero authentication needed. |
| **macOS Notification UX** | Clicking notification opened empty **Script Editor** | **Fixed via `System Events` & Click-to-Open** | Routed AppleScript through `System Events` to stop Script Editor from opening. Supports `terminal-notifier` for direct radar link clicks. |
| **BLR Airport Geofencing** | Pointed incorrectly to HAL Airport coordinates | **Accurate Kempegowda International Airport** | Corrected `blr_airport` in `locations.json` to real Kempegowda coordinates (`13.16–13.24° N`, `77.66–77.76° E`). |
| **Flight Dynamics** | Raw altitude in meters only | **Dual Units & Climb/Descent Indicators** | Displays altitude in both meters and feet, vertical rate (`↗ Climbing`, `↘ Descending`, `Level`), speed (`km/h` & `kts`), and compass heading (`111° ESE`). |
| **Environment Auto-Switch** | Required manual virtualenv activation | **Automatic `.venv` Detection** | Auto-detects local `.venv` and seamlessly switches interpreters if dependencies are missing. |

---

## 🔔 Notification Previews

### 1. Predictive Early Warning (~1 min before arrival)
```text
⚠️ INCOMING (~58s ETA): VT-NJB • C25A
Entering from West boundary (Heading East, 92°) • Hindalco Industries Ltd

⏱ ETA: ~58s to HAL Area
🧭 Entering from West boundary (Heading East, 92°)
✈️ Aircraft: CESSNA 525A Citation CJ2 [C25A]
📊 Altitude: 2,743 m (8,999 ft) • ↘ Descending (-1,568 fpm)
🚀 Speed: 412 km/h (222 kts) • Heading: 92° E
Click notification to open live radar
```

### 2. Takeoff & Climb-Out Alert
```text
🛫 TAKEOFF: VT-AVS • E50P
Departing from HAL Area • Aviators (India) P/L

Status: 🛫 Airborne & Climbing out
Aircraft: EMBRAER EMB-500 Phenom 100
Altitude: 450 m (1,476 ft) • ↗ Climbing (+1,673 fpm)
Speed: 270 km/h (145 kts) • Heading: 92° E
Click notification to open live radar
```

### 3. Airspace Departure
```text
🛫 DEPARTED: VT-AVS • E50P
Exited HAL Area (Heading East) • Aviators (India) P/L

Status: Departed HAL Area (Heading East)
Aircraft: EMBRAER EMB-500 Phenom 100
Altitude: 1,200 m (3,937 ft) • ↗ Climbing (+1,181 fpm)
Speed: 396 km/h (214 kts) • Heading: 90° E
```

---

## 🛠 Usage

Start tracking your local airspace:

```bash
# Track HAL Airport & East Bengaluru (Whitefield, Mahadevapura, Trifecta Addatto)
python3 aero_watch.py hal_area

# Track Kempegowda International Airport (BLR) commercial traffic
python3 aero_watch.py blr_airport

# Monitor the entire Bangalore metropolitan airspace
python3 aero_watch.py entire_blr
```

List all available tracking zones:
```bash
python3 aero_watch.py --list-locations
```

---

## ⚙️ Configuration

### `config/settings.json`
```json
{
    "tracking": {
        "poll_interval": 10,
        "token_buffer_seconds": 60,
        "ignore_ground_aircraft": false,
        "predictive_warning": true,
        "warning_lead_time_seconds": 60,
        "surveillance_buffer_degrees": 0.15,
        "notify_on_entry": true,
        "notify_on_departure": true
    },
    "notifications": {
        "enabled": true,
        "sound": true,
        "timeout": 30,
        "auto_open_url": false
    },
    "adsb_exchange": {
        "base_url": "https://globe.adsbexchange.com"
    }
}
```

- `predictive_warning`: Enables trajectory calculation and alerts ~60s before entry.
- `notify_on_departure`: Notifies when an aircraft takes off or departs the airspace.
- `ignore_ground_aircraft`: Set to `true` if you only want airborne flights and want to ignore stationary parked planes.
- `surveillance_buffer_degrees`: Buffer margin around the target box used for predictive trajectory analysis (~0.15° ≈ 16 km).

### `config/locations.json`
Define any custom tracking area with bounding latitude/longitude coordinates:
```json
{
    "blr_airport": {
        "name": "BLR Airport (Kempegowda)",
        "lamin": 13.1600,
        "lamax": 13.2400,
        "lomin": 77.6600,
        "lomax": 77.7600
    },
    "hal_area": {
        "name": "HAL Area",
        "lamin": 12.9100,
        "lamax": 13.0000,
        "lomin": 77.6200,
        "lomax": 77.7200
    },
    "entire_blr": {
        "name": "Entire Bangalore",
        "lamin": 12.2939,
        "lamax": 13.4076,
        "lomin": 76.7293,
        "lomax": 78.2313
    }
}
```

---

## 📦 Setup & Requirements

1. **Python Dependencies**:
   ```bash
   pip3 install -r requirements.txt
   ```
2. **Clickable macOS Notifications (Recommended)**:
   ```bash
   brew install terminal-notifier
   ```
   *Tip: In ** System Settings > Notifications > terminal-notifier**, ensure **Allow Notifications** is enabled so notifications can open the live ADS-B radar view in your browser when clicked.*

---

## 📁 Project Structure

```text
aero-watch/
├── config/
│   ├── locations.json         # Airspace geographic boundaries
│   └── settings.json          # Polling, predictive, and alert settings
├── aero_watch.py             # CLI entrypoint with auto-venv switcher
├── flight_tracker.py         # Trajectory prediction, takeoff/exit & tracking logic
├── flight_service.py         # Multi-feeder ADS-B & aircraft metadata integration
├── auth_manager.py           # OpenSky authentication (with env var fallback)
├── notification_manager.py    # macOS System Events & terminal-notifier handler
├── config_manager.py         # Configuration loader
├── requirements.txt          # Python dependencies
├── LICENSE                   # MIT License
└── README.md
```

---

## ❤️ Credits & Attribution

- **Original Creator & Concept**: [Pankaj Tanwar](https://twitter.com/the2ndfloorguy) ([Pankaj's Twitter](https://twitter.com/the2ndfloorguy), [Original Repository](https://github.com/Pankajtanwarbanna/aero-watch), [Side Hustles](https://pankajtanwar.in/side-hustles)).
- **Enhanced Edition & Predictive Engine**: [Puneeth Kakarla](https://github.com/PK-999) (Quantiphi Analytics, Bengaluru).
