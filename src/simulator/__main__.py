"""Symulator 90 czujników parkingowych.

Przykłady:
  python -m simulator ruch                          # losowy ruch na żywo -> MQTT
  python -m simulator ruch --awarie                 # + rzadkie awarie łączności
  python -m simulator scenariusz 1                  # scenariusz 1 w czasie rzeczywistym -> MQTT
  python -m simulator scenariusz 3 --przerwa-min 4  # scenariusz 3 ze skróconą przerwą
  python -m simulator scenariusz 2 --wyjscie stdout --wirtualnie   # podgląd komunikatów
  python -m simulator ruch --wyjscie iothub         # tryb Azure (IoT Hub)
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime

from parking.config import get_settings

from .engine import MessageLog, TrafficModel, run_scenario, run_traffic
from .publishers import IoTHubPublisher, MqttPublisher, StdoutPublisher
from .scenarios import SCENARIOS, scenario_3


def make_publisher(kind: str):
    s = get_settings()
    if kind == "mqtt":
        if not s.mqtt_sensor_password:
            logging.warning("Brak MQTT_SENSOR_PASSWORD w .env – broker z logowaniem odrzuci połączenie")
        return MqttPublisher(s.mqtt_host, s.mqtt_port, s.mqtt_sensor_user, s.mqtt_sensor_password,
                             tls=s.mqtt_tls, ca_file=s.mqtt_ca_file)
    if kind == "iothub":
        return IoTHubPublisher(os.environ.get("IOTHUB_DEVICE_CONNECTION_STRING", ""),
                               max_messages=int(os.environ.get("IOTHUB_MAX_MESSAGES", "7000")))
    return StdoutPublisher()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m simulator", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="tryb", required=True)

    p_ruch = sub.add_parser("ruch", help="losowy ruch w czasie rzeczywistym")
    p_ruch.add_argument("--zmiany-na-minute", type=float, default=6.0)
    p_ruch.add_argument("--piesi-na-minute", type=float, default=2.0)
    p_ruch.add_argument("--awarie", action="store_true", help="rzadkie przerwy łączności czujników")
    p_ruch.add_argument("--czas", type=float, default=None, help="czas trwania w sekundach")
    p_ruch.add_argument("--ziarno", type=int, default=2)

    p_sc = sub.add_parser("scenariusz", help="scenariusz z karty LAB02 albo kryterium")
    p_sc.add_argument("numer", choices=sorted(SCENARIOS))
    p_sc.add_argument("--przerwa-min", type=float, default=20.0, help="długość przerwy w scenariuszu 3")
    p_sc.add_argument("--wirtualnie", action="store_true",
                      help="bez czekania (czasy z karty LAB02); tylko z --wyjscie stdout")

    for p in (p_ruch, p_sc):
        p.add_argument("--wyjscie", choices=["mqtt", "iothub", "stdout"], default="mqtt")
        p.add_argument("--log", default=None, help="plik CSV z logiem komunikatów")

    args = parser.parse_args()
    logging.basicConfig(level=get_settings().log_level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = args.log or os.path.join("data", "logi", f"symulator_{args.tryb}_{stamp}.csv")
    mlog = MessageLog(log_path)
    publisher = make_publisher(args.wyjscie)
    try:
        if args.tryb == "ruch":
            traffic = TrafficModel(seed=args.ziarno, changes_per_minute=args.zmiany_na_minute,
                                   pedestrians_per_minute=args.piesi_na_minute, failures=args.awarie)
            run_traffic(publisher, traffic, duration_s=args.czas, message_log=mlog)
        else:
            sc = scenario_3(args.przerwa_min) if args.numer == "3" else SCENARIOS[args.numer]()
            logging.info("%s: %s", sc.title, sc.description)
            realtime = not args.wirtualnie
            if args.wirtualnie and args.wyjscie != "stdout":
                raise SystemExit("--wirtualnie działa tylko z --wyjscie stdout "
                                 "(backend odrzuciłby czasy z przeszłości/przyszłości)")
            run_scenario(sc, publisher, realtime=realtime, message_log=mlog)
    finally:
        publisher.close()
        mlog.close()
        logging.info("Log komunikatów: %s (%d wierszy)", log_path, len(mlog.rows))


if __name__ == "__main__":
    main()
