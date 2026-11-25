"""Uruchamianie systemu w trybie lokalnym.

  python -m parking init                 # utworzenie bazy (SQLite albo Azure SQL z DATABASE_URL)
  python -m parking uzytkownik zarzadca  # konto zarządcy (hasło podawane interaktywnie)
  python -m parking start                # odbiornik MQTT + kontrola co 10 s + aplikacja web
  python -m parking odbiornik            # tylko odbiornik MQTT + kontrola
  python -m parking web                  # tylko aplikacja web
  python -m parking demo                 # bez brokera: symulator w tym samym procesie + web
  python -m parking historia-demo        # syntetyczne próbki obłożenia z 7 dni (wykres w panelu)
"""
from __future__ import annotations

import argparse
import csv
import getpass
import logging
import math
import os
import random
import sys
import threading
from datetime import timedelta

from werkzeug.security import generate_password_hash

from . import model
from .config import get_settings
from .db import Database
from .service import ParkingService
from .worker import SilenceChecker

log = logging.getLogger("parking")


def make_service(settings) -> ParkingService:
    return ParkingService(Database(settings.database_url), gateway_ids=settings.gateway_ids)


def run_web(service: ParkingService, settings) -> None:
    from .web import create_app

    app = create_app(service, settings.secret_key,
                     cookie_secure=os.environ.get("SESSION_COOKIE_SECURE", "false") == "true")
    log.info("Aplikacja web: http://%s:%d  (tablica /, mapa /mapa, panel /panel)",
             settings.web_host, settings.web_port)
    app.run(host=settings.web_host, port=settings.web_port, threaded=True, use_reloader=False)


def cmd_init(service, settings, args) -> None:
    service.db.init_schema()
    added = service.db.seed_spots(model.utcnow())
    print(f"Baza gotowa ({service.db.dialect}). Dodano miejsc: {added}.")


def cmd_user(service, settings, args) -> None:
    service.db.init_schema()
    password = getpass.getpass(f"Hasło dla {args.login} (min. 10 znaków): ")
    if len(password) < 10:
        sys.exit("Hasło za krótkie.")
    if password != getpass.getpass("Powtórz hasło: "):
        sys.exit("Hasła się różnią.")
    service.db.upsert_user(args.login, generate_password_hash(password), "zarzadca", model.utcnow())
    print(f"Zapisano konto zarządcy: {args.login} (w bazie tylko skrót hasła).")


def start_checker(service) -> threading.Event:
    stop = threading.Event()
    SilenceChecker(service, stop).start()
    return stop


def cmd_receiver(service, settings, args, with_web: bool = False) -> None:
    from .worker import MqttReceiver

    service.start(model.utcnow(), reset=not args.bez_resetu)
    start_checker(service)
    receiver = MqttReceiver(service, settings)
    if with_web:
        receiver.start_background()
        run_web(service, settings)
    else:
        receiver.run_forever()


def cmd_web(service, settings, args) -> None:
    service.db.init_schema()
    service.db.seed_spots(model.utcnow())
    run_web(service, settings)


