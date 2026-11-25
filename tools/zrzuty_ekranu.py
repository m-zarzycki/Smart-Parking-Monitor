"""Przygotowuje stan demonstracyjny i robi zrzuty ekranu aplikacji (headless Chrome + Playwright).

  python tools/zrzuty_ekranu.py --chrome /usr/bin/google-chrome

Stan: scenariusz w zegarze wirtualnym kończący się „teraz” (A – pełna, C05 bez danych z aktywnym
alertem, B12 z zamkniętym alertem), kilka odrzuconych komunikatów i syntetyczna historia 7 dni.
Hasło zarządcy jest losowe i istnieje tylko w pamięci skryptu.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from werkzeug.security import generate_password_hash  # noqa: E402

from parking import model  # noqa: E402
from parking.db import Database  # noqa: E402
from parking.service import ParkingService  # noqa: E402
from simulator.harness import run_virtual  # noqa: E402
from simulator.scenarios import Event, Offline, Scenario, _zone_spots  # noqa: E402


def build_state(db_path: str) -> str:
    db = Database(f"sqlite:///{db_path}")
    svc = ParkingService(db)
    duration = 660.0
    now = model.utcnow().replace(microsecond=0)
    sc = Scenario(
        key="demo", title="stan do zrzutów", description="",
        nominal_start_utc=now - timedelta(seconds=duration),
        duration_s=duration,
        free_spots={"A06"} | _zone_spots("B", [5, 9, 16, 28, 12]) | _zone_spots("C", [1, 5, 10, 15, 19, 24, 30]),
        events=[Event("A06", 120.0, None, 55), Event("B12", 150.0, None, 70), Event("C24", 500.0, None, 64)],
        offline=[Offline("C05", 60.0, duration + 10), Offline("B12", 200.0, 420.0)],
        boot_offsets={"C05": 0.0, "B12": 0.0},
    )
    run_virtual(sc, db, svc)
    t = now - timedelta(seconds=30)
    bad = [
        ({"spot_id": "D07", "zone": "D", "state": "WOLNE", "distance_cm": 300, "msg_type": "ZMIANA",
          "event_time_utc": model.to_iso(t)}, "parking/B/B03"),
        ({"spot_id": "B03", "zone": "B", "state": "ZAJĘTE", "distance_cm": 912, "msg_type": "HEARTBEAT",
          "event_time_utc": model.to_iso(t)}, "parking/B/B03"),
        ({"spot_id": "A11", "zone": "A", "state": "ZAJĘTE", "distance_cm": 70, "msg_type": "ZMIANA",
          "event_time_utc": model.to_iso(t)}, "parking/A/A12"),
    ]
    for payload, topic in bad:
        svc.handle_message(json.dumps(payload, ensure_ascii=False).encode(), t, topic=topic)
    password = secrets.token_urlsafe(16)
    db.upsert_user("zarzadca", generate_password_hash(password), "zarzadca", now)
    return password


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome", default=None)
    ap.add_argument("--port", type=int, default=8790)
    args = ap.parse_args()
    out = os.path.join(ROOT, "docs", "img")
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="parking_zrzuty_")
    db_path = os.path.join(tmp, "demo.db")
    password = build_state(db_path)
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{db_path}", WEB_PORT=str(args.port),
               SECRET_KEY=secrets.token_hex(16), PYTHONPATH=os.path.join(ROOT, "src"))
    subprocess.run([sys.executable, "-m", "parking", "historia-demo"], env=env, cwd=tmp, check=True,
                   capture_output=True)
    web = subprocess.Popen([sys.executable, "-m", "parking", "web"], env=env, cwd=tmp,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.5)
    base = f"http://127.0.0.1:{args.port}"
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.chrome) if args.chrome else p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 760}, device_scale_factor=2,
                                    locale="pl-PL", timezone_id="Europe/Warsaw")
            page.goto(base + "/")
            page.wait_for_timeout(1500)
            page.screenshot(path=os.path.join(out, "ekran_tablica.png"))
            page.set_viewport_size({"width": 1280, "height": 900})
            page.goto(base + "/mapa")
            page.wait_for_timeout(1500)
            page.screenshot(path=os.path.join(out, "ekran_mapa.png"), full_page=True)
            page.goto(base + "/logowanie")
            page.fill("input[name=login]", "zarzadca")
            page.fill("input[name=haslo]", password)
            page.click("button[type=submit]")
            page.wait_for_url("**/panel")
            page.wait_for_timeout(2000)
            page.screenshot(path=os.path.join(out, "ekran_panel.png"), full_page=True)
            browser.close()
    finally:
        web.terminate()
    print("Zapisano zrzuty w", out)


if __name__ == "__main__":
    main()
