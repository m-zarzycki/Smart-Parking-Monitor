"""Funkcje Odbiornik i Kontrola: reguły 1, 6, 7 i zasady braku danych (LAB02, cz. 6)."""
from parking import model
from conftest import T0, send, sec


def alerts_for(db, spot, active_only=False):
    return [a for a in db.alerts(active_only=active_only) if a["spot_id"] == spot]


def history(db, spot):
    return [(h["nowy_stan"], h["zrodlo"]) for h in reversed(db.history(spot_id=spot))]


def state(db, spot):
    return {s["spot_id"]: s for s in db.spots()}[spot]


def test_rule1_all_spots_no_data_after_start(service, db):
    assert {s["stan"] for s in db.spots()} == {model.BRAK_DANYCH}
    assert all(z["napis"] == model.BRAK_DANYCH for z in service.board().values())


def test_change_saved_with_history(service, db):
    r = send(service, "B03", model.ZAJETE, t=T0 + sec(3))
    assert r.status == "zmiana"
    s = state(db, "B03")
    assert s["stan"] == model.ZAJETE and s["czas_zmiany_stanu"] == T0 + sec(3)
    assert history(db, "B03") == [(model.ZAJETE, "ZMIANA")]


def test_heartbeat_same_state_updates_only_last_message_time(service, db):
    send(service, "B03", model.ZAJETE, t=T0 + sec(3))
    r = send(service, "B03", model.ZAJETE, model.HEARTBEAT, t=T0 + sec(60))
    assert r.status == "bez_zmian"
    s = state(db, "B03")
    assert s["czas_ostatniego_komunikatu"] == T0 + sec(60.2)
    assert s["czas_zmiany_stanu"] == T0 + sec(3)
    assert len(history(db, "B03")) == 1


def test_rule6_heartbeat_with_different_state_is_accepted(service, db):
    send(service, "B03", model.ZAJETE, t=T0 + sec(3))
    r = send(service, "B03", model.WOLNE, model.HEARTBEAT, t=T0 + sec(60))  # utracona ZMIANA
    assert r.status == "zmiana"
    assert history(db, "B03") == [(model.ZAJETE, "ZMIANA"), (model.WOLNE, "HEARTBEAT")]


def test_duplicate_zmiana_is_idempotent(service, db):
    send(service, "B03", model.ZAJETE, t=T0 + sec(3))
    r = send(service, "B03", model.ZAJETE, t=T0 + sec(3), delay=0.5)  # QoS 1 – drugie dostarczenie
    assert r.status == "bez_zmian"
    assert len(history(db, "B03")) == 1


def test_older_message_cannot_revert_state(service, db):
    send(service, "B03", model.ZAJETE, t=T0 + sec(10))
    r = send(service, "B03", model.WOLNE, model.HEARTBEAT, t=T0 + sec(5), delay=6)
    assert r.status == "odrzucony" and r.reason == "starszy_niz_ostatni"
    assert state(db, "B03")["stan"] == model.ZAJETE


def test_invalid_message_goes_to_rejected_and_changes_nothing(service, db):
    r = send(service, "B03", model.ZAJETE, distance=999)
    assert r.status == "odrzucony"
    rej = db.rejected()
    assert rej[0]["powod"] == "odleglosc_poza_zakresem" and rej[0]["zrodlo"] == "parking/B/B03"
    assert state(db, "B03")["stan"] == model.BRAK_DANYCH
    assert history(db, "B03") == []


def test_silence_strictly_more_than_3_minutes(service, db):
    send(service, "C05", model.WOLNE, model.HEARTBEAT, t=T0, delay=0)
    assert "C05" not in service.check_silence(T0 + sec(180)).no_data      # dokładnie 3 min – jeszcze nie
    assert "C05" in service.check_silence(T0 + sec(190)).no_data          # następna kontrola
    assert state(db, "C05")["stan"] == model.BRAK_DANYCH


def test_one_alert_per_gap_and_counter_excludes_no_data(service, db):
    for spot in model.ALL_SPOTS:
        send(service, spot, model.WOLNE, model.HEARTBEAT, t=T0, delay=0)
    for k in range(1, 121):  # 20 min ciszy C05, inne czujniki nadają
        now = T0 + sec(10 * k)
        if k % 6 == 0:
            for spot in model.ALL_SPOTS:
                if spot != "C05":
                    send(service, spot, model.WOLNE, model.HEARTBEAT, t=now, delay=0)
        service.check_silence(now)
    alerts = db.alerts()
    assert [a["spot_id"] for a in alerts] == ["C05"]
    assert alerts[0]["czas_ostatniego_komunikatu"] == T0
    assert service.board()["C"]["wolne"] == 29


def test_acknowledge_does_not_change_state(service, db):
    send(service, "C05", model.WOLNE, t=T0, delay=0)
    service.check_silence(T0 + sec(190))
    alert = alerts_for(db, "C05", active_only=True)[0]
    assert db.acknowledge_alert(alert["id"], "zarzadca", T0 + sec(200))
    assert not db.acknowledge_alert(alert["id"], "zarzadca", T0 + sec(201))  # drugi raz – nic
    assert state(db, "C05")["stan"] == model.BRAK_DANYCH
    assert len(alerts_for(db, "C05", active_only=True)) == 1


def test_first_message_after_gap_sets_its_state_and_closes_alert(service, db):
    send(service, "C05", model.WOLNE, t=T0, delay=0)
    service.check_silence(T0 + sec(190))
    r = send(service, "C05", model.ZAJETE, model.HEARTBEAT, t=T0 + sec(1200), delay=0)
    assert r.status == "zmiana" and r.alert_closed
    assert state(db, "C05")["stan"] == model.ZAJETE  # stan z komunikatu, nie sprzed przerwy
    a = alerts_for(db, "C05")[0]
    assert a["czas_zamkniecia"] == T0 + sec(1200)
    assert history(db, "C05") == [(model.WOLNE, "ZMIANA"), (model.BRAK_DANYCH, "KONTROLA"),
                                  (model.ZAJETE, "HEARTBEAT")]


def test_never_heard_sensor_alert_counted_from_start(service, db):
    res = service.check_silence(T0 + sec(181))
    assert len(res.alerts_opened) == 90 and res.no_data == []  # stan już BRAK DANYCH
    assert db.alerts(active_only=True)[0]["czas_ostatniego_komunikatu"] is None
    assert service.check_silence(T0 + sec(191)).alerts_opened == []


def test_rule7_board_labels(service):
    for n in range(1, 31):
        send(service, f"A{n:02d}", model.ZAJETE)
    for n in range(1, 30):
        send(service, f"B{n:02d}", model.ZAJETE)  # B30 bez danych
    send(service, "C01", model.WOLNE)
    board = service.board()
    assert board["A"]["napis"] == model.PELNA            # 0 wolnych, wszystkie ZAJĘTE
    assert board["B"]["napis"] == model.BRAK_DANYCH      # 0 wolnych, ale B30 bez danych
    assert board["C"]["napis"] == "1"


def test_restart_resets_to_no_data_and_counts_silence_from_restart(service, db):
    send(service, "B03", model.ZAJETE)
    service.start(T0 + sec(3600))                       # restart godzinę później
    assert state(db, "B03")["stan"] == model.BRAK_DANYCH
    assert history(db, "B03")[-1] == (model.BRAK_DANYCH, "START")
    assert service.check_silence(T0 + sec(3600 + 100)).alerts_opened == []
