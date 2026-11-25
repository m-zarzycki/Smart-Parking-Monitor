-- Schemat bazy dla trybu lokalnego (SQLite).
-- Te same tabele i kolumny co w Azure SQL (azuresql.sql); czasy w UTC (ISO 8601).

CREATE TABLE IF NOT EXISTS miejsca (
    spot_id                     TEXT PRIMARY KEY CHECK (length(spot_id) = 3),
    strefa                      TEXT NOT NULL CHECK (strefa IN ('A', 'B', 'C')),
    stan                        TEXT NOT NULL CHECK (stan IN ('ZAJĘTE', 'WOLNE', 'BRAK DANYCH')),
    odleglosc_cm                REAL,
    czas_zdarzenia              TEXT,   -- czas ostatniego komunikatu wg czujnika
    czas_ostatniego_komunikatu  TEXT,   -- czas odebrania ostatniego komunikatu w chmurze
    czas_zmiany_stanu           TEXT    -- kiedy stan miejsca zmienił się ostatnio
);

CREATE TABLE IF NOT EXISTS historia_zmian (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    spot_id         TEXT NOT NULL REFERENCES miejsca (spot_id),
    strefa          TEXT NOT NULL,
    nowy_stan       TEXT NOT NULL CHECK (nowy_stan IN ('ZAJĘTE', 'WOLNE', 'BRAK DANYCH')),
    czas_zmiany     TEXT NOT NULL,      -- czas zdarzenia (dla BRAK DANYCH: czas wykrycia)
    czas_odebrania  TEXT NOT NULL,      -- czas odebrania / zapisu w chmurze
    zrodlo          TEXT NOT NULL CHECK (zrodlo IN ('ZMIANA', 'HEARTBEAT', 'KONTROLA', 'START'))
);
CREATE INDEX IF NOT EXISTS ix_historia_czas ON historia_zmian (czas_zmiany);
CREATE INDEX IF NOT EXISTS ix_historia_miejsce ON historia_zmian (spot_id, czas_zmiany);

CREATE TABLE IF NOT EXISTS alerty (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    spot_id                     TEXT NOT NULL REFERENCES miejsca (spot_id),
    czas_ostatniego_komunikatu  TEXT,   -- ostatni komunikat przed przerwą (NULL = brak od uruchomienia)
    czas_otwarcia               TEXT NOT NULL,
    czas_zamkniecia             TEXT,
    czas_potwierdzenia          TEXT,
    potwierdzil                 TEXT
);
-- Najwyżej jeden aktywny alert na miejsce (reguła „jeden alert na przerwę”).
CREATE UNIQUE INDEX IF NOT EXISTS ux_alerty_aktywny ON alerty (spot_id) WHERE czas_zamkniecia IS NULL;

CREATE TABLE IF NOT EXISTS odrzucone_komunikaty (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    czas_odebrania  TEXT NOT NULL,
    powod           TEXT NOT NULL,
    szczegoly       TEXT,
    zrodlo          TEXT,               -- temat MQTT albo identyfikator urządzenia
    tresc           TEXT                -- wycinek treści (max 300 znaków)
);
CREATE INDEX IF NOT EXISTS ix_odrzucone_czas ON odrzucone_komunikaty (czas_odebrania);

-- Próbki obłożenia stref co 5 min (wykres „ostatnie 7 dni” w panelu zarządcy).
CREATE TABLE IF NOT EXISTS oblozenie_stref (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    czas         TEXT NOT NULL,
    strefa       TEXT NOT NULL CHECK (strefa IN ('A', 'B', 'C')),
    wolne        INTEGER NOT NULL,
    zajete       INTEGER NOT NULL,
    brak_danych  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_oblozenie_czas ON oblozenie_stref (czas);

CREATE TABLE IF NOT EXISTS uzytkownicy (
    login       TEXT PRIMARY KEY,
    hash_hasla  TEXT NOT NULL,          -- skrót hasła (scrypt/pbkdf2), nigdy hasło jawne
    rola        TEXT NOT NULL CHECK (rola IN ('zarzadca')),
    utworzono   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system (
    klucz    TEXT PRIMARY KEY,
    wartosc  TEXT NOT NULL
);
