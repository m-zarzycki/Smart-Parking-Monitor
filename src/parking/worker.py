"""Tryb lokalny: odbiornik MQTT (funkcja Odbiornik) i pętla kontroli (funkcja Kontrola).

W trybie Azure te same metody ParkingService wywołuje azure/function_app.py.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from . import model
from .config import Settings
from .service import ParkingService

log = logging.getLogger("parking")

SUBSCRIPTION = f"{model.TOPIC_PREFIX}/+/+"
SNAPSHOT_PERIOD_S = 300  # próbka obłożenia stref co 5 min (wykres 7 dni)


class SilenceChecker(threading.Thread):
    """Co 10 s: BRAK DANYCH po > 3 min ciszy; co 5 min: próbka obłożenia stref."""

    def __init__(self, service: ParkingService, stop: threading.Event):
        super().__init__(name="kontrola", daemon=True)
        self.service = service
        self.stop = stop

    def run(self) -> None:
        last_snapshot_slot: Optional[int] = None
        while not self.stop.is_set():
            now = model.utcnow()
            try:
                self.service.check_silence(now)
                slot = int(now.timestamp()) // SNAPSHOT_PERIOD_S
                if slot != last_snapshot_slot:
                    self.service.snapshot_occupancy(now)
                    last_snapshot_slot = slot
            except Exception:  # pętla nie może się zatrzymać przez pojedynczy błąd
                log.exception("Błąd kontroli braku danych")
            # następna kontrola na pełnej dziesiątce sekund
            self.stop.wait(model.CHECK_PERIOD_S - (time.time() % model.CHECK_PERIOD_S))


class MqttReceiver:
    """Subskrybuje parking/+/+ i przekazuje każdy komunikat do ParkingService."""

    def __init__(self, service: ParkingService, settings: Settings, client_id: str = "odbiornik-01"):
        import paho.mqtt.client as mqtt

        self.service = service
        self.settings = settings
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                                  clean_session=False)  # sesja trwała: QoS 1 po krótkiej przerwie
        if settings.mqtt_receiver_user:
            self.client.username_pw_set(settings.mqtt_receiver_user,
                                        settings.mqtt_receiver_password or None)
        if settings.mqtt_tls:
            self.client.tls_set(ca_certs=settings.mqtt_ca_file or None)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("Broker odrzucił połączenie odbiornika: %s", reason_code)
            return
        client.subscribe(SUBSCRIPTION, qos=1)
        log.info("Odbiornik połączony, subskrypcja %s", SUBSCRIPTION)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        log.warning("Odbiornik rozłączony (%s) – ponawianie połączenia", reason_code)

    def _on_message(self, client, userdata, msg):
        try:
            self.service.handle_message(msg.payload, model.utcnow(), topic=msg.topic)
        except Exception:
            log.exception("Błąd zapisu komunikatu z %s", msg.topic)

    def run_forever(self) -> None:
        if self.settings.mqtt_receiver_user and not self.settings.mqtt_receiver_password:
            log.warning("Brak MQTT_RECEIVER_PASSWORD w .env")
        log.info("Łączenie z brokerem %s:%d (TLS: %s)", self.settings.mqtt_host,
                 self.settings.mqtt_port, "tak" if self.settings.mqtt_tls else "nie")
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=60)
        self.client.loop_forever(retry_first_connection=True)

    def start_background(self) -> threading.Thread:
        th = threading.Thread(target=self.run_forever, name="odbiornik", daemon=True)
        th.start()
        return th
