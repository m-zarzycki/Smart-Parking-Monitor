"""Punkt wejścia WSGI dla Azure App Service (gunicorn parking.wsgi:app).

Konfiguracja wyłącznie z ustawień aplikacji (zmienne środowiskowe / Key Vault):
DATABASE_URL (mssql://... z Authentication=ActiveDirectoryMsi), SECRET_KEY.
Aplikacja nie tworzy schematu – ma w bazie tylko prawo odczytu i potwierdzania alertów.
"""
import os

from .config import get_settings
from .db import Database
from .service import ParkingService
from .web import create_app

_settings = get_settings()
app = create_app(ParkingService(Database(_settings.database_url)), _settings.secret_key,
                 cookie_secure=os.environ.get("SESSION_COOKIE_SECURE", "true") == "true")
