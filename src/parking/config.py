"""Konfiguracja z zmiennych środowiskowych (plik .env jest tylko lokalny, poza repozytorium).

W kodzie nie ma żadnych haseł, kluczy ani connection stringów. Wzór: .env.example.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    """Prosty loader pliku .env (KEY=VALUE). Nie nadpisuje zmiennych już ustawionych."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "tak", "yes", "on")


@dataclass
class Settings:
    database_url: str
    mqtt_host: str
    mqtt_port: int
    mqtt_tls: bool
    mqtt_ca_file: str
    mqtt_receiver_user: str
    mqtt_receiver_password: str
    mqtt_sensor_user: str
    mqtt_sensor_password: str
    web_host: str
    web_port: int
    secret_key: str
    gateway_ids: tuple
    log_level: str


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "sqlite:///data/parking.db"),
        mqtt_host=os.environ.get("MQTT_HOST", "127.0.0.1"),
        mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
        mqtt_tls=_bool("MQTT_TLS", False),
        mqtt_ca_file=os.environ.get("MQTT_CA_FILE", ""),
        mqtt_receiver_user=os.environ.get("MQTT_RECEIVER_USER", "odbiornik"),
        mqtt_receiver_password=os.environ.get("MQTT_RECEIVER_PASSWORD", ""),
        mqtt_sensor_user=os.environ.get("MQTT_SENSOR_USER", "czujniki"),
        mqtt_sensor_password=os.environ.get("MQTT_SENSOR_PASSWORD", ""),
        web_host=os.environ.get("WEB_HOST", "127.0.0.1"),
        web_port=int(os.environ.get("WEB_PORT", "8000")),
        secret_key=os.environ.get("SECRET_KEY", ""),
        gateway_ids=tuple(x.strip() for x in os.environ.get("GATEWAY_IDS", "symulator-01").split(",")
                          if x.strip()),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
