"""Wyjścia symulatora: broker MQTT (tryb lokalny), Azure IoT Hub (tryb Azure), stdout."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime

log = logging.getLogger("symulator")


class StdoutPublisher:
    def __call__(self, topic: str, payload: bytes, msg: dict, now: datetime) -> None:
        sys.stdout.write(f"{topic} {payload.decode('utf-8')}\n")
        sys.stdout.flush()

    def close(self) -> None:
        pass


class MqttPublisher:
    """Publikuje JSON na temat parking/{strefa}/{miejsce}, QoS 1, login z .env."""

    def __init__(self, host: str, port: int, user: str, password: str,
                 tls: bool = False, ca_file: str = "", client_id: str = "symulator-01"):
        import paho.mqtt.client as mqtt

        self._mqtt = mqtt
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if user:
            self.client.username_pw_set(user, password or None)
        if tls:
            self.client.tls_set(ca_certs=ca_file or None)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.connect(host, port, keepalive=60)
        self.client.loop_start()

    @staticmethod
    def _on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("Broker odrzucił połączenie: %s (sprawdź login i hasło w .env)", reason_code)
        else:
            log.info("Połączono z brokerem MQTT")

    @staticmethod
    def _on_disconnect(client, userdata, flags, reason_code, properties):
        log.warning("Rozłączono z brokerem: %s", reason_code)

    def __call__(self, topic: str, payload: bytes, msg: dict, now: datetime) -> None:
        info = self.client.publish(topic, payload, qos=1)
        if info.rc != self._mqtt.MQTT_ERR_SUCCESS:
            log.warning("Nie wysłano %s (rc=%s) – brak bufora, komunikat przepada", topic, info.rc)

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


class IoTHubPublisher:
    """Wysyła do Azure IoT Hub jako urządzenie-bramka (np. symulator-01).

    Connection string urządzenia tylko ze zmiennej środowiskowej
    IOTHUB_DEVICE_CONNECTION_STRING. Limit dzienny chroni darmową warstwę F1
    (8 000 komunikatów na dobę).
    """

    def __init__(self, connection_string: str, max_messages: int = 7000):
        if not connection_string:
            raise SystemExit("Brak IOTHUB_DEVICE_CONNECTION_STRING w .env")
        from azure.iot.device import IoTHubDeviceClient, Message

        self._Message = Message
        self.client = IoTHubDeviceClient.create_from_connection_string(connection_string)
        self.client.connect()
        self.sent = 0
        self.max_messages = max_messages
        log.info("Połączono z Azure IoT Hub (limit tej sesji: %d komunikatów)", max_messages)

    def __call__(self, topic: str, payload: bytes, msg: dict, now: datetime) -> None:
        if self.sent >= self.max_messages:
            raise SystemExit(f"Osiągnięto limit {self.max_messages} komunikatów (warstwa F1)")
        m = self._Message(payload.decode("utf-8"))
        m.content_encoding = "utf-8"
        m.content_type = "application/json"
        m.custom_properties["topic"] = topic
        self.client.send_message(m)
        self.sent += 1

    def close(self) -> None:
        self.client.shutdown()


def describe(msg: dict) -> str:
    return json.dumps(msg, ensure_ascii=False)
