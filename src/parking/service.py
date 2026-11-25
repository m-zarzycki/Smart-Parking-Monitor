"""Rdzeń logiki systemu – wspólny dla trybu lokalnego i Azure.

* handle_message  – funkcja Odbiornik (F02): walidacja, porównanie z bazą, zapis,
                    zamknięcie alertu.
* check_silence   – funkcja Kontrola (F05): BRAK DANYCH po > 3 min ciszy, 1 alert.
* board           – liczniki stref na tablicy przy wjeździe (F03).
* snapshot_occupancy – próbka obłożenia stref do wykresu 7 dni (F05, historia).

Wszystkie funkcje przyjmują czas jako parametr, więc testy mogą używać zegara
wirtualnego (np. 20-minutowa przerwa ze scenariusza 3 trwa w teście ułamek sekundy).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Union

from . import model
from .db import Database
from .validation import ValidationError, raw_excerpt, validate

log = logging.getLogger("parking")


@dataclass
class Result:
    status: str                      # "zmiana" | "bez_zmian" | "odrzucony"
    spot_id: Optional[str] = None
    state: Optional[str] = None
    reason: Optional[str] = None
    alert_closed: bool = False


@dataclass
class CheckResult:
    no_data: list = field(default_factory=list)       # miejsca przełączone na BRAK DANYCH
    alerts_opened: list = field(default_factory=list)  # miejsca z nowym alertem


class ParkingService:
    def __init__(self, db: Database, gateway_ids: tuple = ()):
        self.db = db
        self.gateway_ids = tuple(gateway_ids)

    # ------------------------------------------------------------------------------------
    def start(self, now: datetime, reset: bool = True) -> None:
        """Uruchomienie systemu (reguła 1): do pierwszego komunikatu stan BRAK DANYCH."""
        self.db.init_schema()
        self.db.seed_spots(now)
        if not reset:
            return
        with self.db.tx() as t:
            rows = t.q(f"SELECT spot_id, strefa, stan FROM miejsca{self.db.lock_hint()}")
            for r in rows:
                if r["stan"] != model.BRAK_DANYCH:
                    t.ex("UPDATE miejsca SET stan = ?, czas_zmiany_stanu = ? WHERE spot_id = ?",
                         (model.BRAK_DANYCH, now, r["spot_id"]))
                    t.insert("historia_zmian", {
                        "spot_id": r["spot_id"].strip(), "strefa": r["strefa"].strip(),
                        "nowy_stan": model.BRAK_DANYCH, "czas_zmiany": now,
                        "czas_odebrania": now, "zrodlo": "START",
                    })
            if t.ex("UPDATE system SET wartosc = ? WHERE klucz = ?",
                    (model.to_iso(now), "czas_uruchomienia")) == 0:
                t.ex("INSERT INTO system (klucz, wartosc) VALUES (?, ?)",
                     ("czas_uruchomienia", model.to_iso(now)))
        log.info("Start systemu %s: wszystkie miejsca BRAK DANYCH do pierwszego komunikatu",
                 model.to_iso(now))

    # ------------------------------------------------------------------------------------
    def _reject(self, t, received_at: datetime, reason: str, detail: str,
                source: Optional[str], payload) -> None:
        t.insert("odrzucone_komunikaty", {
            "czas_odebrania": received_at,
            "powod": reason,
            "szczegoly": (detail or "")[:200],
            "zrodlo": (source or "")[:100],
            "tresc": raw_excerpt(payload),
        })

    def handle_message(
        self,
        payload: Union[bytes, str, dict],
        received_at: datetime,
        topic: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> Result:
        """Funkcja Odbiornik: kroki 3–4 na diagramie przepływu."""
        source = topic or device_id
        try:
            msg = validate(payload, received_at, topic=topic, device_id=device_id,
                           gateway_ids=self.gateway_ids)
        except ValidationError as err:
            with self.db.tx() as t:
                self._reject(t, received_at, err.reason, err.detail, source, payload)
            log.warning("Odrzucony komunikat (%s %s) z %s", err.reason, err.detail, source)
            return Result("odrzucony", reason=err.reason)

        with self.db.tx() as t:
            row = t.one(
                "SELECT spot_id, strefa, stan, czas_zdarzenia FROM miejsca"
                f"{self.db.lock_hint()} WHERE spot_id = ?",
                (msg.spot_id,),
            )
            last_event = self.db.ts(row["czas_zdarzenia"])
            # Komunikat starszy niż ostatnio przyjęty (np. opóźniony duplikat) nie może
            # cofnąć stanu miejsca.
            if last_event is not None and msg.event_time < last_event:
                self._reject(t, received_at, "starszy_niz_ostatni",
                             f"{model.to_iso(msg.event_time)} < {model.to_iso(last_event)}",
                             source, payload)
                log.warning("Odrzucony starszy komunikat %s", msg.spot_id)
                return Result("odrzucony", spot_id=msg.spot_id, reason="starszy_niz_ostatni")

            # Pierwszy nowy komunikat po przerwie zamyka aktywny alert.
            closed = t.ex(
                "UPDATE alerty SET czas_zamkniecia = ? WHERE spot_id = ? AND czas_zamkniecia IS NULL",
                (received_at, msg.spot_id),
            ) > 0

            if msg.state != row["stan"]:
                t.ex(
                    "UPDATE miejsca SET stan = ?, odleglosc_cm = ?, czas_zdarzenia = ?, "
                    "czas_ostatniego_komunikatu = ?, czas_zmiany_stanu = ? WHERE spot_id = ?",
                    (msg.state, msg.distance_cm, msg.event_time, received_at, msg.event_time,
                     msg.spot_id),
                )
                t.insert("historia_zmian", {
                    "spot_id": msg.spot_id, "strefa": msg.zone, "nowy_stan": msg.state,
                    "czas_zmiany": msg.event_time, "czas_odebrania": received_at,
                    "zrodlo": msg.msg_type,
                })
                status = "zmiana"
            else:
                # Heartbeat (albo duplikat ZMIANA) zgodny z bazą: tylko czas ostatniego
                # komunikatu; bez wpisu w historii.
                t.ex(
                    "UPDATE miejsca SET odleglosc_cm = ?, czas_zdarzenia = ?, "
                    "czas_ostatniego_komunikatu = ? WHERE spot_id = ?",
                    (msg.distance_cm, msg.event_time, received_at, msg.spot_id),
                )
                status = "bez_zmian"

        if status == "zmiana":
            log.info("%s -> %s (%s, zdarzenie %s)%s", msg.spot_id, msg.state, msg.msg_type,
                     model.to_iso(msg.event_time), "; alert zamknięty" if closed else "")
        return Result(status, spot_id=msg.spot_id, state=msg.state, alert_closed=closed)

    # ------------------------------------------------------------------------------------
    def check_silence(self, now: datetime) -> CheckResult:
        """Funkcja Kontrola (co 10 s): > 3 min bez komunikatu -> BRAK DANYCH + 1 alert."""
        result = CheckResult()
        start_txt = self.db.get_setting("czas_uruchomienia")
        start = model.parse_iso(start_txt) if start_txt else now
        with self.db.tx() as t:
            rows = t.q(
                "SELECT spot_id, strefa, stan, czas_ostatniego_komunikatu FROM miejsca"
                f"{self.db.lock_hint()}"
            )
            active = {r["spot_id"].strip() for r in
                      t.q("SELECT spot_id FROM alerty WHERE czas_zamkniecia IS NULL")}
            for r in rows:
                spot = r["spot_id"].strip()
                last_msg = self.db.ts(r["czas_ostatniego_komunikatu"])
                # Czujnik, który nic nie wysłał od uruchomienia: czas liczony od startu.
                reference = max(last_msg, start) if last_msg else start
                silence = (now - reference).total_seconds()
                if silence <= model.SILENCE_LIMIT_S or spot in active:
                    continue
                if r["stan"] != model.BRAK_DANYCH:
                    t.ex("UPDATE miejsca SET stan = ?, czas_zmiany_stanu = ? WHERE spot_id = ?",
                         (model.BRAK_DANYCH, now, spot))
                    t.insert("historia_zmian", {
                        "spot_id": spot, "strefa": r["strefa"].strip(),
                        "nowy_stan": model.BRAK_DANYCH, "czas_zmiany": now,
                        "czas_odebrania": now, "zrodlo": model.KONTROLA,
                    })
                    result.no_data.append(spot)
                t.insert("alerty", {
                    "spot_id": spot,
                    "czas_ostatniego_komunikatu": last_msg,
                    "czas_otwarcia": now,
                })
                result.alerts_opened.append(spot)
        if len(result.alerts_opened) > 5:
            log.warning("ALERT: %d miejsc bez komunikatu > %d s (%s, ...)",
                        len(result.alerts_opened), model.SILENCE_LIMIT_S,
                        ", ".join(result.alerts_opened[:5]))
        else:
            for spot in result.alerts_opened:
                log.warning("ALERT: %s bez komunikatu > %d s", spot, model.SILENCE_LIMIT_S)
        return result

    # ------------------------------------------------------------------------------------
    def board(self) -> dict:
        """Liczniki stref dla tablicy przy wjeździe (reguła 7 po poprawce z LAB05)."""
        counts = self.db.zone_counts()
        out = {}
        for zone in model.ZONES:
            c = counts[zone]
            out[zone] = {
                "wolne": c[model.WOLNE],
                "zajete": c[model.ZAJETE],
                "brak_danych": c[model.BRAK_DANYCH],
                "napis": model.board_label(c[model.WOLNE], c[model.ZAJETE], c[model.BRAK_DANYCH]),
            }
        return out

    def snapshot_occupancy(self, now: datetime) -> None:
        counts = self.db.zone_counts()
        with self.db.tx() as t:
            for zone in model.ZONES:
                c = counts[zone]
                t.insert("oblozenie_stref", {
                    "czas": now, "strefa": zone, "wolne": c[model.WOLNE],
                    "zajete": c[model.ZAJETE], "brak_danych": c[model.BRAK_DANYCH],
                })
