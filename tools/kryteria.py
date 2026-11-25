"""Uruchamia scenariusze z karty LAB02 i kryteria K1–K5, zapisuje dowody do data/wyniki.

  python tools/kryteria.py            # wszystko (K2 w czasie rzeczywistym, ok. 35 s)
  python tools/kryteria.py --bez-k2   # bez pomiaru w czasie rzeczywistym

Wyniki: CSV z danymi dla każdego kryterium + raport_kryteriow.md / .json.
Czas lokalny w raportach = CET (UTC+1), jak w karcie LAB02.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shutil
import sys
import tempfile
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from parking import model  # noqa: E402
from parking.db import Database  # noqa: E402
from parking.service import ParkingService  # noqa: E402
from simulator.engine import encode  # noqa: E402
from simulator.harness import run_virtual  # noqa: E402
from simulator.scenarios import (SHORT_DETECTIONS, Checkpoint, Offline, scenario_1,  # noqa: E402
                                 scenario_2, scenario_3, scenario_4, scenario_k1, scenario_k3)

OUT = os.path.join(ROOT, "data", "wyniki")
LOGS = os.path.join(ROOT, "data", "logi")
CET = timedelta(hours=1)


def local(dt) -> str:
    return (dt + CET).strftime("%H:%M:%S") if dt else ""


def write_csv(name: str, rows: list[dict]) -> str:
    path = os.path.join(OUT, name)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return path


def save_log(run, name: str) -> None:
    path = os.path.join(LOGS, name)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(run.message_log.rows[0]))
        w.writeheader()
        w.writerows(run.message_log.rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bez-k2", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.ERROR)
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(LOGS, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="parking_kryteria_")
    summary: dict = {"scenariusze": {}, "kryteria": {}}

    def db(name):
        return Database(f"sqlite:///{os.path.join(tmp, name + '.db')}")

    # --- Scenariusze 1–4 + K4 ------------------------------------------------------------------
    k4_rows, sc_rows = [], []
    for factory in (scenario_1, scenario_2, scenario_3, scenario_4):
        sc = factory()
        extra = [Checkpoint(t, f"kontrola K4 t={t:.0f} s")
                 for t in range(30, min(300, int(sc.duration_s)), 30)]
        d = db("sc" + sc.key)
        run = run_virtual(sc, d, extra_checks=extra if sc.key != "4" else None)
        save_log(run, f"scenariusz_{sc.key}.csv")
        for h_name, rows in (("historia", d.history(limit=100000)),):
            write_csv(f"{h_name}_scenariusz_{sc.key}.csv", [{
                "czas_zmiany_utc": model.to_iso(h["czas_zmiany"]), "czas_lokalny": local(h["czas_zmiany"]),
                "miejsce": h["spot_id"], "nowy_stan": h["nowy_stan"], "zrodlo": h["zrodlo"],
                "czas_odebrania_utc": model.to_iso(h["czas_odebrania"]),
            } for h in reversed(rows)])
        ok_main = all(c.ok for c in run.checkpoints if not c.label.startswith("kontrola K4"))
        summary["scenariusze"][sc.key] = {"tytul": sc.title, "wynik": "OK" if ok_main else "BŁĄD"}
        for c in run.checkpoints:
            row = {
                "scenariusz": sc.key, "punkt": c.label, "czas_lokalny": local(c.time_utc),
                "tablica_A": c.board["A"], "tablica_B": c.board["B"], "tablica_C": c.board["C"],
                "sql_wolne_A": c.sql_free["A"], "sql_wolne_B": c.sql_free["B"], "sql_wolne_C": c.sql_free["C"],
                "aktywne_alerty": c.active_alerts, "wynik": "OK" if c.ok else "; ".join(c.problems),
            }
            k4_rows.append(row)
            if not c.label.startswith("kontrola K4"):
                sc_rows.append({**row, "oczekiwane": json.dumps(c.expected, ensure_ascii=False)})
        if sc.key == "3":
            alerts = d.alerts()
            write_csv("alerty_scenariusz_3.csv", [{
                "miejsce": a["spot_id"], "ostatni_komunikat": local(a["czas_ostatniego_komunikatu"]),
                "otwarty": local(a["czas_otwarcia"]), "zamkniety": local(a["czas_zamkniecia"]),
            } for a in alerts])
    write_csv("scenariusze_punkty_kontrolne.csv", sc_rows)
    write_csv("K4_licznik_vs_sql.csv", [r for r in k4_rows if r["scenariusz"] in "123"])
    k4_ok = all(r["wynik"] == "OK" for r in k4_rows if r["scenariusz"] in "123")
    summary["kryteria"]["K4"] = {
        "wynik": "SPEŁNIONE" if k4_ok else "NIESPEŁNIONE",
        "opis": f"{sum(r['wynik'] == 'OK' for r in k4_rows if r['scenariusz'] in '123')} z "
                f"{sum(1 for r in k4_rows if r['scenariusz'] in '123')} punktów kontrolnych zgodnych",
    }

    # --- K1 -------------------------------------------------------------------------------------
    sc = scenario_k1()
    d = db("k1")
    run = run_virtual(sc, d)
    save_log(run, "kryterium_K1.csv")
    sent = [m for m in run.message_log.rows if m["msg_type"] == model.ZMIANA
            and m["spot_id"] in sc.focus and m["event_time_utc"] > "2026-11-24T12:00:39"]
    saved = {(h["spot_id"], h["nowy_stan"], model.to_iso(h["czas_zmiany"])) for h in d.history(limit=100000)}
    k1 = [{"miejsce": m["spot_id"], "strefa": m["zone"], "stan": m["state"], "czas_zdarzenia_utc": m["event_time_utc"],
           "zapisano_w_historii": "TAK" if (m["spot_id"], m["state"], m["event_time_utc"]) in saved else "NIE"}
          for m in sent]
    write_csv("K1_zapis_zmian.csv", k1)
    n_ok = sum(r["zapisano_w_historii"] == "TAK" for r in k1)
    summary["kryteria"]["K1"] = {"wynik": "SPEŁNIONE" if n_ok == 20 == len(k1) else "NIESPEŁNIONE",
                                 "opis": f"{n_ok} z {len(k1)} komunikatów ZMIANA zapisanych"}

    # --- K3 -------------------------------------------------------------------------------------
    sc = scenario_k3()
    d = db("k3")
    run = run_virtual(sc, d)
    save_log(run, "kryterium_K3.csv")
    k3 = []
    for spot, dur in SHORT_DETECTIONS:
        zm = [m for m in run.message_log.rows if m["spot_id"] == spot and m["msg_type"] == model.ZMIANA
              and m["event_time_utc"] > "2026-11-24T13:00:35"]
        hist = [h for h in d.history(spot_id=spot) if model.to_iso(h["czas_zmiany"]) > "2026-11-24T13:00:35"]
        k3.append({"miejsce": spot, "czas_wykrycia_s": dur, "odczyty_ponizej_150": int(dur / 0.5) + 1,
                   "komunikaty_ZMIANA": len(zm), "nowe_wpisy_historii": len(hist)})
    write_csv("K3_krotkie_wykrycia.csv", k3)
    k3_ok = all(r["komunikaty_ZMIANA"] == 0 and r["nowe_wpisy_historii"] == 0 for r in k3)
    summary["kryteria"]["K3"] = {"wynik": "SPEŁNIONE" if k3_ok else "NIESPEŁNIONE",
                                 "opis": f"{len(k3)} wykryć 1–2,5 s: "
                                         f"{sum(r['komunikaty_ZMIANA'] for r in k3)} ZMIANA, "
                                         f"{sum(r['nowe_wpisy_historii'] for r in k3)} nowych wpisów"}

    # --- K5 -------------------------------------------------------------------------------------
    k5 = []
    for phase in (0.0, 2.5, 5.0, 7.5, 9.5):
        sc = scenario_3(20)
        sc.offline = [Offline("C05", 60.0 + phase, sc.offline[0].t_to + phase)]
        sc.boot_offsets["C05"] = phase
        for cp in sc.checkpoints:
            cp.t += phase
        sc.duration_s += phase
        d = db(f"k5_{phase}")
        run = run_virtual(sc, d)
        a = d.alerts()
        c_count = [c.board["C"] for c in run.checkpoints]
        k5.append({
            "przesuniecie_fazy_s": phase, "liczba_alertow": len(a),
            "ostatni_komunikat": local(a[0]["czas_ostatniego_komunikatu"]) if a else "",
            "BRAK_DANYCH_od": local(a[0]["czas_otwarcia"]) if a else "",
            "opoznienie_s": round((a[0]["czas_otwarcia"] - a[0]["czas_ostatniego_komunikatu"]).total_seconds(), 1) if a else "",
            "alert_zamkniety": local(a[0]["czas_zamkniecia"]) if a else "",
            "licznik_C_w_punktach": " → ".join(c_count),
            "punkty_kontrolne_ok": all(c.ok for c in run.checkpoints),
        })
    write_csv("K5_brak_danych.csv", k5)
    k5_ok = all(r["liczba_alertow"] == 1 and 180 < r["opoznienie_s"] <= 190 and r["alert_zamkniety"]
                and r["punkty_kontrolne_ok"] for r in k5)
    summary["kryteria"]["K5"] = {"wynik": "SPEŁNIONE" if k5_ok else "NIESPEŁNIONE",
                                 "opis": f"5 przebiegów: zawsze 1 alert, opóźnienie "
                                         f"{min(r['opoznienie_s'] for r in k5)}–{max(r['opoznienie_s'] for r in k5)} s "
                                         f"(limit 190 s), alert zamknięty przez pierwszy komunikat"}

    # --- Walidacja: przykładowe błędne komunikaty -------------------------------------------------
    d = db("walidacja")
    svc = ParkingService(d)
    now = model.utcnow()
    svc.start(now)
    good = {"spot_id": "B03", "zone": "B", "state": model.ZAJETE, "distance_cm": 60,
            "msg_type": model.ZMIANA, "event_time_utc": model.to_iso(now)}
    cases = [
        ("poprawny komunikat", good, "parking/B/B03"),
        ("nieznane miejsce", {**good, "spot_id": "D07", "zone": "D"}, "parking/B/B03"),
        ("strefa niezgodna", {**good, "zone": "A"}, "parking/B/B03"),
        ("stan spoza listy", {**good, "state": "ZAJETE?"}, "parking/B/B03"),
        ("brak czasu", {k: v for k, v in good.items() if k != "event_time_utc"}, "parking/B/B03"),
        ("czas 5 min w przyszłości", {**good, "event_time_utc": model.to_iso(now + timedelta(minutes=5))}, "parking/B/B03"),
        ("odległość 900 cm", {**good, "distance_cm": 900}, "parking/B/B03"),
        ("temat innego miejsca", good, "parking/B/B04"),
        ("niepoprawny JSON", "{spot_id: B03", "parking/B/B03"),
    ]
    val_rows = []
    for name, payload, topic in cases:
        raw = payload.encode() if isinstance(payload, str) else encode(payload)
        r = svc.handle_message(raw, now, topic=topic)
        val_rows.append({"przypadek": name, "wynik": r.status, "powod": r.reason or "",
                         "stan_B03_po": {s["spot_id"]: s["stan"] for s in d.spots()}["B03"]})
    write_csv("walidacja_odrzucone.csv", val_rows)
    summary["walidacja"] = f"{sum(r['wynik'] == 'odrzucony' for r in val_rows)} z {len(val_rows) - 1} błędnych odrzuconych"

    # --- K2 (czas rzeczywisty) ---------------------------------------------------------------------
    if not args.bez_k2:
        from simulator.k2 import measure_k2

        rows = measure_k2(ParkingService(db("k2")))
        write_csv("K2_opoznienie_widoku.csv", [{
            "miejsce": r.spot, "stan": r.state, "odebrano_utc": r.received_utc, "widoczne_utc": r.visible_utc,
            "opoznienie_s": r.delay_s, "do_5_s": "TAK" if r.ok else "NIE"} for r in rows])
        k2_ok = len(rows) == 10 and all(r.ok for r in rows)
        delays = [r.delay_s for r in rows]
        summary["kryteria"]["K2"] = {"wynik": "SPEŁNIONE" if k2_ok else "NIESPEŁNIONE",
                                     "opis": f"{sum(r.ok for r in rows)} z 10 zmian widocznych ≤ 5 s "
                                             f"(śr. {sum(delays) / len(delays):.2f} s, maks. {max(delays):.2f} s, "
                                             f"odpytywanie co 2 s)"}

    summary["kryteria"] = dict(sorted(summary["kryteria"].items()))
    with open(os.path.join(OUT, "raport_kryteriow.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    lines = ["# Raport kryteriów sukcesu (LAB02, cz. 8)", "",
             f"Wygenerowano: {local(model.utcnow())} (CET), `python tools/kryteria.py`", "",
             "| Kryterium | Wynik | Szczegóły |", "|---|---|---|"]
    for k, v in summary["kryteria"].items():
        lines.append(f"| {k} | {v['wynik']} | {v['opis']} |")
    lines += ["", "| Scenariusz | Wynik |", "|---|---|"]
    for k, v in summary["scenariusze"].items():
        lines.append(f"| {v['tytul']} | {v['wynik']} |")
    lines += ["", f"Walidacja: {summary['walidacja']}.", "",
              "Pliki z danymi: `data/wyniki/*.csv`, logi symulatora: `data/logi/*.csv`."]
    with open(os.path.join(OUT, "raport_kryteriow.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
