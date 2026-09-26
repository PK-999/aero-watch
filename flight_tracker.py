"""
Aero Watch - Core Flight Tracker Engine
Originally created by Pankaj Tanwar (https://github.com/Pankajtanwarbanna/aero-watch)
Enhanced by Puneeth Kakarla (https://github.com/PK-999/aero-watch):
- Predictive trajectory entry calculation (Liang-Barsky 2D ray-box projection)
- Takeoff and climb-out detection
- Airspace departure tracking
"""
import time
import math
from flight_service import FlightService
from notification_manager import NotificationManager
from config_manager import Config

class FlightTracker:
    def __init__(self, location_key):
        self.config = Config()
        self.location_config = self.config.get_location(location_key)
        
        if not self.location_config:
            raise ValueError(f"Location '{location_key}' not found in configuration")
        
        self.flight_service = FlightService()
        self.notification_manager = NotificationManager()
        self.tracking_config = self.config.get_tracking_config()
        self.aircraft_cache = {}
        self.aircraft_states = {}
        
        # Normalize designated airspace boundaries (min/max safety)
        self.target_lamin = min(float(self.location_config["lamin"]), float(self.location_config["lamax"]))
        self.target_lamax = max(float(self.location_config["lamin"]), float(self.location_config["lamax"]))
        self.target_lomin = min(float(self.location_config["lomin"]), float(self.location_config["lomax"]))
        self.target_lomax = max(float(self.location_config["lomin"]), float(self.location_config["lomax"]))
        
        # Surveillance buffer: extend search area so we detect incoming aircraft ~1-2 min before entry
        buffer_deg = float(self.tracking_config.get("surveillance_buffer_degrees", 0.15))
        self.surveillance_params = {
            "lamin": self.target_lamin - buffer_deg,
            "lamax": self.target_lamax + buffer_deg,
            "lomin": self.target_lomin - buffer_deg,
            "lomax": self.target_lomax + buffer_deg
        }
        
        self.location_name = self.location_config.get("name", location_key)
        self.predictive_enabled = self.tracking_config.get("predictive_warning", True)
        self.warning_lead_time = float(self.tracking_config.get("warning_lead_time_seconds", 60))
        self.notify_on_entry = self.tracking_config.get("notify_on_entry", True)
        self.notify_on_departure = self.tracking_config.get("notify_on_departure", True)
        
    def predict_airspace_entry(self, lat, lon, track_deg, speed_ms):
        """
        Uses 2D ray-box intersection to project flight path and determine:
        1. If and when (ETA in seconds) the aircraft will enter the target airspace.
        2. The exact direction of entry (boundary edge and flight heading).
        """
        # Check if already inside the target airspace
        if self.target_lamin <= lat <= self.target_lamax and self.target_lomin <= lon <= self.target_lomax:
            return "already_inside", 0.0, "Inside Airspace", "Center"
        
        # Stationary or very slow aircraft (< 5 m/s or ~10 kts) won't enter in 1 min
        if speed_ms is None or speed_ms < 5.0 or track_deg is None:
            return "stationary", None, None, None
            
        rad = math.radians(track_deg)
        v_north = speed_ms * math.cos(rad)
        v_east = speed_ms * math.sin(rad)
        
        # Degrees per second conversion at current latitude
        dlat_dt = v_north / 111139.0
        dlon_dt = v_east / (111139.0 * math.cos(math.radians(lat)))
        
        # Liang-Barsky 2D Ray-Box intersection
        t_lat_enter = -float('inf')
        t_lat_exit = float('inf')
        edge_lat = None
        
        if abs(dlat_dt) > 1e-9:
            if dlat_dt > 0:  # Moving Northwards
                t_lat_enter = (self.target_lamin - lat) / dlat_dt
                t_lat_exit = (self.target_lamax - lat) / dlat_dt
                edge_lat = "South"
            else:             # Moving Southwards
                t_lat_enter = (self.target_lamax - lat) / dlat_dt
                t_lat_exit = (self.target_lamin - lat) / dlat_dt
                edge_lat = "North"
        else:
            if lat < self.target_lamin or lat > self.target_lamax:
                return "no_intersection", None, None, None
                
        t_lon_enter = -float('inf')
        t_lon_exit = float('inf')
        edge_lon = None
        
        if abs(dlon_dt) > 1e-9:
            if dlon_dt > 0:  # Moving Eastwards
                t_lon_enter = (self.target_lomin - lon) / dlon_dt
                t_lon_exit = (self.target_lomax - lon) / dlon_dt
                edge_lon = "West"
            else:             # Moving Westwards
                t_lon_enter = (self.target_lomax - lon) / dlon_dt
                t_lon_exit = (self.target_lomin - lon) / dlon_dt
                edge_lon = "East"
        else:
            if lon < self.target_lomin or lon > self.target_lomax:
                return "no_intersection", None, None, None
                
        t_enter = max(t_lat_enter, t_lon_enter)
        t_exit = min(t_lat_exit, t_lon_exit)
        
        if t_enter <= t_exit and t_exit > 0 and t_enter > 0:
            entry_boundary = edge_lat if t_lat_enter > t_lon_enter else edge_lon
            dirs = ["North", "NNE", "NE", "ENE", "East", "ESE", "SE", "SSE",
                    "South", "SSW", "SW", "WSW", "West", "WNW", "NW", "NNW"]
            heading_cardinal = dirs[round(track_deg / 22.5) % 16]
            direction_desc = f"Entering from {entry_boundary} boundary (Heading {heading_cardinal}, {round(track_deg)}°)"
            return "will_enter", t_enter, direction_desc, entry_boundary
            
        return "no_intersection", None, None, None

    def _get_display_name(self, details, raw_callsign, icao24):
        reg = details.get("registration")
        flight_num = details.get("flight_number")
        if flight_num and flight_num != raw_callsign:
            return f"{flight_num} ({raw_callsign})"
        elif reg and raw_callsign and reg.replace("-", "") != raw_callsign:
            return f"{reg} ({raw_callsign})"
        elif reg:
            return reg
        elif raw_callsign:
            return raw_callsign
        return f"Unknown [{icao24.upper()}]"

    def _format_alt(self, baro_alt, geo_alt, on_ground, vrate_ms):
        if on_ground:
            return "Status: On Ground (Surface)"
        
        alt_m = None
        label = ""
        if baro_alt is not None:
            alt_m = int(baro_alt)
        elif geo_alt is not None:
            alt_m = int(geo_alt)
            label = " [Geo]"
            
        if alt_m is not None:
            alt_ft = int(alt_m * 3.28084)
            alt_display = f"Altitude: {alt_m:,} m ({alt_ft:,} ft){label}"
        else:
            alt_display = "Altitude: Unavailable"
            
        vrate_display = ""
        if not on_ground and vrate_ms is not None:
            fpm = int(vrate_ms * 196.85)
            if fpm > 100:
                vrate_display = f" • ↗ Climbing (+{fpm:,} fpm)"
            elif fpm < -100:
                vrate_display = f" • ↘ Descending ({fpm:,} fpm)"
            else:
                vrate_display = " • → Level"
        return f"{alt_display}{vrate_display}"

    def _format_dynamics(self, vel_ms, track_deg):
        items = []
        if vel_ms is not None:
            kmh = int(vel_ms * 3.6)
            kts = int(vel_ms * 1.94384)
            items.append(f"Speed: {kmh} km/h ({kts} kts)")
        if track_deg is not None:
            dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
            cardinal = dirs[round(track_deg / 22.5) % 16]
            items.append(f"Heading: {round(track_deg)}° {cardinal}")
        return " • ".join(items)

    def start_tracking(self):
        print("\n" + "=" * 75)
        print(f"✈️  AERO-WATCH: AIRSPACE SURVEILLANCE & PREDICTIVE EARLY WARNING")
        print("=" * 75)
        print(f"  Target Airspace:       {self.location_name}")
        print(f"  Designated Boundaries: Lat [{self.target_lamin:.4f} to {self.target_lamax:.4f}], Lon [{self.target_lomin:.4f} to {self.target_lomax:.4f}]")
        print(f"  Surveillance Perimeter:Lat [{self.surveillance_params['lamin']:.4f} to {self.surveillance_params['lamax']:.4f}], Lon [{self.surveillance_params['lomin']:.4f} to {self.surveillance_params['lomax']:.4f}]")
        print(f"  Early Warning Window:  ~{int(self.warning_lead_time)} seconds before airspace entry")
        print(f"  Polling Frequency:     Every {self.tracking_config.get('poll_interval', 10)}s")
        print("=" * 75)
        print("Press Ctrl+C to stop\n")
        
        while True:
            try:
                planes = self.flight_service.get_planes_in_area(self.surveillance_params)
                now = time.time()
                
                for plane in planes:
                    icao24 = plane[0].lower()
                    raw_callsign = plane[1].strip() if plane[1] else ""
                    country = plane[2] or "Unknown"
                    plon = plane[5]
                    plat = plane[6]
                    baro_alt = plane[7]
                    on_ground = plane[8] if len(plane) > 8 else False
                    vel_ms = plane[9] if len(plane) > 9 else None
                    track_deg = plane[10] if len(plane) > 10 else None
                    vrate_ms = plane[11] if len(plane) > 11 else None
                    geo_alt = plane[13] if len(plane) > 13 else None
                    squawk = plane[14] if len(plane) > 14 and plane[14] else None
                    
                    if plat is None or plon is None:
                        continue
                        
                    # Skip stationary ground aircraft if configured
                    if on_ground and self.tracking_config.get("ignore_ground_aircraft", False):
                        continue
                        
                    is_on_ground = on_ground or (vel_ms is not None and vel_ms < 15.0 and (baro_alt is None or baro_alt < 100))
                    is_airborne = not on_ground and (baro_alt is None or baro_alt > 50) and (vel_ms is not None and vel_ms > 30.0)
                    is_climbing = vrate_ms is not None and vrate_ms > 0.8
                    inside_target = (self.target_lamin <= plat <= self.target_lamax and self.target_lomin <= plon <= self.target_lomax)
                    
                    # Initialize state tracking for this aircraft
                    if icao24 not in self.aircraft_states:
                        self.aircraft_states[icao24] = {
                            "status": "initial",
                            "was_on_ground": is_on_ground,
                            "was_stationary": (vel_ms is not None and vel_ms < 20.0),
                            "warned_entry": False,
                            "entered_notified": False,
                            "takeoff_notified": False,
                            "departed_notified": False,
                            "pass_count": 0,
                            "last_seen": now
                        }
                    
                    state = self.aircraft_states[icao24]
                    state["last_seen"] = now
                    
                    prev_on_ground = state.get("was_on_ground", False)
                    prev_stationary = state.get("was_stationary", False)
                    
                    # Compute predictive trajectory and time to entry
                    pred_status, eta_seconds, dir_desc, entry_edge = self.predict_airspace_entry(
                        plat, plon, track_deg, vel_ms
                    )
                    
                    # Lazy-load enriched aircraft details
                    if icao24 not in self.aircraft_cache:
                        self.aircraft_cache[icao24] = self.flight_service.get_aircraft_details(icao24, raw_callsign)
                    details = self.aircraft_cache[icao24]
                    
                    display_name = self._get_display_name(details, raw_callsign, icao24)
                    model = details.get("model")
                    type_code = details.get("type_code")
                    operator = details.get("operator") or details.get("airline")
                    route = details.get("route") or self.flight_service.get_route_info(icao24)
                    alt_display = self._format_alt(baro_alt, geo_alt, on_ground, vrate_ms)
                    dyn_display = self._format_dynamics(vel_ms, track_deg)
                    adsb_url = f"{self.config.get_setting('adsb_exchange.base_url')}/?icao={icao24}"
                    title_type = f" • {type_code}" if type_code else ""
                    
                    # -------------------------------------------------------------
                    # DEPARTURE TAKEOFF EVENT (Ground-to-air transition / liftoff)
                    # -------------------------------------------------------------
                    took_off = (
                        (prev_on_ground and not on_ground and is_airborne) or
                        (prev_stationary and is_airborne and (is_climbing or (vel_ms is not None and vel_ms > 40.0)))
                    )
                    fresh_departure = (
                        state["status"] == "initial" and
                        is_airborne and is_climbing and
                        (baro_alt is not None and baro_alt < 3500) and
                        inside_target
                    )
                    
                    if (took_off or fresh_departure) and not state.get("takeoff_notified", False):
                        state["takeoff_notified"] = True
                        state["entered_notified"] = True
                        state["status"] = "departing"
                        state["was_on_ground"] = False
                        
                        title = f"🛫 TAKEOFF: {display_name}{title_type}"
                        subtitle = f"Departing from {self.location_name} • {operator or country}"
                        
                        msg_lines = [
                            f"Status: 🛫 Airborne & Climbing out",
                        ]
                        if model:
                            msg_lines.append(f"Aircraft: {model}")
                        msg_lines.append(alt_display)
                        if dyn_display:
                            msg_lines.append(dyn_display)
                        if route:
                            msg_lines.append(f"Route: {route}")
                        msg_lines.append("Click notification to open live radar")
                        
                        message = "\n".join(msg_lines)
                        
                        print("\n" + "=" * 75)
                        print(f"🛫  TAKEOFF DETECTED: {display_name} is departing {self.location_name}")
                        print("=" * 75)
                        print(f"  Aircraft:        {display_name}")
                        if model:
                            print(f"  Model:           {model} [{type_code or 'Unknown'}]")
                        print(f"  Status:          Airborne & Climbing out")
                        if operator:
                            print(f"  Operator/Line:   {operator}")
                        if route:
                            print(f"  Route:           {route}")
                        print(f"  {alt_display}")
                        if dyn_display:
                            print(f"  {dyn_display}")
                        print(f"  Live Radar:      {adsb_url}")
                        print("=" * 75 + "\n")
                        
                        self.notification_manager.send_notification(title, message, subtitle, url=adsb_url)
                    
                    # Update ground/motion state for next poll
                    state["was_on_ground"] = is_on_ground
                    state["was_stationary"] = (vel_ms is not None and vel_ms < 20.0)
                    
                    # -------------------------------------------------------------
                    # CASE 1: PREDICTIVE EARLY WARNING (~1 min before entering)
                    # -------------------------------------------------------------
                    if self.predictive_enabled and pred_status == "will_enter":
                        if 20.0 <= eta_seconds <= 85.0 and not state["warned_entry"]:
                            state["warned_entry"] = True
                            state["status"] = "approaching"
                            state["pass_count"] += 1
                            
                            eta_round = round(eta_seconds)
                            lap_tag = f" (Pass #{state['pass_count']})" if state["pass_count"] > 1 else ""
                            title = f"⚠️ INCOMING (~{eta_round}s ETA){lap_tag}: {display_name}"
                            subtitle = f"{dir_desc} • {operator or country}"
                            
                            msg_lines = [
                                f"⏱ ETA: ~{eta_round}s to {self.location_name}",
                                f"🧭 {dir_desc}",
                            ]
                            if model:
                                msg_lines.append(f"✈️ Aircraft: {model} [{type_code or 'Unknown'}]")
                            msg_lines.append(f"📊 {alt_display}")
                            if dyn_display:
                                msg_lines.append(f"🚀 {dyn_display}")
                            if route:
                                msg_lines.append(f"🗺 Route: {route}")
                            msg_lines.append("Click notification to open live radar")
                            
                            message = "\n".join(msg_lines)
                            
                            print("\n" + "=" * 75)
                            print(f"⚠️  PREDICTIVE EARLY WARNING: ~1 MIN TO AIRSPACE ENTRY{lap_tag.upper()}")
                            print("=" * 75)
                            print(f"  Target Airspace: {self.location_name}")
                            print(f"  Aircraft:        {display_name}")
                            if model:
                                print(f"  Model:           {model} [{type_code or 'Unknown'}]")
                            print(f"  Estimated ETA:   ~{eta_round} seconds")
                            print(f"  Entry Vector:    {dir_desc}")
                            if operator:
                                print(f"  Operator/Line:   {operator}")
                            if route:
                                print(f"  Route:           {route}")
                            print(f"  {alt_display}")
                            if dyn_display:
                                print(f"  {dyn_display}")
                            print(f"  Live Radar:      {adsb_url}")
                            print("=" * 75 + "\n")
                            
                            self.notification_manager.send_notification(title, message, subtitle, url=adsb_url)
                            
                    # -------------------------------------------------------------
                    # CASE 2: AIRCRAFT IS CURRENTLY INSIDE DESIGNATED AIRSPACE
                    # -------------------------------------------------------------
                    elif pred_status == "already_inside":
                        if state["status"] not in ("inside", "departing"):
                            state["status"] = "inside"
                            
                            # If never warned (e.g. started inside or supersonic approach)
                            if not state["entered_notified"] and self.notify_on_entry:
                                state["entered_notified"] = True
                                
                                event_tag = "🛫 DEPARTING" if is_climbing and (baro_alt or 0) < 3000 else "✈️ OVERHEAD"
                                title = f"{event_tag}: {display_name}{title_type}"
                                subtitle = f"Inside {self.location_name} • {operator or country}"
                                msg_lines = []
                                if model:
                                    msg_lines.append(f"Aircraft: {model}")
                                msg_lines.append(alt_display)
                                if dyn_display:
                                    msg_lines.append(dyn_display)
                                if route:
                                    msg_lines.append(f"Route: {route}")
                                msg_lines.append("Click to view live on ADS-B Exchange")
                                
                                message = "\n".join(msg_lines)
                                
                                print("\n" + "-" * 70)
                                print(f"✈️  AIRSPACE ACTIVITY: {display_name} is inside {self.location_name}")
                                print("-" * 70)
                                print(f"  {alt_display} | {dyn_display}")
                                print(f"  Live Radar: {adsb_url}\n")
                                
                                if not state["warned_entry"]:
                                    self.notification_manager.send_notification(title, message, subtitle, url=adsb_url)
                                    
                    # -------------------------------------------------------------
                    # CASE 3: AIRCRAFT EXITED / DEPARTED THE AIRSPACE
                    # -------------------------------------------------------------
                    elif pred_status in ("will_enter", "no_intersection"):
                        if state["status"] in ("inside", "departing"):
                            # Aircraft just departed the target box
                            state["status"] = "outside"
                            state["warned_entry"] = False    # Reset warning so the next lap triggers ~1 min before re-entry!
                            state["entered_notified"] = False
                            
                            if self.notify_on_departure and not state.get("departed_notified", False):
                                state["departed_notified"] = True
                                
                                dirs = ["North", "NNE", "NE", "ENE", "East", "ESE", "SE", "SSE",
                                        "South", "SSW", "SW", "WSW", "West", "WNW", "NW", "NNW"]
                                heading_cardinal = dirs[round((track_deg or 0) / 22.5) % 16] if track_deg is not None else "outbound"
                                
                                title = f"🛫 DEPARTED: {display_name}{title_type}"
                                subtitle = f"Exited {self.location_name} (Heading {heading_cardinal}) • {operator or country}"
                                
                                msg_lines = [
                                    f"Status: Departed {self.location_name} (Heading {heading_cardinal})",
                                ]
                                if model:
                                    msg_lines.append(f"Aircraft: {model}")
                                msg_lines.append(alt_display)
                                if dyn_display:
                                    msg_lines.append(dyn_display)
                                if route:
                                    msg_lines.append(f"Route: {route}")
                                msg_lines.append("Click to view live on ADS-B Exchange")
                                
                                message = "\n".join(msg_lines)
                                
                                print("\n" + "-" * 70)
                                print(f"🛫  AIRSPACE DEPARTURE: {display_name} has exited {self.location_name}")
                                print("-" * 70)
                                print(f"  Heading: {heading_cardinal} ({round(track_deg or 0)}°) | {alt_display} | {dyn_display}")
                                print(f"  Live Radar: {adsb_url}\n")
                                
                                self.notification_manager.send_notification(title, message, subtitle, url=adsb_url)
                        elif pred_status == "no_intersection":
                            if state["status"] == "outside":
                                state["departed_notified"] = False
                                state["takeoff_notified"] = False
                            
                # Cleanup state cache for planes not seen in 10 minutes
                stale_threshold = now - 600
                stale_keys = [k for k, v in self.aircraft_states.items() if v["last_seen"] < stale_threshold]
                for k in stale_keys:
                    del self.aircraft_states[k]
                    if k in self.aircraft_cache:
                        del self.aircraft_cache[k]
                        
            except KeyboardInterrupt:
                print("\nStopping flight tracking...")
                break
            except Exception as e:
                print(f"Error in tracking loop: {e}")
            
            time.sleep(self.tracking_config.get("poll_interval", 10))
