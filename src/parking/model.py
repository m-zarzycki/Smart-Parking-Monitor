"""Stałe i reguły domenowe wspólne dla symulatora, odbiornika, kontroli i aplikacji.

Źródło: karta założeń LAB02 (cz. 6) oraz diagram LAB05, strona 3_Przeplyw_danych.
Wszystkie czasy w systemie są przechowywane w UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone

# --- Układ parkingu (LAB02, cz. 2) ---------------------------------------
ZONES = ("A", "B", "C")
SPOTS_PER_ZONE = 30
ZONE_DESCRIPTIONS = {
    "A": "przy wjeździe",
    "B": "za budynkiem",
    "C": "najdalej od wjazdu",
}
ALL_SPOTS = tuple(f"{z}{n:02d}" for z in ZONES for n in range(1, SPOTS_PER_ZONE + 1))

# --- Stany miejsca ----------------------------------------------------------
ZAJETE = "ZAJĘTE"
WOLNE = "WOLNE"
BRAK_DANYCH = "BRAK DANYCH"
DEVICE_STATES = (ZAJETE, WOLNE)            # stany, które może zgłosić czujnik
ALL_STATES = (ZAJETE, WOLNE, BRAK_DANYCH)  # stany w bazie

# --- Typy komunikatów ---------------------------------------------------------
ZMIANA = "ZMIANA"
HEARTBEAT = "HEARTBEAT"
MSG_TYPES = (ZMIANA, HEARTBEAT)
KONTROLA = "KONTROLA"  # źródło wpisu w historii utworzonego przez funkcję Kontrola

# --- Reguły decyzji (LAB02, cz. 6) ----------------------------------------------
SAMPLE_PERIOD_S = 0.5          # pomiar lokalny co 0,5 s
CONFIRM_SAMPLES = 7            # 7 kolejnych odczytów = 3 s (0; 0,5; ... 3,0)
OCCUPIED_BELOW_CM = 150        # ZAJĘTE: wszystkie odczyty < 150 cm
FREE_FROM_CM = 200             # WOLNE: wszystkie odczyty >= 200 cm
HEARTBEAT_PERIOD_S = 60        # heartbeat co 60 s
SILENCE_LIMIT_S = 180          # > 3 min bez komunikatu => BRAK DANYCH
CHECK_PERIOD_S = 10            # funkcja Kontrola co 10 s

# --- Walidacja rekordu (LAB05, strona 3) --------------------------------------
DISTANCE_MIN_CM = 0
DISTANCE_MAX_CM = 450
MAX_FUTURE_SKEW_S = 60         # czas zdarzenia > 1 min w przyszłości = błąd

# --- Format komunikatu ----------------------------------------------------------
MESSAGE_FIELDS = ("spot_id", "zone", "state", "distance_cm", "msg_type", "event_time_utc")
TOPIC_PREFIX = "parking"       # temat MQTT: parking/{zone}/{spot_id}


def zone_of(spot_id: str) -> str:
    return spot_id[0]


def topic_for(spot_id: str) -> str:
    return f"{TOPIC_PREFIX}/{zone_of(spot_id)}/{spot_id}"


# --- Tablica przy wjeździe (reguła 7 po poprawce z LAB05) -------------------------
PELNA = "PEŁNA"


def board_label(free: int, occupied: int, no_data: int) -> str:
    """Napis dla strefy na tablicy.

    Licznik > 0 -> liczba wolnych miejsc.
    Licznik = 0 i wszystkie miejsca ZAJĘTE -> PEŁNA.
    Licznik = 0 i część miejsc ma BRAK DANYCH -> BRAK DANYCH
    (zmiana reguły 7 z karty LAB02 po przeglądzie w LAB05).
    """
    if free > 0:
        return str(free)
    if no_data > 0:
        return BRAK_DANYCH
    return PELNA


# --- Czas ---------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    """UTC w formacie ISO 8601 z 'Z' i milisekundami."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parsuje czas ISO 8601. Wymaga strefy czasowej (np. 'Z' albo '+01:00')."""
    if not isinstance(value, str) or not value:
        raise ValueError("pusty czas")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("czas bez strefy czasowej")
    return dt.astimezone(timezone.utc)
