"""Pomiar K2 w czasie rzeczywistym: od odebrania komunikatu w chmurze do pojawienia się
nowego stanu w widoku, który odpytuje /api/stan co 2 s (tak jak tablica i mapa).

Uruchamia aplikację web na losowym porcie, wysyła 10 kolejnych zmian stanu i mierzy,
po ilu sekundach od `czas_odebrania` widok dostaje nowy stan.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from dataclasses import dataclass

from werkzeug.serving import make_server

from parking import model
from parking.service import ParkingService
from parking.web import create_app

from .edge import build_message

POLL_S = 2.0
CHANGES = [("A07", model.WOLNE), ("B11", model.ZAJETE), ("C20", model.WOLNE), ("A15", model.ZAJETE),
           ("B22", model.WOLNE), ("C03", model.ZAJETE), ("A28", model.WOLNE), ("B01", model.ZAJETE),
           ("C14", model.WOLNE), ("A19", model.ZAJETE)]


@dataclass
class K2Row:
    spot: str
    state: str
    received_utc: str
    visible_utc: str
    delay_s: float
    ok: bool


def measure_k2(service: ParkingService, spacing_s: float = 2.7, timeout_s: float = 40.0) -> list[K2Row]:
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    service.start(model.utcnow())
    app = create_app(service, "k2-test-only")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.server_port
    threading.Thread(target=server.serve_forever, daemon=True).start()

    received: dict[str, tuple] = {}
    seen: dict[str, K2Row] = {}
    stop = threading.Event()

    def poller():
        while not stop.is_set():
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stan", timeout=5) as resp:
                data = json.load(resp)
            visible = model.utcnow()
            states = {s["id"]: s["stan"] for s in data["miejsca"]}
            for spot, (state, rec) in list(received.items()):
                if spot not in seen and states.get(spot) == state:
                    delay = (visible - rec).total_seconds()
                    seen[spot] = K2Row(spot, state, model.to_iso(rec), model.to_iso(visible),
                                       round(delay, 3), delay <= 5.0)
            stop.wait(POLL_S)

    th = threading.Thread(target=poller, daemon=True)
    th.start()
    try:
        for spot, state in CHANGES:
            now = model.utcnow()
            msg = build_message(spot, state, 60 if state == model.ZAJETE else 300, model.ZMIANA, now)
            rec = model.utcnow()
            service.handle_message(json.dumps(msg, ensure_ascii=False).encode(), rec,
                                   topic=model.topic_for(spot))
            received[spot] = (state, rec)
            time.sleep(spacing_s)
        deadline = time.time() + timeout_s
        while len(seen) < len(CHANGES) and time.time() < deadline:
            time.sleep(0.2)
    finally:
        stop.set()
        server.shutdown()
    return [seen[s] for s, _ in CHANGES if s in seen]
