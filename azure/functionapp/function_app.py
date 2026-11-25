"""Azure Functions (model programowania v2, Python) – tryb Azure.

Odbiornik: wyzwalacz Event Hubs na wbudowanym punkcie końcowym IoT Hub
           -> ParkingService.handle_message (walidacja, porównanie z bazą, zapis).
Kontrola:  timer co 10 s -> ParkingService.check_silence (BRAK DANYCH + 1 alert),
           co 5 min próbka obłożenia stref do wykresu 7 dni.

Logika jest ta sama co w trybie lokalnym (pakiet `parking`, kopiowany do paczki
skryptem azure/przygotuj_paczki.py). Konfiguracja tylko z ustawień aplikacji:
  DATABASE_URL                   mssql://Driver=...;Authentication=ActiveDirectoryMsi (bez hasła)
  IOTHUB_EVENTHUB_CONNECTION     connection string punktu końcowego (referencja do Key Vault)
  IOTHUB_EVENTHUB_NAME           nazwa zgodna z Event Hubs
  IOTHUB_CONSUMER_GROUP          np. odbiornik
  GATEWAY_IDS                    np. symulator-01
"""
import logging
import os
from datetime import timezone

import azure.functions as func

from parking import model
from parking.db import Database
from parking.service import ParkingService

app = func.FunctionApp()
_service = None


def service() -> ParkingService:
    global _service
    if _service is None:
        gateways = tuple(x.strip() for x in os.environ.get("GATEWAY_IDS", "symulator-01").split(",")
                         if x.strip())
        _service = ParkingService(Database(os.environ["DATABASE_URL"]), gateway_ids=gateways)
    return _service


@app.function_name(name="Odbiornik")
@app.event_hub_message_trigger(
    arg_name="event",
    event_hub_name="%IOTHUB_EVENTHUB_NAME%",
    connection="IOTHUB_EVENTHUB_CONNECTION",
    consumer_group="%IOTHUB_CONSUMER_GROUP%",
    cardinality=func.Cardinality.ONE,
)
def odbiornik(event: func.EventHubEvent) -> None:
    meta = event.iothub_metadata or {}
    device_id = meta.get("connection-device-id")
    # Czas odebrania w chmurze = czas przyjęcia komunikatu przez IoT Hub.
    received = event.enqueued_time or model.utcnow()
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    result = service().handle_message(event.get_body(), received, device_id=device_id)
    if result.status == "odrzucony":
        logging.warning("Odrzucono komunikat od %s: %s", device_id, result.reason)


@app.function_name(name="Kontrola")
@app.timer_trigger(arg_name="timer", schedule="*/10 * * * * *", run_on_startup=False, use_monitor=False)
def kontrola(timer: func.TimerRequest) -> None:
    now = model.utcnow()
    res = service().check_silence(now)
    if res.alerts_opened:
        logging.warning("Nowe alerty o braku danych: %s", ", ".join(res.alerts_opened))
    if now.minute % 5 == 0 and now.second < 10:
        service().snapshot_occupancy(now)
