"""Silnik symulatora: 90 czujników, krok 0,5 s, zegar wirtualny albo rzeczywisty."""
from __future__ import annotations

import csv
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from parking import model

from .edge import EdgeSensor
from .scenarios import Scenario

log = logging.getLogger("symulator")

TICK = timedelta(seconds=model.SAMPLE_PERIOD_S)


class MessageLog:
    """Log wysłanych (i utraconych) komunikatów – do porównania z bazą (K1) i analizy (LAB08)."""

    FIELDS = ["czas_wyslania_utc", "spot_id", "zone", "msg_type", "state", "distance_cm",
              "event_time_utc", "wyslano", "uwagi"]

    def __init__(self, path: Optional[str] = None):
        self.rows: list[dict] = []
        self.path = path
        self._fh = None
        self._writer = None
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._fh = open(path, "w", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._fh, fieldnames=self.FIELDS)
            self._writer.writeheader()

    def add(self, sent_at: datetime, msg: dict, sent: bool, note: str = "") -> None:
        row = {
            "czas_wyslania_utc": model.to_iso(sent_at),
            "spot_id": msg["spot_id"], "zone": msg["zone"], "msg_type": msg["msg_type"],
            "state": msg["state"], "distance_cm": msg["distance_cm"],
            "event_time_utc": msg["event_time_utc"], "wyslano": "TAK" if sent else "NIE",
            "uwagi": note,
        }
        self.rows.append(row)
        if self._writer:
            self._writer.writerow(row)
            self._fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


Sink = Callable[[str, bytes, dict, datetime], None]   # (temat, treść, komunikat, czas)


def encode(msg: dict) -> bytes:
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def run_scenario(
    scenario: Scenario,
    sink: Sink,
    start: Optional[datetime] = None,
    realtime: bool = False,
    on_tick: Optional[Callable[[float, datetime], None]] = None,
    message_log: Optional[MessageLog] = None,
) -> MessageLog:
    """Odtwarza scenariusz. on_tick(t, now) wywoływane po każdym kroku (kontrola, punkty kontrolne)."""
    start = start or scenario.nominal_start_utc
    message_log = message_log or MessageLog()
    sensors = {spot: EdgeSensor(spot) for spot in model.ALL_SPOTS}
    boot_tick = {spot: int(round(scenario.boot_offset(spot) / model.SAMPLE_PERIOD_S))
                 for spot in model.ALL_SPOTS}
    n_ticks = int(scenario.duration_s / model.SAMPLE_PERIOD_S)
    wall0 = time.monotonic()

    for tick in range(n_ticks + 1):
        t = tick * model.SAMPLE_PERIOD_S
        if realtime:
            delay = wall0 + t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            now = model.utcnow()
        else:
            now = start + tick * TICK
        for spot in model.ALL_SPOTS:
            if tick < boot_tick[spot]:
                continue
            distance = scenario.distance(spot, t, tick)
            for msg in sensors[spot].sample(now, distance):
                if scenario.online(spot, t):
                    sink(model.topic_for(spot), encode(msg), msg, now)
                    message_log.add(now, msg, True)
                else:
                    message_log.add(now, msg, False, "brak łączności – brak bufora")
        if on_tick:
            on_tick(t, now)
    return message_log


class TrafficModel:
    """Tryb „ruch”: losowe przyjazdy i odjazdy, piesi i rzadkie awarie (demo na żywo)."""

    def __init__(self, seed: int = 2, changes_per_minute: float = 6.0,
                 pedestrians_per_minute: float = 2.0, failures: bool = False):
        self.rng = random.Random(seed)
        self.occupied = {s: self.rng.random() < 0.7 for s in model.ALL_SPOTS}
        self.base = {s: (45 + self.rng.random() * 70, 240 + self.rng.random() * 150)
                     for s in model.ALL_SPOTS}
        self.obstacle_until: dict[str, float] = {}
        self.offline_until: dict[str, float] = {}
        self.p_change = changes_per_minute / 60.0 * model.SAMPLE_PERIOD_S
        self.p_ped = pedestrians_per_minute / 60.0 * model.SAMPLE_PERIOD_S
        self.failures = failures

    def step(self, t: float) -> None:
        if self.rng.random() < self.p_change:
            spot = self.rng.choice(model.ALL_SPOTS)
            # Strefa A zapełnia się chętniej niż C (kierowcy wybierają najbliższe miejsca).
            prefer = {"A": 0.8, "B": 0.6, "C": 0.45}[spot[0]]
            self.occupied[spot] = self.rng.random() < prefer
        if self.rng.random() < self.p_ped:
            spot = self.rng.choice(model.ALL_SPOTS)
            self.obstacle_until[spot] = t + self.rng.choice([0.5, 1.0, 1.5, 2.0, 2.5])
        if self.failures and self.rng.random() < 0.0005:
            spot = self.rng.choice(model.ALL_SPOTS)
            self.offline_until[spot] = t + self.rng.uniform(200, 400)
            log.info("Symulowana awaria łączności %s na ~%.0f s", spot, self.offline_until[spot] - t)

    def distance(self, spot: str) -> float:
        occ, free = self.base[spot]
        value = occ if self.occupied[spot] else free
        return value + self.rng.uniform(-3, 3)

    def reading(self, spot: str, t: float) -> float:
        if self.obstacle_until.get(spot, -1) >= t:
            return 85.0
        return self.distance(spot)

    def online(self, spot: str, t: float) -> bool:
        return self.offline_until.get(spot, -1) < t


def run_traffic(sink: Sink, traffic: TrafficModel, duration_s: Optional[float] = None,
                message_log: Optional[MessageLog] = None) -> MessageLog:
    """Ruch w czasie rzeczywistym (Ctrl+C kończy)."""
    message_log = message_log or MessageLog()
    sensors = {spot: EdgeSensor(spot) for spot in model.ALL_SPOTS}
    boot_tick = {spot: (model.ALL_SPOTS.index(spot) * 13) % 60 for spot in model.ALL_SPOTS}
    wall0 = time.monotonic()
    tick = 0
    try:
        while duration_s is None or tick * model.SAMPLE_PERIOD_S <= duration_s:
            t = tick * model.SAMPLE_PERIOD_S
            delay = wall0 + t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            now = model.utcnow()
            traffic.step(t)
            for spot in model.ALL_SPOTS:
                if tick < boot_tick[spot]:
                    continue
                for msg in sensors[spot].sample(now, traffic.reading(spot, t)):
                    if traffic.online(spot, t):
                        sink(model.topic_for(spot), encode(msg), msg, now)
                        message_log.add(now, msg, True)
                        if msg["msg_type"] == model.ZMIANA:
                            log.info("%s %s (%.0f cm)", spot, msg["state"], msg["distance_cm"])
                    else:
                        message_log.add(now, msg, False, "brak łączności – brak bufora")
            tick += 1
    except KeyboardInterrupt:
        log.info("Zatrzymano symulator")
    return message_log
