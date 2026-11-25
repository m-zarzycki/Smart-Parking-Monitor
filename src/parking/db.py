"""Warstwa dostępu do bazy: SQLite (tryb lokalny) i Azure SQL (tryb Azure).

Oba dialekty używają parametrów `?` (sqlite3 i pyodbc), więc zapytania są
parametryzowane i wspólne. Różnice (typ czasu, blokady, TOP/LIMIT, zwracanie
identyfikatora) obsługują małe metody pomocnicze.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from typing import Any, Iterator, Optional

from . import model


class Tx:
    """Pojedyncza transakcja: metody zapytań z parametrami."""

    def __init__(self, db: "Database", cursor: Any):
        self.db = db
        self.cur = cursor

    def q(self, sql: str, params: tuple = ()) -> list[dict]:
        self.cur.execute(sql, self.db._params(params))
        if self.cur.description is None:
            return []
        cols = [d[0] for d in self.cur.description]
        return [dict(zip(cols, row)) for row in self.cur.fetchall()]

    def one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def ex(self, sql: str, params: tuple = ()) -> int:
        self.cur.execute(sql, self.db._params(params))
        return self.cur.rowcount

    def insert(self, table: str, values: dict) -> int:
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        if self.db.dialect == "mssql":
            self.cur.execute(
                f"INSERT INTO {table} ({cols}) OUTPUT INSERTED.id VALUES ({marks})",
                self.db._params(tuple(values.values())),
            )
            return int(self.cur.fetchone()[0])
        self.cur.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({marks})",
            self.db._params(tuple(values.values())),
        )
        return int(self.cur.lastrowid or 0)


class Database:
    """Połączenie z bazą. Jedno połączenie na wątek (threading.local)."""

    def __init__(self, url: str):
        self.url = url
        if url.startswith("sqlite:///"):
            self.dialect = "sqlite"
            self.path = url[len("sqlite:///"):]
        elif url.startswith("mssql://"):
            self.dialect = "mssql"
            # Pełny connection string ODBC po prefiksie, bez hasła (tożsamość zarządzana)
            self.odbc = url[len("mssql://"):]
        else:
            raise ValueError("DATABASE_URL musi zaczynać się od sqlite:/// albo mssql://")
        self._local = threading.local()

    # --- połączenie ---------------------------------------------------------------
    def _connect(self):
        if self.dialect == "sqlite":
            folder = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(folder, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=30, isolation_level=None,
                                   check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            return conn
        import pyodbc  # tylko w trybie Azure

        conn = pyodbc.connect(self.odbc, autocommit=False, timeout=30)
        return conn

    def _conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    @contextmanager
    def tx(self) -> Iterator[Tx]:
        conn = self._conn()
        cur = conn.cursor()
        if self.dialect == "sqlite":
            cur.execute("BEGIN IMMEDIATE")  # blokada zapisu: odbiornik i kontrola nie nadpiszą się
        try:
            yield Tx(self, cur)
            if self.dialect == "sqlite":
                cur.execute("COMMIT")
            else:
                conn.commit()
        except Exception:
            if self.dialect == "sqlite":
                cur.execute("ROLLBACK")
            else:
                conn.rollback()
            raise
        finally:
            cur.close()

    # --- różnice dialektów -----------------------------------------------------------
    def _params(self, params: tuple) -> tuple:
        out = []
        for p in params:
            if isinstance(p, datetime):
                p = p.astimezone(timezone.utc)
                if self.dialect == "sqlite":
                    p = model.to_iso(p)
                else:
                    p = p.replace(tzinfo=None)  # DATETIME2 w UTC
            out.append(p)
        return tuple(out)

    def ts(self, value: Any) -> Optional[datetime]:
        """Czas z bazy -> datetime w UTC."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return model.parse_iso(str(value))

    def lock_hint(self) -> str:
        return " WITH (UPDLOCK, ROWLOCK)" if self.dialect == "mssql" else ""

    def top(self, n: int) -> tuple[str, str]:
        """(prefiks po SELECT, sufiks na końcu) dla ograniczenia liczby wierszy."""
        n = int(n)
        if self.dialect == "mssql":
            return f"TOP ({n}) ", ""
        return "", f" LIMIT {n}"

    # --- schemat ---------------------------------------------------------------------
    def init_schema(self) -> None:
        name = "sqlite.sql" if self.dialect == "sqlite" else "azuresql.sql"
        script = resources.files("parking").joinpath("sql", name).read_text(encoding="utf-8")
        conn = self._conn()
        if self.dialect == "sqlite":
            conn.executescript(script)
        else:
            cur = conn.cursor()
            for batch in script.split("\nGO"):
                if batch.strip() and not all(
                    line.strip().startswith("--") or not line.strip()
                    for line in batch.splitlines()
                ):
                    cur.execute(batch)
            conn.commit()

    def seed_spots(self, now: datetime) -> int:
        """Wstawia brakujące miejsca A01–C30 ze stanem BRAK DANYCH (reguła 1)."""
        added = 0
        with self.tx() as t:
            existing = {r["spot_id"].strip() for r in t.q("SELECT spot_id FROM miejsca")}
            for spot in model.ALL_SPOTS:
                if spot not in existing:
                    t.ex(
                        "INSERT INTO miejsca (spot_id, strefa, stan) VALUES (?, ?, ?)",
                        (spot, model.zone_of(spot), model.BRAK_DANYCH),
                    )
                    added += 1
            if t.one("SELECT wartosc FROM system WHERE klucz = ?", ("czas_uruchomienia",)) is None:
                t.ex("INSERT INTO system (klucz, wartosc) VALUES (?, ?)",
                     ("czas_uruchomienia", model.to_iso(now)))
        return added

    # --- system ------------------------------------------------------------------------
    def get_setting(self, key: str) -> Optional[str]:
        with self.tx() as t:
            row = t.one("SELECT wartosc FROM system WHERE klucz = ?", (key,))
        return row["wartosc"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self.tx() as t:
            if t.ex("UPDATE system SET wartosc = ? WHERE klucz = ?", (value, key)) == 0:
                t.ex("INSERT INTO system (klucz, wartosc) VALUES (?, ?)", (key, value))

    # --- odczyty dla aplikacji -------------------------------------------------------------
    def spots(self) -> list[dict]:
        with self.tx() as t:
            rows = t.q(
                "SELECT spot_id, strefa, stan, odleglosc_cm, czas_zdarzenia, "
                "czas_ostatniego_komunikatu, czas_zmiany_stanu FROM miejsca ORDER BY spot_id"
            )
        for r in rows:
            r["spot_id"] = r["spot_id"].strip()
            r["strefa"] = r["strefa"].strip()
            for k in ("czas_zdarzenia", "czas_ostatniego_komunikatu", "czas_zmiany_stanu"):
                r[k] = self.ts(r[k])
        return rows

    def zone_counts(self) -> dict[str, dict[str, int]]:
        """Liczba miejsc w każdym stanie dla stref A, B, C (zapytanie SQL, K4)."""
        out = {z: {model.WOLNE: 0, model.ZAJETE: 0, model.BRAK_DANYCH: 0} for z in model.ZONES}
        with self.tx() as t:
            rows = t.q("SELECT strefa, stan, COUNT(*) AS n FROM miejsca GROUP BY strefa, stan")
        for r in rows:
            out[r["strefa"].strip()][r["stan"]] = int(r["n"])
        return out

    def history(self, spot_id: Optional[str] = None, since: Optional[datetime] = None,
                limit: int = 1000) -> list[dict]:
        pre, suf = self.top(limit)
        where, params = [], []
        if spot_id:
            where.append("spot_id = ?")
            params.append(spot_id)
        if since:
            where.append("czas_zmiany >= ?")
            params.append(since)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with self.tx() as t:
            rows = t.q(
                f"SELECT {pre}id, spot_id, strefa, nowy_stan, czas_zmiany, czas_odebrania, zrodlo "
                f"FROM historia_zmian{clause} ORDER BY id DESC{suf}",
                tuple(params),
            )
        for r in rows:
            r["spot_id"] = r["spot_id"].strip()
            r["strefa"] = r["strefa"].strip()
            r["czas_zmiany"] = self.ts(r["czas_zmiany"])
            r["czas_odebrania"] = self.ts(r["czas_odebrania"])
        return rows

    def alerts(self, active_only: bool = False, limit: int = 200) -> list[dict]:
        pre, suf = self.top(limit)
        clause = " WHERE czas_zamkniecia IS NULL" if active_only else ""
        with self.tx() as t:
            rows = t.q(
                f"SELECT {pre}id, spot_id, czas_ostatniego_komunikatu, czas_otwarcia, czas_zamkniecia, "
                f"czas_potwierdzenia, potwierdzil FROM alerty{clause} ORDER BY id DESC{suf}"
            )
        for r in rows:
            r["spot_id"] = r["spot_id"].strip()
            for k in ("czas_ostatniego_komunikatu", "czas_otwarcia", "czas_zamkniecia",
                      "czas_potwierdzenia"):
                r[k] = self.ts(r[k])
        return rows

    def acknowledge_alert(self, alert_id: int, user: str, now: datetime) -> bool:
        """Potwierdzenie przez zarządcę. Nie zmienia stanu miejsca (LAB02)."""
        with self.tx() as t:
            n = t.ex(
                "UPDATE alerty SET czas_potwierdzenia = ?, potwierdzil = ? "
                "WHERE id = ? AND czas_potwierdzenia IS NULL",
                (now, user, int(alert_id)),
            )
        return n == 1

    def rejected(self, limit: int = 100) -> list[dict]:
        pre, suf = self.top(limit)
        with self.tx() as t:
            rows = t.q(
                f"SELECT {pre}id, czas_odebrania, powod, szczegoly, zrodlo, tresc "
                f"FROM odrzucone_komunikaty ORDER BY id DESC{suf}"
            )
        for r in rows:
            r["czas_odebrania"] = self.ts(r["czas_odebrania"])
        return rows

    def occupancy_series(self, since: datetime) -> list[dict]:
        with self.tx() as t:
            rows = t.q(
                "SELECT czas, strefa, wolne, zajete, brak_danych FROM oblozenie_stref "
                "WHERE czas >= ? ORDER BY czas",
                (since,),
            )
        for r in rows:
            r["czas"] = self.ts(r["czas"])
            r["strefa"] = r["strefa"].strip()
        return rows

    # --- użytkownicy -------------------------------------------------------------------------
    def get_user(self, login: str) -> Optional[dict]:
        with self.tx() as t:
            return t.one("SELECT login, hash_hasla, rola FROM uzytkownicy WHERE login = ?", (login,))

    def upsert_user(self, login: str, password_hash: str, role: str, now: datetime) -> None:
        with self.tx() as t:
            if t.ex("UPDATE uzytkownicy SET hash_hasla = ?, rola = ? WHERE login = ?",
                    (password_hash, role, login)) == 0:
                t.ex("INSERT INTO uzytkownicy (login, hash_hasla, rola, utworzono) VALUES (?, ?, ?, ?)",
                     (login, password_hash, role, now))
