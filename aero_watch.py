#!/usr/bin/env python3
"""
Aero Watch ✈️ - Desktop Airspace & Flight Tracker
Originally created by Pankaj Tanwar (https://github.com/Pankajtanwarbanna/aero-watch)
Enhanced edition by Puneeth Kakarla (https://github.com/PK-999/aero-watch)

Monitors local airspace using public ADS-B telemetry and broadcasts real-time macOS
notifications with predictive early warning, takeoff tracking, and aircraft metadata.
"""
import os
import sys
from pathlib import Path

# Auto-switch to local .venv if dependencies are missing in current environment
try:
    import requests
except ModuleNotFoundError:
    venv_python = Path(__file__).resolve().parent / ".venv" / "bin" / "python3"
    if venv_python.exists() and sys.executable != str(venv_python):
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)
    raise

import argparse
from flight_tracker import FlightTracker
from config_manager import Config

def main():
    parser = argparse.ArgumentParser(description='Track flights in specified areas')
    parser.add_argument('location', nargs='?',
                       help='Location to track (blr_airport, hal_area, entire_blr)')
    parser.add_argument('--list-locations', action='store_true',
                       help='List available locations')
    
    args = parser.parse_args()
    
    config = Config()
    
    if args.list_locations:
        print("Available locations:")
        for key, location in config.get_all_locations().items():
            print(f"  {key}: {location['name']}")
        return
    
    if not args.location:
        parser.error("Location is required unless using --list-locations")
    
    try:
        tracker = FlightTracker(args.location)
        tracker.start_tracking()
    except ValueError as e:
        print(f"Error: {e}")
        print("\nUse --list-locations to see available options")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nFlight tracking stopped.")
        sys.exit(0)

if __name__ == "__main__":
    main()
