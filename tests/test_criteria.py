"""Kryteria sukcesu K1, K3, K4, K5 z karty LAB02 (cz. 8). K2 – test_k2_realtime.py."""
import pytest

from parking import model
from parking.db import Database
from simulator.harness import run_virtual
from simulator.scenarios import (SHORT_DETECTIONS, Checkpoint, Offline, scenario_1, scenario_2,
                                 scenario_3, scenario_k1, scenario_k3)


def fresh(tmp_path, name):
    return Database(f"sqlite:///{tmp_path / (name + '.db')}")


def test_K1_all_20_changes_saved(tmp_path):
    sc = scenario_k1()
    db = fresh(tmp_path, "k1")
    r = run_virtual(sc, db)
    sent = [m for m in r.message_log.rows
            if m["msg_type"] == model.ZMIANA and m["spot_id"] in sc.focus
            and m["event_time_utc"] > "2026-11-24T12:00:39"]
    assert len(sent) == 20
    saved = {(h["spot_id"], h["nowy_stan"], model.to_iso(h["czas_zmiany"])) for h in db.history()}
    found = [(m["spot_id"], m["state"], m["event_time_utc"]) in saved for m in sent]
    assert sum(found) == 20  # 20 z 20
    assert len({m["spot_id"][0] for m in sent}) == 3  # różne strefy


def test_K3_short_detections_change_nothing(tmp_path):
    sc = scenario_k3()
    db = fresh(tmp_path, "k3")
    r = run_virtual(sc, db)
    after_warmup = [m for m in r.message_log.rows
                    if m["msg_type"] == model.ZMIANA and m["event_time_utc"] > "2026-11-24T13:00:35"]
    assert after_warmup == []  # 0 komunikatów ZMIANA
    new_history = [h for h in db.history() if model.to_iso(h["czas_zmiany"]) > "2026-11-24T13:00:35"]
    assert new_history == []  # 0 nowych wpisów
    assert len(SHORT_DETECTIONS) == 10
    assert all(1.0 <= d <= 2.5 for _, d in SHORT_DETECTIONS)


@pytest.mark.parametrize("factory", [scenario_1, scenario_2, scenario_3])
def test_K4_counter_equals_free_spots_after_each_step(tmp_path, factory):
    sc = factory()
    # Dodatkowe punkty kontrolne co 30 s przez pierwsze 5 min – K4 sprawdzane „po każdym kroku”.
    extra = [Checkpoint(t, f"kontrola K4 t={t:.0f}s") for t in range(30, min(300, int(sc.duration_s)), 30)]
    r = run_virtual(sc, fresh(tmp_path, "k4_" + sc.key), extra_checks=extra)
    assert len(r.checkpoints) >= len(sc.checkpoints) + len(extra)
    assert r.ok, [(c.label, c.problems) for c in r.checkpoints if not c.ok]


@pytest.mark.parametrize("phase", [0.0, 2.5, 5.0, 7.5, 9.5])
def test_K5_no_data_within_3min10s_one_alert(tmp_path, phase):
    sc = scenario_3(20)
    # Przesunięcie chwili utraty łączności względem kontroli co 10 s (różne fazy, w tym najgorsza).
    sc.offline = [Offline("C05", 60.0 + phase, sc.offline[0].t_to + phase)]
    sc.boot_offsets["C05"] = phase
    for cp in sc.checkpoints:
        cp.t += phase
    sc.duration_s += phase
    db = fresh(tmp_path, f"k5_{phase}")
    r = run_virtual(sc, db)
    # Miejsce bez danych nie jest liczone jako wolne (licznik C 7 -> 6), potem wraca do 7.
    assert r.ok, [(c.label, c.problems) for c in r.checkpoints if not c.ok]
    a = db.alerts()
    assert len(a) == 1 and a[0]["spot_id"] == "C05"  # dokładnie jeden alert przy 20 min przerwy
    delay = (a[0]["czas_otwarcia"] - a[0]["czas_ostatniego_komunikatu"]).total_seconds()
    assert 180 < delay <= 190                         # BRAK DANYCH najpóźniej po 3 min 10 s
    assert a[0]["czas_zamkniecia"] is not None       # pierwszy nowy komunikat zamyka alert
