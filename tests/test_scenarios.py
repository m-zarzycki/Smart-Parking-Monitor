"""Scenariusze 1–3 i dodatkowy z karty LAB02 (cz. 7), uruchamiane end-to-end w zegarze wirtualnym:
symulator (logika ESP32) -> komunikat JSON -> Odbiornik -> baza -> Kontrola co 10 s -> tablica."""
from datetime import datetime, timezone

import pytest

from parking import model
from parking.db import Database
from simulator.harness import run_virtual
from simulator.scenarios import scenario_1, scenario_2, scenario_3, scenario_4


def utc(h, m, s, ms=0):  # godzina z karty (czas lokalny, UTC+1) -> UTC
    return datetime(2026, 11, 24, h - 1, m, s, ms * 1000, tzinfo=timezone.utc)


@pytest.fixture
def run(tmp_path):
    def _run(sc):
        return run_virtual(sc, Database(f"sqlite:///{tmp_path / (sc.key + '.db')}"))
    return _run


def spot_history(db_run, spot):
    return [(h["nowy_stan"], h["zrodlo"], h["czas_zmiany"]) for h in reversed(db_run.history(spot_id=spot))]


def test_scenario_1_normal_work(run, tmp_path):
    r = run(scenario_1())
    assert r.ok, [c.problems for c in r.checkpoints]
    db = Database(f"sqlite:///{tmp_path / '1.db'}")
    h = spot_history(db, "B03")
    # Wpis startowy WOLNE (ZMIANA po uruchomieniu czujnika) i jeden wpis ZAJĘTE o 09:00:03.
    assert h[-1] == (model.ZAJETE, "ZMIANA", utc(9, 0, 3))
    assert [x for x in h if x[0] == model.ZAJETE] == [h[-1]]
    sent = [m for m in r.message_log.rows if m["spot_id"] == "B03" and m["msg_type"] == "ZMIANA"]
    assert sent[-1]["event_time_utc"] == "2026-11-24T08:00:03.000Z"
    b03 = {s["spot_id"]: s for s in db.spots()}["B03"]
    assert b03["czas_ostatniego_komunikatu"] == utc(9, 1, 0, 200)  # heartbeat 09:01:00 + 0,2 s
    assert db.alerts() == []


def test_scenario_2_zone_a_fills(run):
    r = run(scenario_2())
    assert r.ok, [c.problems for c in r.checkpoints]
    labels = [c.board["A"] for c in r.checkpoints]
    assert labels == ["1", model.PELNA, model.PELNA, "1"]


def test_scenario_3_sensor_failure(run, tmp_path):
    r = run(scenario_3(20))
    assert r.ok, [c.problems for c in r.checkpoints]
    db = Database(f"sqlite:///{tmp_path / '3.db'}")
    # BRAK DANYCH najpóźniej o 11:03:10, dokładnie jeden alert z czasem ostatniego komunikatu 11:00:00.
    (when, no_data, opened), = r.silence_events
    assert no_data == ["C05"] and opened == ["C05"] and when <= utc(11, 3, 10)
    alerts = db.alerts()
    assert len(alerts) == 1
    a = alerts[0]
    assert a["czas_ostatniego_komunikatu"] == utc(11, 0, 0, 200)
    assert a["czas_zamkniecia"] == utc(11, 20, 0, 200)
    h = spot_history(db, "C05")
    assert [x[0] for x in h[-2:]] == [model.BRAK_DANYCH, model.WOLNE]
    lost = [m for m in r.message_log.rows if m["spot_id"] == "C05" and m["wyslano"] == "NIE"]
    assert len(lost) == 19  # heartbeaty 11:01–11:19 przepadły (brak bufora)


def test_extra_scenario_short_detection(run, tmp_path):
    r = run(scenario_4())
    assert r.ok, [c.problems for c in r.checkpoints]
    db = Database(f"sqlite:///{tmp_path / '4.db'}")
    sent = [m for m in r.message_log.rows if m["spot_id"] == "B04" and m["msg_type"] == "ZMIANA"]
    assert len(sent) == 1  # tylko zatwierdzenie stanu po uruchomieniu czujnika
    assert [x[0] for x in spot_history(db, "B04")] == [model.WOLNE]
