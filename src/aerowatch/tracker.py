"""Pure per-aircraft alert transitions. No network, notification, or timing I/O."""

from collections.abc import Iterable
from dataclasses import dataclass

from .config import TrackingSettings
from .models import AircraftObservation, AlertEvent, Location
from .prediction import predict_entry


@dataclass
class _State:
    last_seen: float
    inside: bool = False
    ground: bool | None = None
    warned: bool = False
    overhead_notified: bool = False
    ground_notified: bool = False
    airborne_visit: bool = False
    takeoff_notified: bool = False

    def reset_visit(self):
        self.warned = False
        self.overhead_notified = False
        self.ground_notified = False
        self.airborne_visit = False
        self.takeoff_notified = False


class FlightTracker:
    def __init__(self, location: Location, settings: TrackingSettings):
        self.location = location
        self.settings = settings
        self._states: dict[str, _State] = {}

    def process(self, aircraft: Iterable[AircraftObservation], now: float) -> list[AlertEvent]:
        self._states = {
            key: state for key, state in self._states.items() if now - state.last_seen < 600
        }
        events = []
        seen = set()
        for observation in aircraft:
            if observation.icao24 in seen:
                continue
            seen.add(observation.icao24)
            state = self._states.setdefault(observation.icao24, _State(now))
            inside = self.location.bounds.contains(observation.latitude, observation.longitude)
            airborne = observation.on_ground is False
            exited = state.inside and not inside
            took_off = inside and state.inside and state.ground is True and airborne
            if exited:
                if (
                    state.airborne_visit
                    and observation.on_ground is not True
                    and self.settings.notify_on_departure
                ):
                    events.append(AlertEvent("departed", observation))
                state.reset_visit()
            elif inside:
                if airborne:
                    state.airborne_visit = True
                    if (
                        took_off
                        and self.settings.notify_on_departure
                        and not state.takeoff_notified
                    ):
                        events.append(AlertEvent("takeoff", observation))
                        state.overhead_notified = True
                        state.takeoff_notified = True
                    elif not state.overhead_notified:
                        if not state.warned and self.settings.notify_on_entry:
                            events.append(AlertEvent("overhead", observation))
                        state.overhead_notified = True
                elif observation.on_ground is True:
                    if (
                        not state.ground_notified
                        and not self.settings.ignore_ground_aircraft
                        and self.settings.notify_on_entry
                    ):
                        events.append(AlertEvent("overhead", observation))
                    state.ground_notified = True
            else:
                prediction = predict_entry(self.location.bounds, observation) if airborne else None
                if prediction is None:
                    state.warned = False
                elif (
                    self.settings.predictive_warning
                    and prediction.eta_seconds <= self.settings.warning_lead_time_seconds
                    and not state.warned
                ):
                    events.append(AlertEvent("incoming", observation, prediction))
                    state.warned = True
            state.last_seen, state.inside, state.ground = now, inside, observation.on_ground
        return events
