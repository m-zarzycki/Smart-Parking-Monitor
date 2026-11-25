"""F01 – reguła 3 s na ESP32 (symulator), reguły decyzji 2–5 z karty LAB02."""
from datetime import timedelta

from parking import model
from simulator.edge import EdgeSensor
from conftest import T0


def feed(sensor, distances, start_tick=0):
    out = []
    for i, d in enumerate(distances):
        out.extend(sensor.sample(T0 + timedelta(seconds=(start_tick + i) * 0.5), d))
    return out


def test_seven_readings_below_150_confirm_occupied():
    s = EdgeSensor("B03")
    msgs = feed(s, [60] * 7)
    assert [(m["msg_type"], m["state"]) for m in msgs] == [(model.ZMIANA, model.ZAJETE)]
    assert msgs[0]["event_time_utc"] == "2026-11-24T08:00:03.000Z"  # odczyty 0…3 s


def test_six_readings_are_not_enough():
    s = EdgeSensor("B03")
    assert feed(s, [60] * 6) == []


def test_free_needs_all_readings_at_least_200():
    s = EdgeSensor("B03")
    assert feed(s, [200] * 7)[0]["state"] == model.WOLNE
    s2 = EdgeSensor("B04")
    assert feed(s2, [250] * 6 + [199]) == []


def test_band_150_199_does_not_change_state():
    s = EdgeSensor("B03")
    feed(s, [60] * 7)
    assert feed(s, [150, 170, 199, 180, 160, 175, 190, 185], start_tick=7) == []
    assert s.confirmed == model.ZAJETE


def test_short_detection_does_not_change_state():
    s = EdgeSensor("B04")
    feed(s, [300] * 7)
    msgs = feed(s, [80] * 6 + [300] * 10, start_tick=7)  # 6 odczytów = 2,5 s
    assert msgs == []
    assert s.confirmed == model.WOLNE


def test_zmiana_only_when_state_differs():
    s = EdgeSensor("B03")
    first = feed(s, [60] * 7)
    again = feed(s, [65] * 20, start_tick=7)
    assert len(first) == 1 and again == []


def test_heartbeat_every_60_s_with_confirmed_state():
    s = EdgeSensor("B03")
    msgs = feed(s, [60] * 241)  # 0…120 s
    hb = [m for m in msgs if m["msg_type"] == model.HEARTBEAT]
    assert [m["event_time_utc"] for m in hb] == ["2026-11-24T08:01:00.000Z", "2026-11-24T08:02:00.000Z"]
    assert all(m["state"] == model.ZAJETE for m in hb)


def test_no_heartbeat_before_first_confirmed_state():
    s = EdgeSensor("B03")
    msgs = feed(s, [170] * 130)  # cały czas w strefie 150–199 cm
    assert msgs == []
