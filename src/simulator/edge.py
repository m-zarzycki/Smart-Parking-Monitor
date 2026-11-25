"""Logika brzegowa czujnika (to, co robi ESP32 przy każdym miejscu).

F01: pomiar co 0,5 s; stan zatwierdzony, gdy 7 kolejnych odczytów (0–3 s):
  * wszystkie < 150 cm  -> ZAJĘTE,
  * wszystkie >= 200 cm -> WOLNE,
  * odczyty 150–199 cm i wykrycia krótsze niż 3 s nie zmieniają stanu.
ZMIANA wysyłana tylko, gdy zatwierdzony stan różni się od poprzedniego.
HEARTBEAT co 60 s z bieżącym zatwierdzonym stanem.
ESP32 nie buforuje komunikatów: gdy brak sieci, komunikat przepada (ograniczenie).

Ta sama logika jest w szkicu firmware/esp32_czujnik/esp32_czujnik.ino.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Optional

from parking import model


def build_message(spot_id: str, state: str, distance_cm: float, msg_type: str,
                  event_time: datetime) -> dict:
    return {
        "spot_id": spot_id,
        "zone": model.zone_of(spot_id),
        "state": state,
        "distance_cm": round(float(distance_cm), 1),
        "msg_type": msg_type,
        "event_time_utc": model.to_iso(event_time),
    }


class EdgeSensor:
    """Jeden czujnik + ESP32. Czas podawany z zewnątrz (zegar rzeczywisty albo wirtualny)."""

    def __init__(self, spot_id: str, heartbeat_every_ticks: int = 120):
        self.spot_id = spot_id
        self.window: deque = deque(maxlen=model.CONFIRM_SAMPLES)
        self.confirmed: Optional[str] = None
        self.last_distance: Optional[float] = None
        self.ticks_since_boot = 0
        self.heartbeat_every = heartbeat_every_ticks  # 120 × 0,5 s = 60 s

    def sample(self, now: datetime, distance_cm: float) -> list[dict]:
        """Jeden odczyt co 0,5 s. Zwraca listę komunikatów do wysłania (0, 1 lub 2)."""
        out: list[dict] = []
        self.window.append(distance_cm)
        self.last_distance = distance_cm

        if len(self.window) == model.CONFIRM_SAMPLES:
            if all(d < model.OCCUPIED_BELOW_CM for d in self.window):
                candidate = model.ZAJETE
            elif all(d >= model.FREE_FROM_CM for d in self.window):
                candidate = model.WOLNE
            else:
                candidate = None  # strefa 150–199 cm albo krótkie wykrycie: bez zmiany
            if candidate is not None and candidate != self.confirmed:
                self.confirmed = candidate
                out.append(build_message(self.spot_id, candidate, distance_cm, model.ZMIANA, now))

        if self.ticks_since_boot > 0 and self.ticks_since_boot % self.heartbeat_every == 0:
            if self.confirmed is not None:
                out.append(build_message(self.spot_id, self.confirmed, distance_cm,
                                         model.HEARTBEAT, now))
        self.ticks_since_boot += 1
        return out
