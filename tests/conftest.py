import json
from datetime import datetime, timedelta, timezone

import pytest

from parking import model
from parking.db import Database
from parking.service import ParkingService

T0 = datetime(2026, 11, 24, 8, 0, 0, tzinfo=timezone.utc)  # 09:00 czasu lokalnego


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    yield database
    database.close()


@pytest.fixture
def service(db):
    svc = ParkingService(db, gateway_ids=("symulator-01",))
    svc.start(T0)
    return svc


def msg(spot="B03", state=model.ZAJETE, msg_type=model.ZMIANA, t=T0, distance=60, **over):
    data = {
        "spot_id": spot, "zone": spot[0], "state": state, "distance_cm": distance,
        "msg_type": msg_type, "event_time_utc": model.to_iso(t),
    }
    data.update(over)
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def send(service, spot="B03", state=model.ZAJETE, msg_type=model.ZMIANA, t=T0, delay=0.2, **over):
    return service.handle_message(msg(spot, state, msg_type, t, **over), t + timedelta(seconds=delay),
                                  topic=model.topic_for(spot))


def sec(n):
    return timedelta(seconds=n)