def cmd_demo(service, settings, args) -> None:
    """Tryb awaryjny na obronę: bez brokera MQTT, wszystko w jednym procesie."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from simulator.engine import TrafficModel, run_traffic

    service.start(model.utcnow())
    start_checker(service)

    def sink(topic, payload, msg, now):
        service.handle_message(payload, model.utcnow(), topic=topic)

    traffic = TrafficModel(seed=args.ziarno, changes_per_minute=args.zmiany_na_minute,
                           failures=args.awarie)
    threading.Thread(target=run_traffic, args=(sink, traffic), name="symulator", daemon=True).start()
    log.warning("TRYB DEMO: symulator działa w tym samym procesie, bez brokera MQTT")
    run_web(service, settings)


def cmd_history_demo(service, settings, args) -> None:
    """Syntetyczne próbki obłożenia co 5 min z ostatnich N dni (oznaczone jako syntetyczne)."""
    service.db.init_schema()
    service.db.seed_spots(model.utcnow())
    rng = random.Random(args.ziarno)
    end = model.utcnow().replace(second=0, microsecond=0)
    end -= timedelta(minutes=end.minute % 5)
    start = end - timedelta(days=args.dni)
    out_path = os.path.join("data", "historia_7dni_syntetyczna.csv")
    os.makedirs("data", exist_ok=True)
    rows = []
    noise = {"A": 0, "B": 0, "C": 0}
    t = start
    while t < end:
        local = t + timedelta(hours=1)  # CET (zima)
        hour = local.hour + local.minute / 60
        weekday = local.weekday() < 5
        # Obłożenie: szczyt 8–10 w dni robocze, spadek po 16, noce i weekendy prawie puste.
        peak = math.exp(-((hour - 9.5) / 2.2) ** 2) if weekday else 0.15 * math.exp(-((hour - 12) / 3) ** 2)
        day = (0.55 if weekday else 0.1) * (1 if 7 <= hour <= 17 else 0.2)
        level = min(1.0, max(peak, day))
        for zone, pref in (("A", 1.15), ("B", 0.95), ("C", 0.75)):
            noise[zone] = max(-2, min(2, noise[zone] + rng.choice((-1, 0, 0, 0, 1))))
            occupied = min(30, max(0, round(30 * min(1.0, level * pref)) + noise[zone]))
            rows.append({"czas": t, "strefa": zone, "wolne": 30 - occupied, "zajete": occupied,
                         "brak_danych": 0})
        t += timedelta(minutes=5)
    with service.db.tx() as tx:
        for r in rows:
            tx.insert("oblozenie_stref", r)
    fmt = "%d.%m.%Y %H:%M"
    service.db.set_setting("dane_syntetyczne", f"{(start + timedelta(hours=1)).strftime(fmt)} – "
                                               f"{(end + timedelta(hours=1)).strftime(fmt)} CET")
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["czas_utc", "strefa", "wolne", "zajete", "brak_danych"])
        w.writeheader()
        for r in rows:
            w.writerow({"czas_utc": model.to_iso(r["czas"]), "strefa": r["strefa"], "wolne": r["wolne"],
                        "zajete": r["zajete"], "brak_danych": r["brak_danych"]})
    print(f"Dodano {len(rows)} syntetycznych próbek ({args.dni} dni). CSV: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m parking", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p_user = sub.add_parser("uzytkownik")
    p_user.add_argument("login")
    for name in ("start", "odbiornik"):
        p = sub.add_parser(name)
        p.add_argument("--bez-resetu", action="store_true",
                       help="nie ustawiaj BRAK DANYCH przy starcie (reguła 1)")
    sub.add_parser("web")
    p_demo = sub.add_parser("demo")
    p_demo.add_argument("--zmiany-na-minute", type=float, default=8.0)
    p_demo.add_argument("--awarie", action="store_true")
    p_demo.add_argument("--ziarno", type=int, default=2)
    p_hist = sub.add_parser("historia-demo")
    p_hist.add_argument("--dni", type=int, default=7)
    p_hist.add_argument("--ziarno", type=int, default=7)
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(level=settings.log_level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    service = make_service(settings)

    if args.cmd == "init":
        cmd_init(service, settings, args)
    elif args.cmd == "uzytkownik":
        cmd_user(service, settings, args)
    elif args.cmd == "start":
        cmd_receiver(service, settings, args, with_web=True)
    elif args.cmd == "odbiornik":
        cmd_receiver(service, settings, args, with_web=False)
    elif args.cmd == "web":
        cmd_web(service, settings, args)
    elif args.cmd == "demo":
        cmd_demo(service, settings, args)
    elif args.cmd == "historia-demo":
        cmd_history_demo(service, settings, args)


if __name__ == "__main__":
    main()
