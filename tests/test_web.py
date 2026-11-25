"""Aplikacja web: dostęp kierowcy i zarządcy, CSRF, nagłówki bezpieczeństwa, potwierdzanie alertu."""
import re

import pytest
from werkzeug.security import generate_password_hash

from parking import model
from parking.web import create_app
from conftest import T0, send, sec

PASSWORD = "haslo-testowe-tylko-w-tescie"


@pytest.fixture
def client(service, db):
    db.upsert_user("zarzadca", generate_password_hash(PASSWORD), "zarzadca", T0)
    app = create_app(service, "klucz-testowy")
    app.config["TESTING"] = True
    return app.test_client()


def csrf(client, path="/logowanie"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def login(client, password=PASSWORD):
    return client.post("/logowanie", data={"login": "zarzadca", "haslo": password, "csrf": csrf(client)})


def test_public_pages_and_api(client, service):
    send(service, "B03", model.ZAJETE)
    assert client.get("/").status_code == 200
    assert client.get("/mapa").status_code == 200
    data = client.get("/api/stan").get_json()
    assert len(data["miejsca"]) == 90
    b03 = next(s for s in data["miejsca"] if s["id"] == "B03")
    assert b03["stan"] == "ZAJĘTE"
    assert data["tablica"]["A"]["napis"] == "BRAK DANYCH"
    assert "odleglosc_cm" not in b03


def test_security_headers(client):
    h = client.get("/").headers
    assert "default-src 'self'" in h["Content-Security-Policy"]
    assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff"
    assert client.get("/api/stan").headers["Cache-Control"] == "no-store"


def test_manager_area_requires_login(client):
    r = client.get("/panel")
    assert r.status_code == 302 and "/logowanie" in r.headers["Location"]
    for path in ("/api/alerty", "/api/oblozenie", "/api/historia", "/api/odrzucone"):
        assert client.get(path).status_code == 401


def test_login_requires_csrf_and_correct_password(client):
    r = client.post("/logowanie", data={"login": "zarzadca", "haslo": PASSWORD})
    assert r.status_code == 400
    assert login(client, "zle-haslo").status_code == 401
    r = login(client)
    assert r.status_code == 302 and r.headers["Location"].endswith("/panel")
    assert client.get("/panel").status_code == 200


def test_login_rate_limit(client):
    for _ in range(5):
        assert login(client, "zle").status_code == 401
    assert login(client).status_code == 429


def test_no_open_redirect_after_login(client):
    token = csrf(client)
    r = client.post("/logowanie?next=//evil.example", data={"login": "zarzadca", "haslo": PASSWORD,
                                                           "csrf": token})
    assert r.headers["Location"].endswith("/panel")


def test_acknowledge_alert_with_csrf(client, service, db):
    send(service, "C05", model.WOLNE, t=T0, delay=0)
    for spot in model.ALL_SPOTS:
        if spot != "C05":
            send(service, spot, model.WOLNE, t=T0 + sec(100), delay=0)
    service.check_silence(T0 + sec(190))
    login(client)
    alerts = client.get("/api/alerty?aktywne=1").get_json()
    assert [a["miejsce"] for a in alerts] == ["C05"]
    aid = alerts[0]["id"]
    assert client.post(f"/api/alerty/{aid}/potwierdz").status_code == 400  # bez tokenu CSRF
    panel = client.get("/panel").get_data(as_text=True)
    token = re.search(r'content="([^"]+)" id="csrf"', panel).group(1)
    r = client.post(f"/api/alerty/{aid}/potwierdz", headers={"X-CSRF-Token": token})
    assert r.status_code == 200 and r.get_json()["potwierdzono"]
    assert client.post(f"/api/alerty/{aid}/potwierdz", headers={"X-CSRF-Token": token}).status_code == 409
    spots = {s["id"]: s["stan"] for s in client.get("/api/stan").get_json()["miejsca"]}
    assert spots["C05"] == model.BRAK_DANYCH  # potwierdzenie nie zmienia stanu


def test_bad_parameters(client):
    login(client)
    assert client.get("/api/historia?miejsce=Z99").status_code == 400
    assert client.get("/api/historia?limit=abc").status_code == 200
    assert client.get("/api/oblozenie?dni=-5").status_code == 200
