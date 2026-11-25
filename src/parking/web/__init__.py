"""Aplikacja webowa + API (F03 tablica, F04 mapa, F05 panel zarządcy).

Kierowca: tablica i mapa bez logowania (tylko odczyt).
Zarządca: panel po zalogowaniu (alerty, potwierdzanie, historia 7 dni, odrzucone komunikaty).
"""
from __future__ import annotations

import logging
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash

from .. import model
from ..service import ParkingService

log = logging.getLogger("parking.web")

LOGIN_WINDOW_S = 300
LOGIN_MAX_FAILURES = 5


def _iso(dt):
    return model.to_iso(dt) if dt else None


def create_app(service: ParkingService, secret_key: str = "", cookie_secure: bool = False) -> Flask:
    app = Flask(__name__)
    if not secret_key:
        # Bez SECRET_KEY w .env klucz jest losowy przy każdym starcie (sesje wygasają po restarcie).
        secret_key = secrets.token_hex(32)
        log.warning("Brak SECRET_KEY w .env – użyto klucza tymczasowego")
    app.config.update(
        SECRET_KEY=secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cookie_secure,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        JSON_AS_ASCII=False,
    )
    app.json.ensure_ascii = False
    db = service.db
    failures: dict[str, deque] = defaultdict(deque)

    # --- bezpieczeństwo -------------------------------------------------------------------
    @app.after_request
    def security_headers(resp):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def csrf_token() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    def check_csrf():
        sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400, "Niepoprawny token CSRF")

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("rola") != "zarzadca":
                if request.path.startswith("/api/"):
                    return jsonify({"blad": "wymagane logowanie zarządcy"}), 401
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    # --- strony ----------------------------------------------------------------------------
    @app.get("/")
    def tablica():
        return render_template("tablica.html")

    @app.get("/mapa")
    def mapa():
        return render_template("mapa.html", zones=model.ZONES, spots=model.ALL_SPOTS,
                               descriptions=model.ZONE_DESCRIPTIONS)

    @app.get("/panel")
    @login_required
    def panel():
        return render_template("panel.html", user=session.get("login"),
                               synthetic=db.get_setting("dane_syntetyczne"))

    @app.route("/logowanie", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            check_csrf()
            ip = request.remote_addr or "?"
            q = failures[ip]
            now = time.time()
            while q and now - q[0] > LOGIN_WINDOW_S:
                q.popleft()
            if len(q) >= LOGIN_MAX_FAILURES:
                flash("Zbyt wiele nieudanych prób. Spróbuj za kilka minut.")
                return render_template("logowanie.html"), 429
            login_name = request.form.get("login", "").strip()[:64]
            password = request.form.get("haslo", "")
            user = db.get_user(login_name) if login_name else None
            if user and check_password_hash(user["hash_hasla"], password):
                session.clear()
                session["login"] = user["login"]
                session["rola"] = user["rola"]
                session.permanent = True
                log.info("Zalogowano: %s", user["login"])
                target = request.args.get("next", "")
                return redirect(target if target.startswith("/") and not target.startswith("//")
                                else url_for("panel"))
            q.append(now)
            log.warning("Nieudane logowanie z %s", ip)
            flash("Niepoprawny login lub hasło.")
            return render_template("logowanie.html"), 401
        return render_template("logowanie.html")

    @app.post("/wyloguj")
    def logout():
        check_csrf()
        session.clear()
        return redirect(url_for("tablica"))

    # --- API publiczne (kierowca) ---------------------------------------------------------------
    @app.get("/api/stan")
    def api_stan():
        spots = db.spots()
        return jsonify({
            "czas_serwera": _iso(model.utcnow()),
            "tablica": service.board(),
            "miejsca": [{
                "id": s["spot_id"], "strefa": s["strefa"], "stan": s["stan"],
                "czas_zmiany_stanu": _iso(s["czas_zmiany_stanu"]),
                "czas_ostatniego_komunikatu": _iso(s["czas_ostatniego_komunikatu"]),
            } for s in spots],
        })

    @app.get("/api/tablica")
    def api_tablica():
        return jsonify({"czas_serwera": _iso(model.utcnow()), "tablica": service.board()})

    @app.get("/zdrowie")
    def health():
        return jsonify({"status": "ok", "czas_serwera": _iso(model.utcnow())})

    # --- API zarządcy ------------------------------------------------------------------------------
    @app.get("/api/alerty")
    @login_required
    def api_alerty():
        active = request.args.get("aktywne") == "1"
        return jsonify([{
            "id": a["id"], "miejsce": a["spot_id"],
            "czas_ostatniego_komunikatu": _iso(a["czas_ostatniego_komunikatu"]),
            "czas_otwarcia": _iso(a["czas_otwarcia"]), "czas_zamkniecia": _iso(a["czas_zamkniecia"]),
            "czas_potwierdzenia": _iso(a["czas_potwierdzenia"]), "potwierdzil": a["potwierdzil"],
        } for a in db.alerts(active_only=active)])

    @app.post("/api/alerty/<int:alert_id>/potwierdz")
    @login_required
    def api_potwierdz(alert_id: int):
        check_csrf()
        ok = db.acknowledge_alert(alert_id, session["login"], model.utcnow())
        if ok:
            log.info("Alert %d potwierdzony przez %s", alert_id, session["login"])
        return jsonify({"potwierdzono": ok}), (200 if ok else 409)

    @app.get("/api/oblozenie")
    @login_required
    def api_oblozenie():
        days = min(max(request.args.get("dni", 7, type=int), 1), 31)
        rows = db.occupancy_series(model.utcnow() - timedelta(days=days))
        return jsonify([{"czas": _iso(r["czas"]), "strefa": r["strefa"], "wolne": r["wolne"],
                         "zajete": r["zajete"], "brak_danych": r["brak_danych"]} for r in rows])

    @app.get("/api/historia")
    @login_required
    def api_historia():
        spot = request.args.get("miejsce") or None
        if spot is not None and spot not in model.ALL_SPOTS:
            abort(400, "nieznane miejsce")
        limit = min(max(request.args.get("limit", 100, type=int), 1), 1000)
        return jsonify([{
            "id": h["id"], "miejsce": h["spot_id"], "strefa": h["strefa"], "nowy_stan": h["nowy_stan"],
            "czas_zmiany": _iso(h["czas_zmiany"]), "czas_odebrania": _iso(h["czas_odebrania"]),
            "zrodlo": h["zrodlo"],
        } for h in db.history(spot_id=spot, limit=limit)])

    @app.get("/api/odrzucone")
    @login_required
    def api_odrzucone():
        return jsonify([{
            "id": r["id"], "czas_odebrania": _iso(r["czas_odebrania"]), "powod": r["powod"],
            "szczegoly": r["szczegoly"], "zrodlo": r["zrodlo"], "tresc": r["tresc"],
        } for r in db.rejected(limit=50)])

    @app.errorhandler(400)
    def bad_request(err):
        if request.path.startswith("/api/"):
            return jsonify({"blad": getattr(err, "description", "błędne żądanie")}), 400
        return err

    return app
