"""Walidacja komunikatu od czujnika (krok „Dane poprawne?” na diagramie 3).

Rekord błędny (LAB05, strona 3):
  * spot_id spoza A01–C30,
  * zone niezgodna z miejscem,
  * state inny niż ZAJĘTE / WOLNE,
  * msg_type inny niż ZMIANA / HEARTBEAT,
  * brak event_time_utc lub czas > 1 min w przyszłości,
  * distance_cm < 0 lub > 450.
Dodatkowo (bezpieczeństwo): niepoprawny JSON, za duży komunikat, temat MQTT
lub tożsamość urządzenia niezgodna z miejscem.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, Union

from . import model

MAX_PAYLOAD_BYTES = 1024


@dataclass(frozen=True)
class Message:
    spot_id: str
    zone: str
    state: str
    distance_cm: float
    msg_type: str
    event_time: datetime  # UTC


class ValidationError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _decode(payload: Union[bytes, str, dict]) -> dict:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, (bytes, bytearray)):
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise ValidationError("za_duzy_komunikat", f"{len(payload)} B")
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("niepoprawne_kodowanie", str(exc)) from exc
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValidationError("za_duzy_komunikat")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValidationError("niepoprawny_json", str(exc)) from exc
        if not isinstance(data, dict):
            raise ValidationError("niepoprawny_json", "oczekiwano obiektu JSON")
        return data
    raise ValidationError("niepoprawny_json", f"typ {type(payload).__name__}")


def validate(
    payload: Union[bytes, str, dict],
    received_at: datetime,
    topic: Optional[str] = None,
    device_id: Optional[str] = None,
    gateway_ids: tuple = (),
) -> Message:
    """Zwraca poprawny Message albo zgłasza ValidationError z kodem powodu."""
    data = _decode(payload)

    for field in model.MESSAGE_FIELDS:
        if field not in data or data[field] is None or data[field] == "":
            if field == "event_time_utc":
                raise ValidationError("brak_czasu")
            raise ValidationError("brak_pola", field)

    spot_id = data["spot_id"]
    if not isinstance(spot_id, str) or spot_id not in model.ALL_SPOTS:
        raise ValidationError("nieznane_miejsce", str(spot_id)[:20])

    zone = data["zone"]
    if zone != model.zone_of(spot_id):
        raise ValidationError("strefa_niezgodna", f"{zone} dla {spot_id}")

    state = data["state"]
    if state not in model.DEVICE_STATES:
        raise ValidationError("niepoprawny_stan", str(state)[:20])

    msg_type = data["msg_type"]
    if msg_type not in model.MSG_TYPES:
        raise ValidationError("niepoprawny_typ", str(msg_type)[:20])

    distance = data["distance_cm"]
    if isinstance(distance, bool) or not isinstance(distance, (int, float)):
        raise ValidationError("odleglosc_poza_zakresem", "nie jest liczbą")
    if not (model.DISTANCE_MIN_CM <= distance <= model.DISTANCE_MAX_CM):
        raise ValidationError("odleglosc_poza_zakresem", str(distance))

    try:
        event_time = model.parse_iso(data["event_time_utc"])
    except (ValueError, TypeError) as exc:
        raise ValidationError("niepoprawny_czas", str(exc)[:60]) from exc
    if event_time > received_at + timedelta(seconds=model.MAX_FUTURE_SKEW_S):
        raise ValidationError("czas_w_przyszlosci", model.to_iso(event_time))

    # Temat MQTT musi wskazywać to samo miejsce co treść (ochrona przed
    # podszywaniem się jednego czujnika pod inny w ramach ACL brokera).
    if topic is not None and topic != model.topic_for(spot_id):
        raise ValidationError("temat_niezgodny", topic[:60])

    # Tożsamość urządzenia w IoT Hub: czujnik-B03 może wysyłać tylko dla B03;
    # bramka/symulator z listy gateway_ids może wysyłać dla wszystkich miejsc.
    if device_id is not None and device_id not in gateway_ids:
        if device_id != f"czujnik-{spot_id}":
            raise ValidationError("urzadzenie_niezgodne", device_id[:60])

    return Message(
        spot_id=spot_id,
        zone=zone,
        state=state,
        distance_cm=float(distance),
        msg_type=msg_type,
        event_time=event_time,
    )


def raw_excerpt(payload: Any, limit: int = 300) -> str:
    """Bezpieczny wycinek treści do tabeli odrzuconych komunikatów."""
    if isinstance(payload, dict):
        text = json.dumps(payload, ensure_ascii=False)
    elif isinstance(payload, (bytes, bytearray)):
        text = bytes(payload[:limit * 4]).decode("utf-8", errors="replace")
    else:
        text = str(payload)
    return text[:limit]
