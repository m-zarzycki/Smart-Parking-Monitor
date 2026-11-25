"""Scenariusze testowe z karty LAB02 (cz. 7) i scenariusze do kryteriów K1, K3.

Czasy w scenariuszach to przesunięcia w sekundach od uruchomienia czujników.
`nominal_start_utc` mapuje je na godziny z karty (Polska zimą = UTC+1, więc
09:00 czasu lokalnego = 08:00 UTC). W trybie czasu rzeczywistego start = teraz.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from parking import model


@dataclass
class Event:
    """Odległość `distance_cm` na miejscu `spot` w przedziale [t_from, t_to] (t_to=None: do końca)."""
    spot: str
    t_from: float
    t_to: Optional[float]
    distance_cm: float


@dataclass
class Offline:
    """Brak łączności czujnika w przedziale (t_from, t_to) – komunikaty przepadają."""
    spot: str
    t_from: float
    t_to: float


@dataclass
class Checkpoint:
    t: float
    label: str
    board: dict = field(default_factory=dict)        # strefa -> napis na tablicy
    states: dict = field(default_factory=dict)       # miejsce -> stan w bazie
    active_alerts: Optional[int] = None              # liczba aktywnych alertów


@dataclass
class Scenario:
    key: str
    title: str
    description: str
    nominal_start_utc: datetime
    duration_s: float
    free_spots: set
    events: list = field(default_factory=list)
    offline: list = field(default_factory=list)
    boot_offsets: dict = field(default_factory=dict)  # miejsce -> przesunięcie startu [s]
    checkpoints: list = field(default_factory=list)
    focus: tuple = ()                                  # miejsca opisane w scenariuszu

    # -- profil odległości -----------------------------------------------------------
    def base_distance(self, spot: str, tick: int) -> float:
        h = int(hashlib.sha256(spot.encode()).hexdigest()[:6], 16)
        jitter = ((h + tick * 7919) % 9) - 4  # deterministyczny szum ±4 cm
        if spot in self.free_spots:
            return 240 + h % 150 + jitter      # pusty miejsce: 236–393 cm (ziemia / ściana)
        return 45 + h % 70 + jitter            # pojazd: 41–118 cm

    def distance(self, spot: str, t: float, tick: int) -> float:
        value = self.base_distance(spot, tick)
        for ev in self.events:
            if ev.spot == spot and t >= ev.t_from - 1e-9 and (ev.t_to is None or t <= ev.t_to + 1e-9):
                value = ev.distance_cm
        return value

    def online(self, spot: str, t: float) -> bool:
        return not any(o.spot == spot and o.t_from < t < o.t_to for o in self.offline)

    def boot_offset(self, spot: str) -> float:
        if spot in self.boot_offsets:
            return self.boot_offsets[spot]
        # Rozłożenie startu czujników na 0–29,5 s, aby heartbeaty nie szły jednocześnie.
        idx = model.ALL_SPOTS.index(spot)
        return ((idx * 13) % 60) * 0.5


def _utc(y, mo, d, h, mi, s=0) -> datetime:
    return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)


def _zone_spots(zone: str, numbers) -> set:
    return {f"{zone}{n:02d}" for n in numbers}


# ---------------------------------------------------------------------------------------------
def scenario_1() -> Scenario:
    # Strefa B ma 5 wolnych miejsc, w tym B03. Czujniki startują o 08:59:00 (czasu lokalnego).
    free = _zone_spots("A", [4, 11, 27]) | _zone_spots("B", [3, 7, 12, 18, 25]) | \
        _zone_spots("C", [2, 5, 9, 14, 20, 23, 29])
    return Scenario(
        key="1",
        title="Scenariusz 1 – zwykła praca",
        description="B03 mierzy 60 cm od 09:00:00 do 09:00:03; o 09:01:00 heartbeat B03 ZAJĘTE.",
        nominal_start_utc=_utc(2026, 11, 24, 7, 59, 0),   # 08:59:00 czasu lokalnego
        duration_s=150,
        free_spots=free,
        events=[Event("B03", 60.0, None, 60)],             # od 09:00:00 pojazd na B03
        boot_offsets={"B03": 0.0},                         # heartbeat B03 o 09:00:00 i 09:01:00
        checkpoints=[
            Checkpoint(59.0, "08:59:59 – przed zmianą", board={"A": "3", "B": "5", "C": "7"},
                       states={"B03": model.WOLNE}, active_alerts=0),
            Checkpoint(68.0, "09:00:08 – po ZMIANA B03", board={"A": "3", "B": "4", "C": "7"},
                       states={"B03": model.ZAJETE}, active_alerts=0),
            Checkpoint(125.0, "09:01:05 – po heartbeat B03", board={"A": "3", "B": "4", "C": "7"},
                       states={"B03": model.ZAJETE}, active_alerts=0),
        ],
        focus=("B03",),
    )


def scenario_2() -> Scenario:
    # O 08:40 wolne: A – 1 (A06), B – 4, C – 7. Start czujników 08:39:00.
    free = {"A06"} | _zone_spots("B", [5, 9, 16, 28]) | _zone_spots("C", [1, 6, 10, 15, 19, 24, 30])
    return Scenario(
        key="2",
        title="Scenariusz 2 – strefa A się zapełnia",
        description="A06 mierzy 50 cm od 08:40:00 do 08:40:03; o 09:30 A02 >= 200 cm przez 3 s.",
        nominal_start_utc=_utc(2026, 11, 24, 7, 39, 0),   # 08:39:00 czasu lokalnego
        duration_s=3080,                                   # do 09:30:20
        free_spots=free,
        events=[
            Event("A06", 60.0, None, 50),                  # 08:40:00 pojazd na A06
            Event("A02", 3060.0, None, 310),               # 09:30:00 A02 zwolnione
        ],
        boot_offsets={"A06": 0.0, "A02": 0.0},
        checkpoints=[
            Checkpoint(59.0, "08:39:59 – stan początkowy", board={"A": "1", "B": "4", "C": "7"},
                       states={"A06": model.WOLNE}, active_alerts=0),
            Checkpoint(68.0, "08:40:08 – A06 zajęte", board={"A": model.PELNA, "B": "4", "C": "7"},
                       states={"A06": model.ZAJETE}, active_alerts=0),
            Checkpoint(1800.0, "09:09:00 – strefa A pełna", board={"A": model.PELNA, "B": "4", "C": "7"},
                       active_alerts=0),
            Checkpoint(3068.0, "09:30:08 – A02 wolne", board={"A": "1", "B": "4", "C": "7"},
                       states={"A02": model.WOLNE}, active_alerts=0),
        ],
        focus=("A06", "A02"),
    )


def scenario_3(gap_minutes: float = 20.0) -> Scenario:
    # C05 jest WOLNE, strefa C ma 7 wolnych. Start czujników 10:59:00.
    free = _zone_spots("A", [3, 8, 21]) | _zone_spots("B", [2, 11, 19, 26]) | \
        _zone_spots("C", [5, 8, 12, 17, 22, 26, 30])
    back = 60.0 + gap_minutes * 60.0                       # 11:00:00 + przerwa
    end = back + 30.0
    cps = [
        Checkpoint(59.0, "10:59:59 – stan początkowy", board={"A": "3", "B": "4", "C": "7"},
                   states={"C05": model.WOLNE}, active_alerts=0),
        Checkpoint(60.0 + 175.0, "11:02:55 – jeszcze przed limitem 3 min",
                   board={"C": "7"}, states={"C05": model.WOLNE}, active_alerts=0),
        Checkpoint(60.0 + 195.0, "11:03:15 – po kontroli: BRAK DANYCH",
                   board={"C": "6"}, states={"C05": model.BRAK_DANYCH}, active_alerts=1),
    ]
    if gap_minutes >= 10:
        cps.append(Checkpoint(60.0 + 600.0, "11:10:00 – nadal jeden alert",
                              board={"C": "6"}, states={"C05": model.BRAK_DANYCH}, active_alerts=1))
    cps.append(Checkpoint(back - 5.0, "tuż przed powrotem – jeden alert",
                          board={"C": "6"}, states={"C05": model.BRAK_DANYCH}, active_alerts=1))
    cps.append(Checkpoint(back + 5.0, "po heartbeat C05 – alert zamknięty",
                          board={"A": "3", "B": "4", "C": "7"}, states={"C05": model.WOLNE},
                          active_alerts=0))
    return Scenario(
        key="3",
        title="Scenariusz 3 – awaria czujnika",
        description=(f"Ostatni heartbeat C05 o 11:00:00, potem {gap_minutes:g} min bez komunikatów; "
                     "pierwszy heartbeat po przerwie z WOLNE."),
        nominal_start_utc=_utc(2026, 11, 24, 9, 59, 0),   # 10:59:00 czasu lokalnego
        duration_s=end,
        free_spots=free,
        offline=[Offline("C05", 60.0, back)],
        boot_offsets={"C05": 0.0},
        checkpoints=cps,
        focus=("C05",),
    )


def scenario_4() -> Scenario:
    # Dodatkowy: krótkie wykrycie. B04 jest WOLNE; o 09:05:00 pieszy 80 cm przez 1,5 s.
    free = _zone_spots("A", [4, 11, 27]) | _zone_spots("B", [4, 7, 12, 18, 25]) | \
        _zone_spots("C", [2, 5, 9, 14, 20, 23, 29])
    return Scenario(
        key="4",
        title="Scenariusz dodatkowy – krótkie wykrycie",
        description="Pieszy przed czujnikiem B04: 80 cm przez 1,5 s, potem >= 200 cm.",
        nominal_start_utc=_utc(2026, 11, 24, 8, 4, 0),    # 09:04:00 czasu lokalnego
        duration_s=80,
        free_spots=free,
        events=[Event("B04", 60.0, 61.5, 80)],
        boot_offsets={"B04": 0.0},
        checkpoints=[
            Checkpoint(59.0, "09:04:59 – przed wykryciem", board={"B": "5"}, states={"B04": model.WOLNE}),
            Checkpoint(70.0, "09:05:10 – po wykryciu", board={"B": "5"}, states={"B04": model.WOLNE},
                       active_alerts=0),
        ],
        focus=("B04",),
    )


def scenario_k1() -> Scenario:
    """K1: 20 komunikatów ZMIANA z różnych miejsc i stref po rozgrzaniu systemu."""
    free = _zone_spots("A", [1, 5, 9, 13, 17]) | _zone_spots("B", [2, 6, 10, 14, 18]) | \
        _zone_spots("C", [3, 7, 11, 15, 19])
    events = []
    # 10 miejsc wolnych zajmuje pojazd, 10 zajętych się zwalnia; co 8 s jedna zmiana.
    to_occupy = ["A01", "B02", "C03", "A05", "B06", "C07", "A09", "B10", "C11", "A13"]
    to_free = ["A02", "B03", "C04", "A06", "B07", "C08", "A10", "B11", "C12", "A14"]
    t = 40.0
    for a, b in zip(to_occupy, to_free):
        events.append(Event(a, t, None, 70))
        t += 8.0
        events.append(Event(b, t, None, 320))
        t += 8.0
    return Scenario(
        key="k1",
        title="Kryterium K1 – 20 komunikatów ZMIANA",
        description="20 zmian stanu na 20 różnych miejscach w strefach A, B, C (co 8 s).",
        nominal_start_utc=_utc(2026, 11, 24, 12, 0, 0),
        duration_s=t + 20.0,
        free_spots=free,
        events=events,
        focus=tuple(to_occupy + to_free),
    )


SHORT_DETECTIONS = [  # (miejsce, czas trwania wykrycia w s) – K3
    ("A03", 1.0), ("A12", 1.5), ("A25", 2.0), ("B05", 2.5), ("B13", 1.0),
    ("B21", 2.0), ("C06", 1.5), ("C16", 2.5), ("C27", 1.0), ("A30", 2.5),
]


def scenario_k3() -> Scenario:
    """K3: 10 krótkich wykryć 1–2,5 s na wolnych miejscach – żadna zmiana stanu."""
    free = {s for s, _ in SHORT_DETECTIONS} | _zone_spots("B", [8, 9]) | _zone_spots("C", [1])
    events = []
    t = 40.0
    for spot, dur in SHORT_DETECTIONS:
        events.append(Event(spot, t, t + dur, 85))
        t += 6.0
    return Scenario(
        key="k3",
        title="Kryterium K3 – krótkie wykrycia",
        description="10 obiektów przed czujnikiem przez 1–2,5 s (pieszy, przejeżdżający samochód).",
        nominal_start_utc=_utc(2026, 11, 24, 13, 0, 0),
        duration_s=t + 15.0,
        free_spots=free,
        events=events,
        focus=tuple(s for s, _ in SHORT_DETECTIONS),
    )


SCENARIOS = {
    "1": scenario_1,
    "2": scenario_2,
    "3": scenario_3,
    "4": scenario_4,
    "k1": scenario_k1,
    "k3": scenario_k3,
}
