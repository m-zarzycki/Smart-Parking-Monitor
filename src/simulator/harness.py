"""Uruchomienie scenariusza end-to-end w zegarze wirtualnym.

symulator (logika ESP32) -> komunikat JSON (temat MQTT) -> ParkingService.handle_message
-> baza; co 10 s ParkingService.check_silence. W punktach kontrolnych porównuje stan
bazy i napisy tablicy z oczekiwaniami ze scenariusza (K4) i zapisuje wynik.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from parking import model
from parking.db import Database
from parking.service import ParkingService

from .engine import MessageLog, run_scenario
from .scenarios import Scenario

LATENCY = timedelta(milliseconds=200)  # umowne opóźnienie sieci w zegarze wirtualnym


@dataclass
class CheckpointResult:
    t: float
    time_utc: datetime
    label: str
    board: dict
    sql_free: dict
    states: dict
    active_alerts: int
    expected: dict
    ok: bool
    problems: list = field(default_factory=list)


@dataclass
class RunResult:
    scenario: Scenario
    message_log: MessageLog
    checkpoints: list
    results: list = field(default_factory=list)  # wyniki handle_message
    silence_events: list = field(default_factory=list)  # (czas, miejsca BRAK DANYCH, nowe alerty)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checkpoints)


def run_virtual(scenario: Scenario, db: Database, service: Optional[ParkingService] = None,
                extra_checks: Optional[list] = None) -> RunResult:
    service = service or ParkingService(db)
    start = scenario.nominal_start_utc
    service.start(start)
    pending = sorted(list(scenario.checkpoints) + list(extra_checks or []), key=lambda c: c.t)
    run = RunResult(scenario=scenario, message_log=MessageLog(), checkpoints=[])

    def sink(topic: str, payload: bytes, msg: dict, now: datetime) -> None:
        run.results.append(service.handle_message(payload, now + LATENCY, topic=topic))

    def on_tick(t: float, now: datetime) -> None:
        # Kontrola braku danych co 10 s (jak timer funkcji Kontrola).
        if abs(t / model.CHECK_PERIOD_S - round(t / model.CHECK_PERIOD_S)) < 1e-9:
            res = service.check_silence(now)
            if res.no_data or res.alerts_opened:
                run.silence_events.append((now, list(res.no_data), list(res.alerts_opened)))
        while pending and pending[0].t <= t + 1e-9:
            cp = pending.pop(0)
            run.checkpoints.append(evaluate(service, db, cp, now))

    run_scenario(scenario, sink, start=start, realtime=False, on_tick=on_tick,
                 message_log=run.message_log)
    return run


def evaluate(service: ParkingService, db: Database, cp, now: datetime) -> CheckpointResult:
    board = service.board()
    labels = {z: board[z]["napis"] for z in model.ZONES}
    sql_free = {z: board[z]["wolne"] for z in model.ZONES}
    spots = {s["spot_id"]: s["stan"] for s in db.spots()}
    active = len(db.alerts(active_only=True))
    problems = []
    for zone, expected in cp.board.items():
        if labels[zone] != expected:
            problems.append(f"tablica {zone}: {labels[zone]} zamiast {expected}")
    for spot, expected in cp.states.items():
        if spots[spot] != expected:
            problems.append(f"{spot}: {spots[spot]} zamiast {expected}")
    if cp.active_alerts is not None and active != cp.active_alerts:
        problems.append(f"aktywne alerty: {active} zamiast {cp.active_alerts}")
    # K4: licznik tablicy = liczba miejsc WOLNE w bazie (niezależne zapytanie po stanach miejsc).
    for zone in model.ZONES:
        direct = sum(1 for s, st in spots.items() if s[0] == zone and st == model.WOLNE)
        if direct != sql_free[zone]:
            problems.append(f"licznik {zone}={sql_free[zone]} != WOLNE w bazie {direct}")
        expected_label = model.board_label(direct, 0, sum(
            1 for s, st in spots.items() if s[0] == zone and st == model.BRAK_DANYCH))
        if labels[zone] != expected_label:
            problems.append(f"napis {zone}={labels[zone]} != reguła 7 ({expected_label})")
    return CheckpointResult(
        t=cp.t, time_utc=now, label=cp.label, board=labels, sql_free=sql_free,
        states={s: spots[s] for s in cp.states}, active_alerts=active,
        expected={"board": cp.board, "states": cp.states, "active_alerts": cp.active_alerts},
        ok=not problems, problems=problems,
    )
