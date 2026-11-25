"""Walidacja rekordu – krok „Dane poprawne?” (LAB05, strona 3) + kontrole bezpieczeństwa."""
import json
from datetime import timedelta

import pytest

from parking import model
from parking.validation import ValidationError, validate
from conftest import T0, msg

NOW = T0 + timedelta(seconds=1)


def reason(payload, **kw):
    with pytest.raises(ValidationError) as exc:
        validate(payload, NOW, **kw)
    return exc.value.reason


def test_valid_message():
    m = validate(msg(), NOW, topic="parking/B/B03")
    assert (m.spot_id, m.zone, m.state, m.msg_type, m.distance_cm) == ("B03", "B", model.ZAJETE, "ZMIANA", 60.0)
    assert m.event_time == T0


@pytest.mark.parametrize("over, expected", [
    ({"spot_id": "D01", "zone": "D"}, "nieznane_miejsce"),
    ({"spot_id": "B31"}, "nieznane_miejsce"),
    ({"zone": "A"}, "strefa_niezgodna"),
    ({"state": "BRAK DANYCH"}, "niepoprawny_stan"),
    ({"state": "zajete"}, "niepoprawny_stan"),
    ({"msg_type": "PING"}, "niepoprawny_typ"),
    ({"distance_cm": -1}, "odleglosc_poza_zakresem"),
    ({"distance_cm": 451}, "odleglosc_poza_zakresem"),
    ({"distance_cm": "60"}, "odleglosc_poza_zakresem"),
    ({"distance_cm": True}, "odleglosc_poza_zakresem"),
    ({"event_time_utc": ""}, "brak_czasu"),
    ({"event_time_utc": "wczoraj"}, "niepoprawny_czas"),
    ({"event_time_utc": "2026-11-24T08:00:00"}, "niepoprawny_czas"),  # bez strefy czasowej
])
def test_invalid_fields(over, expected):
    data = json.loads(msg())
    data.update(over)
    assert reason(data) == expected


def test_missing_field():
    data = json.loads(msg())
    del data["state"]
    assert reason(data) == "brak_pola"


def test_missing_time_field():
    data = json.loads(msg())
    del data["event_time_utc"]
    assert reason(data) == "brak_czasu"


def test_time_more_than_one_minute_in_future():
    assert reason(msg(t=NOW + timedelta(seconds=61))) == "czas_w_przyszlosci"
    validate(msg(t=NOW + timedelta(seconds=59)), NOW)  # tolerancja zegara do 1 min


def test_not_json_and_not_object():
    assert reason(b"{nie json") == "niepoprawny_json"
    assert reason(b"[1, 2]") == "niepoprawny_json"
    assert reason(b"\xff\xfe") == "niepoprawne_kodowanie"


def test_payload_too_large():
    assert reason(b"{" + b" " * 2000 + b"}") == "za_duzy_komunikat"


def test_topic_must_match_spot():
    assert reason(msg("B03"), topic="parking/B/B04") == "temat_niezgodny"


def test_device_identity():
    assert reason(msg("B03"), device_id="czujnik-B04") == "urzadzenie_niezgodne"
    validate(msg("B03"), NOW, device_id="czujnik-B03")
    validate(msg("B03"), NOW, device_id="symulator-01", gateway_ids=("symulator-01",))
