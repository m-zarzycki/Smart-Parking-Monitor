"""Połączenie symulator -> MQTT -> odbiornik na atrapie brokera (bez sieci).

Sprawdza okablowanie kodu (subskrypcja parking/+/+, przekazanie tematu i treści do serwisu).
Prawdziwy broker Mosquitto testujemy ręcznie według README, krok 3.
"""
import sys
import types
from types import SimpleNamespace

from parking import model
from parking.config import Settings
from parking.worker import MqttReceiver
from simulator.engine import run_scenario
from simulator.scenarios import scenario_1


class FakeBroker:
    def __init__(self):
        self.subs = []  # (pattern, client)

    @staticmethod
    def match(pattern, topic):
        p, t = pattern.split("/"), topic.split("/")
        return len(p) == len(t) and all(a in ("+", b) for a, b in zip(p, t))

    def deliver(self, topic, payload):
        for pattern, client in self.subs:
            if self.match(pattern, topic):
                client.on_message(client, None, SimpleNamespace(topic=topic, payload=payload))


def fake_paho(broker):
    mod = types.ModuleType("paho.mqtt.client")
    ok = SimpleNamespace(is_failure=False)

    class Client:
        def __init__(self, api, client_id="", clean_session=True):
            self.client_id = client_id
            self.on_connect = self.on_disconnect = self.on_message = None

        def username_pw_set(self, u, p): self.user = u
        def tls_set(self, **kw): pass
        def reconnect_delay_set(self, **kw): pass
        def connect(self, host, port, keepalive=60): self.on_connect(self, None, {}, ok, None)
        connect_async = connect
        def subscribe(self, pattern, qos=0): broker.subs.append((pattern, self))
        def loop_start(self): pass
        def loop_stop(self): pass
        def loop_forever(self, retry_first_connection=False): pass
        def disconnect(self): pass

        def publish(self, topic, payload, qos=0):
            broker.deliver(topic, payload)
            return SimpleNamespace(rc=0)

    mod.Client = Client
    mod.CallbackAPIVersion = SimpleNamespace(VERSION2=2)
    mod.MQTT_ERR_SUCCESS = 0
    return mod


def test_simulator_to_receiver_over_fake_mqtt(monkeypatch, service, db):
    broker = FakeBroker()
    fake = fake_paho(broker)
    monkeypatch.setitem(sys.modules, "paho", types.ModuleType("paho"))
    monkeypatch.setitem(sys.modules, "paho.mqtt", types.ModuleType("paho.mqtt"))
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", fake)
    from simulator.publishers import MqttPublisher

    settings = Settings("", "127.0.0.1", 1883, False, "", "odbiornik", "x", "czujniki", "y",
                        "127.0.0.1", 8000, "", ("symulator-01",), "INFO")
    receiver = MqttReceiver(service, settings)
    receiver.run_forever()  # łączy i subskrybuje (atrapa nie blokuje)
    assert broker.subs[0][0] == "parking/+/+"

    publisher = MqttPublisher("127.0.0.1", 1883, "czujniki", "y")
    sc = scenario_1()
    sc.duration_s = 70  # do 09:00:10 – po zmianie B03
    # Odbiornik stempluje czasem rzeczywistym, a scenariusz ma czasy zdarzeń z przeszłości,
    # więc walidacja je przyjmuje (odrzuca tylko czasy > 1 min w przyszłości).
    run_scenario(sc, publisher)
    spots = {s["spot_id"]: s["stan"] for s in db.spots()}
    assert spots["B03"] == model.ZAJETE
    assert service.board()["B"]["napis"] == "4"
    assert db.rejected() == []
