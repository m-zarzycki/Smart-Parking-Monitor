-- Schemat bazy dla trybu Azure (Azure SQL Database).
-- Uruchom raz w Query editor w portalu Azure albo przez sqlcmd / Azure Data Studio.
-- Nie zawiera żadnych haseł. Dostęp aplikacji i funkcji: tożsamość zarządzana (Microsoft Entra ID).

IF OBJECT_ID(N'dbo.miejsca', N'U') IS NULL
CREATE TABLE dbo.miejsca (
    spot_id                     NCHAR(3)      NOT NULL PRIMARY KEY,
    strefa                      NCHAR(1)      NOT NULL CHECK (strefa IN (N'A', N'B', N'C')),
    stan                        NVARCHAR(12)  NOT NULL CHECK (stan IN (N'ZAJĘTE', N'WOLNE', N'BRAK DANYCH')),
    odleglosc_cm                REAL          NULL,
    czas_zdarzenia              DATETIME2(3)  NULL,
    czas_ostatniego_komunikatu  DATETIME2(3)  NULL,
    czas_zmiany_stanu           DATETIME2(3)  NULL
);
GO

IF OBJECT_ID(N'dbo.historia_zmian', N'U') IS NULL
CREATE TABLE dbo.historia_zmian (
    id              BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    spot_id         NCHAR(3)      NOT NULL REFERENCES dbo.miejsca (spot_id),
    strefa          NCHAR(1)      NOT NULL,
    nowy_stan       NVARCHAR(12)  NOT NULL CHECK (nowy_stan IN (N'ZAJĘTE', N'WOLNE', N'BRAK DANYCH')),
    czas_zmiany     DATETIME2(3)  NOT NULL,
    czas_odebrania  DATETIME2(3)  NOT NULL,
    zrodlo          NVARCHAR(10)  NOT NULL CHECK (zrodlo IN (N'ZMIANA', N'HEARTBEAT', N'KONTROLA', N'START'))
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_historia_czas')
    CREATE INDEX ix_historia_czas ON dbo.historia_zmian (czas_zmiany);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_historia_miejsce')
    CREATE INDEX ix_historia_miejsce ON dbo.historia_zmian (spot_id, czas_zmiany);
GO

IF OBJECT_ID(N'dbo.alerty', N'U') IS NULL
CREATE TABLE dbo.alerty (
    id                          BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    spot_id                     NCHAR(3)      NOT NULL REFERENCES dbo.miejsca (spot_id),
    czas_ostatniego_komunikatu  DATETIME2(3)  NULL,
    czas_otwarcia               DATETIME2(3)  NOT NULL,
    czas_zamkniecia             DATETIME2(3)  NULL,
    czas_potwierdzenia          DATETIME2(3)  NULL,
    potwierdzil                 NVARCHAR(64)  NULL
);
GO
-- Najwyżej jeden aktywny alert na miejsce.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ux_alerty_aktywny')
    CREATE UNIQUE INDEX ux_alerty_aktywny ON dbo.alerty (spot_id) WHERE czas_zamkniecia IS NULL;
GO

IF OBJECT_ID(N'dbo.odrzucone_komunikaty', N'U') IS NULL
CREATE TABLE dbo.odrzucone_komunikaty (
    id              BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    czas_odebrania  DATETIME2(3)   NOT NULL,
    powod           NVARCHAR(40)   NOT NULL,
    szczegoly       NVARCHAR(200)  NULL,
    zrodlo          NVARCHAR(100)  NULL,
    tresc           NVARCHAR(300)  NULL
);
GO

IF OBJECT_ID(N'dbo.oblozenie_stref', N'U') IS NULL
CREATE TABLE dbo.oblozenie_stref (
    id           BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    czas         DATETIME2(3)  NOT NULL,
    strefa       NCHAR(1)      NOT NULL CHECK (strefa IN (N'A', N'B', N'C')),
    wolne        INT           NOT NULL,
    zajete       INT           NOT NULL,
    brak_danych  INT           NOT NULL
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_oblozenie_czas')
    CREATE INDEX ix_oblozenie_czas ON dbo.oblozenie_stref (czas);
GO

IF OBJECT_ID(N'dbo.uzytkownicy', N'U') IS NULL
CREATE TABLE dbo.uzytkownicy (
    login       NVARCHAR(64)   NOT NULL PRIMARY KEY,
    hash_hasla  NVARCHAR(256)  NOT NULL,
    rola        NVARCHAR(16)   NOT NULL CHECK (rola IN (N'zarzadca')),
    utworzono   DATETIME2(3)   NOT NULL
);
GO

IF OBJECT_ID(N'dbo.system', N'U') IS NULL
CREATE TABLE dbo.system (
    klucz    NVARCHAR(64)   NOT NULL PRIMARY KEY,
    wartosc  NVARCHAR(256)  NOT NULL
);
GO

-- Uprawnienia (najmniejsze potrzebne). Nazwy tożsamości zarządzanych zastąp własnymi.
-- Funkcje (Odbiornik, Kontrola) zapisują dane:
--   CREATE USER [func-parking-grupa2] FROM EXTERNAL PROVIDER;
--   ALTER ROLE db_datareader ADD MEMBER [func-parking-grupa2];
--   ALTER ROLE db_datawriter ADD MEMBER [func-parking-grupa2];
-- Aplikacja webowa tylko czyta i potwierdza alerty:
--   CREATE USER [app-parking-grupa2] FROM EXTERNAL PROVIDER;
--   ALTER ROLE db_datareader ADD MEMBER [app-parking-grupa2];
--   GRANT UPDATE (czas_potwierdzenia, potwierdzil) ON dbo.alerty TO [app-parking-grupa2];
