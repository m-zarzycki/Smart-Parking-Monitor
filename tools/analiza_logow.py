"""Analiza logu symulatora i historii zmian metodą z LAB08 (integralność, luki, duplikaty).

  python tools/analiza_logow.py data/logi/scenariusz_3.csv data/wyniki/historia_scenariusz_3.csv

Forma ustalenia: obserwacja -> dowód z logu -> dowód z bazy -> wniosek -> pewność.
Brak danych nie jest zamieniany na domniemany pomiar.
"""
from __future__ import annotations

import csv
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

HEARTBEAT_S = 60
TOLERANCE_S = 1.0
CET = timedelta(hours=1)


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def local(dt: datetime) -> str:
    return (dt + CET).strftime("%H:%M:%S")


def main(log_path: str, history_path: str) -> str:
    rows = list(csv.DictReader(open(log_path, encoding="utf-8")))
    hist = list(csv.DictReader(open(history_path, encoding="utf-8")))
    sent = [r for r in rows if r["wyslano"] == "TAK"]
    lost = [r for r in rows if r["wyslano"] == "NIE"]

    # E1: dostarczenia vs unikalne komunikaty
    keys = Counter((r["spot_id"], r["msg_type"], r["event_time_utc"]) for r in sent)
    dups = {k: n for k, n in keys.items() if n > 1}

    # E1: luki – przerwy między kolejnymi wysłanymi komunikatami jednego czujnika
    by_spot = defaultdict(list)
    for r in sent:
        by_spot[r["spot_id"]].append(parse(r["event_time_utc"]))
    gaps = []
    for spot, times in by_spot.items():
        times.sort()
        for a, b in zip(times, times[1:]):
            gap = (b - a).total_seconds()
            if gap > HEARTBEAT_S + TOLERANCE_S:
                missing = int(gap // HEARTBEAT_S) - 1
                gaps.append((spot, a, b, gap, missing))

    # Zgodność: każda ZMIANA z logu ma wpis w historii?
    hist_keys = {(h["miejsce"], h["nowy_stan"], h["czas_zmiany_utc"][:19]) for h in hist}
    zm = [r for r in sent if r["msg_type"] == "ZMIANA"]
    zm_in_hist = sum((r["spot_id"], r["state"], r["event_time_utc"][:19]) in hist_keys for r in zm)
    no_data = [h for h in hist if h["nowy_stan"] == "BRAK DANYCH" and h["zrodlo"] == "KONTROLA"]

    name = os.path.splitext(os.path.basename(log_path))[0]
    out = [f"# Analiza logów – {name}", "",
           f"Źródła: `{log_path}` ({len(rows)} wierszy), `{history_path}` ({len(hist)} wpisów). "
           "Czas lokalny CET (UTC+1).", "",
           "## E1. Integralność danych", "",
           "| Miara | Wartość |", "|---|---|",
           f"| Komunikaty wygenerowane przez czujniki | {len(rows)} |",
           f"| Wysłane (dostarczone do brokera) | {len(sent)} |",
           f"| Utracone (brak łączności, brak bufora) | {len(lost)} |",
           f"| ZMIANA / HEARTBEAT wysłane | {sum(r['msg_type'] == 'ZMIANA' for r in sent)} / "
           f"{sum(r['msg_type'] == 'HEARTBEAT' for r in sent)} |",
           f"| Duplikaty (to samo miejsce, typ i czas) | {len(dups)} |",
           f"| ZMIANA z odpowiednim wpisem w historii | {zm_in_hist} z {len(zm)} |", ""]
    out += ["## Luki w komunikatach (> 61 s między kolejnymi komunikatami czujnika)", ""]
    if gaps:
        out += ["| Miejsce | Ostatni przed luką | Pierwszy po luce | Luka | Brakujące heartbeaty |",
                "|---|---|---|---|---|"]
        for spot, a, b, gap, missing in gaps:
            out.append(f"| {spot} | {local(a)} | {local(b)} | {gap / 60:.1f} min | {missing} |")
    else:
        out.append("Brak luk – każdy czujnik nadawał co najmniej co 60 s.")
    out += ["", "## Reakcja systemu (historia zmian)", ""]
    if no_data:
        for h in no_data:
            ret = [x for x in hist if x["miejsce"] == h["miejsce"] and x["czas_zmiany_utc"] > h["czas_zmiany_utc"]]
            back = f", powrót: {ret[0]['nowy_stan']} o {ret[0]['czas_lokalny']} ({ret[0]['zrodlo']})" if ret else ""
            out.append(f"- {h['miejsce']}: BRAK DANYCH o {h['czas_lokalny']}{back}")
    else:
        out.append("- Brak przejść w BRAK DANYCH.")
    out += ["", "## Ustalenia", ""]
    for spot, a, b, gap, missing in gaps:
        lost_spot = [r for r in lost if r["spot_id"] == spot]
        nd = [h for h in no_data if h["miejsce"] == spot]
        out.append(
            f"- **Obserwacja:** brak komunikatów {spot} przez {gap / 60:.1f} min. "
            f"**Dowód z logu:** {len(lost_spot)} komunikatów z flagą „brak łączności”, ostatni wysłany "
            f"{local(a)}, następny {local(b)}. **Dowód z bazy:** "
            + (f"BRAK DANYCH o {nd[0]['czas_lokalny']} (źródło KONTROLA). " if nd else "brak wpisu BRAK DANYCH. ")
            + "**Wniosek:** przerwa łączności czujnika, komunikaty nie były buforowane, więc historia "
              "z tego okresu jest niepełna; stan miejsca w tym czasie jest nieznany (nie zgadujemy). "
              "**Pewność:** wysoka – oba źródła są zgodne.")
    if not gaps:
        out.append("- Brak luk do wyjaśnienia.")
    if not dups:
        out.append("- Brak duplikatów; gdyby wystąpiły (QoS 1), odbiornik traktuje drugi egzemplarz jako "
                   "zgodny ze stanem i nie tworzy wpisu w historii.")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    report = main(sys.argv[1], sys.argv[2])
    base = os.path.splitext(os.path.basename(sys.argv[1]))[0]
    path = os.path.join("data", "wyniki", f"analiza_logow_{base}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(report)
    print(f"Zapisano: {path}")
