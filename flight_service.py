import requests
import time
from auth_manager import AuthManager
from config_manager import Config

class FlightService:
    def __init__(self):
        self.config = Config()
        self.auth_manager = AuthManager()
        self.opensky_config = self.config.get_opensky_config()
    
    def get_planes_in_area(self, location_params):
        planes_by_hex = {}
        
        lamin = min(float(location_params["lamin"]), float(location_params["lamax"]))
        lamax = max(float(location_params["lamin"]), float(location_params["lamax"]))
        lomin = min(float(location_params["lomin"]), float(location_params["lomax"]))
        lomax = max(float(location_params["lomin"]), float(location_params["lomax"]))
        
        lat_c = (lamin + lamax) / 2.0
        lon_c = (lomin + lomax) / 2.0
        
        # Calculate radius in nautical miles covering the surveillance box (1 deg lat ~ 60 NM)
        d_lat_nm = (lamax - lamin) * 30.0
        d_lon_nm = (lomax - lomin) * 30.0
        radius_nm = max(10, min(80, int((d_lat_nm**2 + d_lon_nm**2)**0.5 + 5)))
        
        # Helper to process readsb/tar1090 formatted aircraft dictionaries
        def ingest_ac_list(ac_list):
            for ac in ac_list:
                hex_code = (ac.get("hex") or "").lower().strip()
                plat = ac.get("lat")
                plon = ac.get("lon")
                if not hex_code or plat is None or plon is None:
                    continue
                
                alt_b = ac.get("alt_baro")
                on_g = alt_b == "ground"
                baro_m = 0 if on_g else (alt_b * 0.3048 if isinstance(alt_b, (int, float)) else None)
                gs_kts = ac.get("gs")
                vel_ms = (gs_kts * 0.514444) if isinstance(gs_kts, (int, float)) else 0.0
                track_deg = ac.get("track", 0.0) or 0.0
                callsign = (ac.get("flight") or "").strip()
                country = ac.get("r") or "Unknown"
                vrate_fpm = ac.get("baro_rate")
                vrate_ms = (vrate_fpm * 0.00508) if isinstance(vrate_fpm, (int, float)) else None
                geom_alt = ac.get("alt_geom")
                geom_m = geom_alt * 0.3048 if isinstance(geom_alt, (int, float)) else None
                squawk = ac.get("squawk")
                
                # Cache aircraft details directly if present
                if hex_code not in getattr(self, "_feeder_details_cache", {}):
                    if not hasattr(self, "_feeder_details_cache"):
                        self._feeder_details_cache = {}
                    desc = ac.get("desc")
                    t_code = ac.get("t")
                    reg = ac.get("r")
                    if desc or t_code or reg:
                        self._feeder_details_cache[hex_code] = {
                            "registration": reg,
                            "type_code": t_code,
                            "model": desc,
                            "squawk": squawk
                        }
                
                if hex_code not in planes_by_hex:
                    planes_by_hex[hex_code] = [
                        hex_code, callsign, country, None, None,
                        plon, plat, baro_m, on_g, vel_ms,
                        track_deg, vrate_ms, None, geom_m, squawk
                    ]
                else:
                    # Update with latest coordinates / speed if new record is richer
                    existing = planes_by_hex[hex_code]
                    if not existing[1] and callsign:
                        existing[1] = callsign
                    if existing[7] is None and baro_m is not None:
                        existing[7] = baro_m
        
        # 1. Primary Feeder: adsb.lol (community ADS-B, military & MLAT aggregator)
        try:
            url = f"https://api.adsb.lol/v2/point/{lat_c:.4f}/{lon_c:.4f}/{radius_nm}"
            response = requests.get(url, timeout=3.5)
            if response.status_code == 200:
                ingest_ac_list(response.json().get("ac", []))
        except Exception:
            pass
            
        # 2. Secondary Feeder: opendata.adsb.fi (high-speed European & global community network with live MLAT)
        try:
            url = f"https://opendata.adsb.fi/api/v2/lat/{lat_c:.4f}/lon/{lon_c:.4f}/dist/{radius_nm}"
            response = requests.get(url, timeout=3.5)
            if response.status_code == 200:
                ingest_ac_list(response.json().get("aircraft", []))
        except Exception:
            pass
            
        # 3. Tertiary Fallback: OpenSky Network API
        try:
            norm_params = {"lamin": lamin, "lamax": lamax, "lomin": lomin, "lomax": lomax}
            url = f"{self.opensky_config['base_url']}/states/all"
            response = requests.get(url, params=norm_params, timeout=4.5)
            if response.status_code == 200:
                states = response.json().get("states") or []
                for s in states:
                    h = s[0].lower()
                    if h not in planes_by_hex:
                        planes_by_hex[h] = s
                    else:
                        existing = planes_by_hex[h]
                        if not existing[1] and s[1]:
                            existing[1] = s[1].strip()
                        if existing[7] is None and s[7] is not None:
                            existing[7] = s[7]
        except Exception:
            pass
            
        return list(planes_by_hex.values())
    
    def get_route_info(self, icao24):
        try:
            token = self.auth_manager.get_access_token()
            if not token:
                return None
            
            now = int(time.time())
            time_windows = [3600, 7200, 14400, 43200]
            
            for window in time_windows:
                begin_time = now - window
                print(f"Trying route lookup for {icao24} with {window//3600}h window...")
                
                url = f"{self.opensky_config['base_url']}/flights/aircraft"
                response = requests.get(
                    url,
                    params={"icao24": icao24, "begin": begin_time, "end": now},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10
                )
                
                print(f"API Response Status: {response.status_code}")
                
                if response.status_code == 200:
                    flights = response.json()
                    print(f"Found {len(flights)} flights for {icao24}")
                    
                    if flights:
                        latest = max(flights, key=lambda x: x.get("lastSeen", 0))
                        dep = latest.get("estDepartureAirport") or latest.get("estDepartureAirportHorizDistance")
                        arr = latest.get("estArrivalAirport") or latest.get("estArrivalAirportHorizDistance")
                        
                        if dep and arr:
                            return f"{dep} → {arr}"
                        elif dep:
                            return f"From {dep}"
                        elif arr:
                            return f"To {arr}"
                elif response.status_code == 401:
                    print("Token expired or invalid, will get new token next time")
                    self.auth_manager.invalidate_token()
                    break
                
                time.sleep(1)
            
            return None
            
        except Exception as e:
            print(f"Route fetch error for {icao24}: {e}")
            return None

    def get_aircraft_details(self, icao24, callsign=""):
        details = {
            "registration": None,
            "model": None,
            "type_code": None,
            "operator": None,
            "airline": None,
            "route": None,
            "flight_number": None,
            "squawk": None,
        }
        
        clean_callsign = callsign.strip() if callsign else ""
        clean_hex = icao24.lower().strip()
        
        # 0. Check live feeder cache populated during area scans (instantaneous)
        if hasattr(self, "_feeder_details_cache") and clean_hex in self._feeder_details_cache:
            cached = self._feeder_details_cache[clean_hex]
            for k in ["registration", "type_code", "model", "squawk"]:
                if cached.get(k):
                    details[k] = cached[k]
        if clean_callsign:
            try:
                r = requests.get(f"https://api.adsbdb.com/v0/callsign/{clean_callsign}", timeout=2.5)
                if r.status_code == 200:
                    fr = r.json().get("response", {}).get("flightroute", {})
                    if fr:
                        details["flight_number"] = fr.get("callsign_iata") or clean_callsign
                        airline = fr.get("airline", {}).get("name")
                        orig = fr.get("origin", {}).get("iata_code") or fr.get("origin", {}).get("icao_code")
                        dest = fr.get("destination", {}).get("iata_code") or fr.get("destination", {}).get("icao_code")
                        if orig and dest:
                            details["route"] = f"{orig} → {dest}"
                        if airline:
                            details["airline"] = airline
            except Exception:
                pass

        # 2. Live telemetry & description via adsb.fi
        try:
            r = requests.get(f"https://opendata.adsb.fi/api/v2/hex/{clean_hex}", timeout=2.5)
            if r.status_code == 200:
                ac_list = r.json().get("ac", [])
                if ac_list:
                    ac = ac_list[0]
                    details["registration"] = ac.get("r")
                    details["type_code"] = ac.get("t")
                    details["model"] = ac.get("desc")
                    details["squawk"] = ac.get("squawk")
        except Exception:
            pass

        # 3. Fallback to adsb.lol if model still missing
        if not details["model"]:
            try:
                r = requests.get(f"https://api.adsb.lol/v2/hex/{clean_hex}", timeout=2.5)
                if r.status_code == 200:
                    ac_list = r.json().get("ac", [])
                    if ac_list:
                        ac = ac_list[0]
                        if not details["registration"] and ac.get("r"):
                            details["registration"] = ac.get("r")
                        if not details["type_code"] and ac.get("t"):
                            details["type_code"] = ac.get("t")
                        if not details["model"] and ac.get("desc"):
                            details["model"] = ac.get("desc")
            except Exception:
                pass

        # 4. Hexdb lookup for owner / manufacturer if missing
        if not details["operator"] or not details["model"]:
            try:
                r = requests.get(f"https://hexdb.io/api/v1/aircraft/{clean_hex}", timeout=2.5)
                if r.status_code == 200:
                    hd = r.json()
                    if not details["registration"] and hd.get("Registration"):
                        details["registration"] = hd.get("Registration")
                    if not details["model"] and hd.get("Type"):
                        man = hd.get("Manufacturer", "")
                        details["model"] = f"{man} {hd.get('Type')}".strip()
                    if not details["type_code"] and hd.get("ICAOTypeCode"):
                        details["type_code"] = hd.get("ICAOTypeCode")
                    if not details["operator"] and hd.get("RegisteredOwners"):
                        details["operator"] = hd.get("RegisteredOwners")
            except Exception:
                pass

        # 5. Fallback to adsbdb aircraft endpoint
        if not details["operator"] or not details["model"]:
            try:
                r = requests.get(f"https://api.adsbdb.com/v0/aircraft/{clean_hex}", timeout=2.5)
                if r.status_code == 200:
                    ad = r.json().get("response", {}).get("aircraft", {})
                    if not details["registration"] and ad.get("registration"):
                        details["registration"] = ad.get("registration")
                    if not details["model"] and ad.get("type"):
                        man = ad.get("manufacturer", "")
                        details["model"] = f"{man} {ad.get('type')}".strip()
                    if not details["operator"] and ad.get("registered_owner"):
                        details["operator"] = ad.get("registered_owner")
            except Exception:
                pass

        return details

