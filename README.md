# System monitorowania zajętości miejsc parkingowych

IoT i Cloud Computing, Collegium Da Vinci • LAB 10 – projekt końcowy • Grupa 2
Radosław Sieroń, Michał Zarzycki

Parking przy budynku uczelni: 90 miejsc w strefach A, B, C (A01–C30). Czujnik ultradźwiękowy z ESP32
przy każdym miejscu zatwierdza stan po 3 s i wysyła przez MQTT tylko zmiany (ZMIANA) oraz heartbeat
co 60 s. Chmura zapisuje stan i historię, liczy wolne miejsca w strefach (tablica przy wjeździe),
pokazuje mapę i po > 3 min ciszy ustawia BRAK DANYCH z jednym alertem dla zarządcy.

| Element | Status |
|---|---|
| Symulator 90 czujników (logika ESP32), odbiornik MQTT, kontrola braku danych, baza SQLite, aplikacja web, testy K1–K5 | **wdrożone i przetestowane lokalnie** |
| Azure SQL Database (`sql-parking-grupa2-rs/parking`): schemat, 90 miejsc, zapis stanu i historii zmian z odbiornika | **wdrożone i sprawdzone** 24.11.2026 – symulator → Mosquitto → odbiornik lokalny → Azure SQL (krok 5a) |
| Funkcje Azure (Odbiornik, Kontrola), wysyłka do IoT Hub, aplikacja na App Service | **przygotowane** – ten sam kod, wymaga wdrożenia na subskrypcji Azure for Students |
| Szkic ESP32 (`firmware/`) | **przygotowany**, nietestowany na sprzęcie |

## Struktura

```
src/parking/          rdzeń: model, walidacja, baza (SQLite / Azure SQL), serwis, odbiornik MQTT, web
  sql/                schematy bazy: sqlite.sql, azuresql.sql
  web/                Flask: tablica (/), mapa (/mapa), panel zarządcy (/panel), API
src/simulator/        symulator czujników, scenariusze z LAB02, pomiar K2
azure/                Azure Functions (Odbiornik, Kontrola), paczka App Service
firmware/             szkic ESP32 + czujnik ultradźwiękowy
mosquitto/config/     konfiguracja brokera i ACL (bez haseł)
tests/                pytest: reguły, walidacja, scenariusze 1–3 i dodatkowy, K1–K5, web
tools/                kryteria.py (raport K1–K5), analiza_logow.py (metoda z LAB08)
data/                 miejsca, przykładowe komunikaty, logi symulatora, wyniki testów
docs/                 Dokumentacja_LAB10_*.docx/.pdf, diagramy/ (.drawio + PDF, LAB05), prezentacja .pptx, img/
```

## 1. Instalacja (Python 3.10+)

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .                      # komendy python -m parking / python -m simulator
copy .env.example .env
```

### macOS (zsh) i Linux

```bash
python3 --version                     # musi być 3.10 lub nowszy
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .                      # komendy python -m parking / python -m simulator
cp -n .env.example .env               # -n: nie nadpisuje istniejącego .env
```

Uwagi do macOS:

- macOS nie ma polecenia `python`, tylko `python3`, dlatego venv tworzymy przez `python3`. Po
  `source .venv/bin/activate` (w prompcie widać `(.venv)`) `python` i `pip` wskazują na venv, więc
  wszystkie dalsze polecenia z README działają bez zmian. W każdym nowym terminalu aktywuj venv ponownie.
- `/usr/bin/python3` to Python 3.9 od Apple (Command Line Tools). Jest za stary, a `pip install -e .` kończy
  się błędem. Jeśli `python3 --version` pokazuje 3.9, zainstaluj Pythona z python.org albo
  `brew install python@3.13` i utwórz venv przez `python3.13 -m venv .venv`.
- Jeśli w prompcie widać `(base)` (Anaconda), najpierw wykonaj `conda deactivate`, żeby venv powstał
  z Pythona python.org lub Homebrew (patrz uwaga o sterowniku ODBC w kroku 5a).
- PyCharm: Settings → Project → Python Interpreter → Add Interpreter → Existing → `.venv/bin/python`.

W `.env` ustaw `SECRET_KEY` (`python -c "import secrets; print(secrets.token_hex(32))"`, na macOS bez
aktywnego venv: `python3 -c ...`) i hasła MQTT z kroku 3. Plik `.env` nie trafia do repozytorium ani do oddanej paczki.

## 2. Szybki podgląd bez brokera (tryb demo)

```bash
python -m parking init
python -m parking uzytkownik zarzadca     # hasło podajesz interaktywnie (min. 10 znaków)
python -m parking historia-demo           # syntetyczne próbki 7 dni do wykresu w panelu
python -m parking demo --awarie           # symulator + backend + web w jednym procesie
```

Otwórz http://127.0.0.1:8000 (tablica), `/mapa`, `/panel`. Tryb demo omija MQTT – służy jako plan
awaryjny na obronę. Właściwa architektura jest w kroku 3.

## 3. Uruchomienie lokalne z MQTT (architektura docelowa w wersji lokalnej)

Broker Mosquitto w Dockerze z logowaniem i ACL. Na macOS najpierw uruchom Docker Desktop (`open -a Docker`)
i poczekaj, aż `docker info` przestanie zgłaszać błąd. Potem utwórz użytkowników (hasła wpisz też do `.env`):

```bash
docker compose run --rm mosquitto mosquitto_passwd -c /mosquitto/config/passwd czujniki
docker compose run --rm mosquitto mosquitto_passwd /mosquitto/config/passwd odbiornik
docker compose up -d
```

Uruchamiaj te polecenia po jednym, bo każde pyta o hasło dwa razy. `-c` tworzy nowy plik i jest potrzebne
tylko przy pierwszej instalacji. Jeśli `mosquitto/config/passwd` już istnieje, Mosquitto 2.1 kończy się błędem
`Unable to open file /mosquitto/config/passwd for writing. File exists.`. Wtedy pomiń `-c`: polecenie bez `-c`
dodaje użytkownika albo zmienia jego hasło w istniejącym pliku. Po zmianie hasła przy działającym brokerze
wykonaj `docker compose restart mosquitto`.

Bez Dockera (macOS): `brew install mosquitto`, te same polecenia `mosquitto_passwd` na pliku
`mosquitto/config/passwd`, a w `mosquitto.conf` popraw ścieżki na lokalne.

Trzy terminale (z aktywnym `.venv`):

```bash
python -m parking start                   # odbiornik MQTT + kontrola co 10 s + web :8000
python -m simulator ruch                  # 90 czujników, losowy ruch (Ctrl+C kończy)
python -m simulator scenariusz 1          # albo scenariusz z karty LAB02 na żywo
```

Scenariusze na żywo: `1`, `2`, `3`, `4`, `k1`, `k3`. Scenariusz 3 trwa 21 min; na prezentacji użyj
`python -m simulator scenariusz 3 --przerwa-min 4`. Mapa z pomiarem K2: http://127.0.0.1:8000/mapa?pomiar=1.

Logi komunikatów symulatora zapisują się w `data/logi/symulator_*.csv`.

## 4. Testy, kryteria K1–K5 i analiza logów

```bash
python -m pytest                          # 67 testów (w tym K2 w czasie rzeczywistym, ok. 30 s)
python -m pytest -m "not wolny"           # bez K2, kilkanaście sekund
python tools/kryteria.py                  # scenariusze + K1–K5 -> data/wyniki/raport_kryteriow.md
python tools/analiza_logow.py data/logi/scenariusz_3.csv data/wyniki/historia_scenariusz_3.csv
python tools/zrzuty_ekranu.py             # opcjonalnie: zrzuty ekranu (wymaga playwright + Chrome)
```

Scenariusze i kryteria K1, K3–K5 działają w zegarze wirtualnym: ten sam kod symulatora i backendu,
ale 20-minutowa przerwa ze scenariusza 3 trwa ułamek sekundy. K2 mierzy prawdziwe opóźnienie
(aplikacja web na losowym porcie, odpytywanie co 2 s jak w przeglądarce).

## 5. Tryb Azure (Azure for Students)

Zgodnie z diagramem `2_Architektura`: symulator → IoT Hub → funkcja Odbiornik → Azure SQL ← funkcja
Kontrola; aplikacja web na App Service. Wszystkie hasła i connection stringi trafiają tylko do
ustawień aplikacji / Key Vault, nigdy do plików.

1. **Azure SQL** (z LAB1): w Query editor uruchom `src/parking/sql/azuresql.sql`. Ustaw administratora
   Microsoft Entra na serwerze, potem utwórz użytkowników tożsamości zarządzanych (komentarz na końcu pliku).
2. **IoT Hub F1**: `az iot hub create -n <hub> -g <rg> --sku F1 --partition-count 2`,
   urządzenie: `az iot hub device-identity create --hub-name <hub> -d symulator-01`,
   grupa odbiorców: `az iot hub consumer-group create --hub-name <hub> -n odbiornik`.
   Connection string urządzenia wpisz lokalnie do `.env` (`IOTHUB_DEVICE_CONNECTION_STRING`).
3. **Function App** (Python 3.11, Linux, plan Consumption), włącz tożsamość zarządzaną
   (`az functionapp identity assign`). Ustawienia: `DATABASE_URL` (z `Authentication=ActiveDirectoryMsi`),
   `IOTHUB_EVENTHUB_CONNECTION` (referencja do Key Vault), `IOTHUB_EVENTHUB_NAME`,
   `IOTHUB_CONSUMER_GROUP=odbiornik`, `GATEWAY_IDS=symulator-01`.
4. `python azure/przygotuj_paczki.py`, potem `cd azure/functionapp && func azure functionapp publish <nazwa>`.
5. **App Service**: `cd azure/webapp && az webapp up -n <nazwa> --runtime PYTHON:3.11`,
   polecenie startowe `gunicorn --bind=0.0.0.0 parking.wsgi:app`, ustawienia `DATABASE_URL`, `SECRET_KEY`,
   tożsamość zarządzana. Konto zarządcy: `python -m parking uzytkownik` z `DATABASE_URL` Azure w `.env`.
6. Test: `pip install -r requirements-azure.txt`, `python -m simulator scenariusz 1 --wyjscie iothub`.

Limit IoT Hub F1 to 8 000 komunikatów na dobę; 90 czujników z heartbeatem co 60 s wysyła ok. 130 000.
Symulator ma bezpiecznik `IOTHUB_MAX_MESSAGES=7000`. Pełne testy robimy w trybie lokalnym.

### 5a. Azure SQL z lokalnym odbiornikiem (wykonane 24.11.2026)

Pierwszy krok wdrożenia: lokalny łańcuch z kroku 3 zapisuje do Azure SQL zamiast do SQLite.
Zmienia się tylko `DATABASE_URL`, kod jest ten sam.

1. Sterownik ODBC na macOS: `brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release`,
   `brew install msodbcsql18`.
2. W `.env` (tylko lokalnie, plik poza repozytorium) ustaw połączenie loginem SQL:
   `DATABASE_URL=mssql://Driver=/opt/homebrew/lib/libmsodbcsql.18.dylib;Server=tcp:<serwer>.database.windows.net,1433;Database=parking;Uid=<login>;Pwd=<hasło>;Encrypt=yes;TrustServerCertificate=no`.
   Pełna ścieżka sterownika jest potrzebna, bo unixODBC z Anacondy nie czyta `/opt/homebrew/etc/odbcinst.ini`.
   Z Pythonem z Homebrew lub venv wystarczy `Driver={ODBC Driver 18 for SQL Server}`.
3. Portal Azure → serwer SQL → **Sieć** → **Dodaj adres IPv4 klienta** → Zapisz (reguła zapory tylko dla IP zespołu).
4. `python -m parking init` (schemat + 90 miejsc), potem `python -m parking start` i `python -m simulator ruch` jak w kroku 3.
5. Sprawdzenie w **Edytorze zapytań** bazy w portalu:

```sql
SELECT strefa, stan, COUNT(*) AS liczba FROM miejsca GROUP BY strefa, stan;
SELECT TOP 20 spot_id, nowy_stan, czas_zmiany, zrodlo FROM historia_zmian ORDER BY id DESC;
```

Wynik: w bazie jest 90 miejsc. W chwili zrzutu strefa A miała 9 WOLNE / 21 ZAJĘTE, strefa B 14 / 16, a strefa C 10 / 20.
Historia zmian rośnie z każdą zmianą z symulatora (`zrodlo = ZMIANA`). Zrzuty: `docs/img/azure_sql_miejsca.png`,
`docs/img/azure_sql_historia.png`.

**Czas w bazie jest w UTC.** Kolumny `DATETIME2` przechowują UTC bez strefy, np. `18:03:11` w bazie to 19:03:11
czasu polskiego zimą (CET = UTC+1, latem CEST = UTC+2). Tak ma być: aplikacja web pokazuje czas w strefie
`Europe/Warsaw`, a porównując bazę z tablicą trzeba dodać tę różnicę.

Typowe błędy na macOS:

- `Can't open lib 'ODBC Driver 18 for SQL Server'` – brak sterownika (punkt 1) albo nazwa sterownika zamiast
  pełnej ścieżki w Anacondzie (punkt 2).
- `SSL Provider: OpenSSL library could not be loaded` – sterownik obsługuje tylko OpenSSL 1.1 / 3, a Homebrew
  ustawia `openssl` na wersję 4. Naprawa: `brew install openssl@3`, `ln -sfn openssl@3 /opt/homebrew/opt/openssl`.
  Po `brew upgrade` link może wrócić na wersję 4, wtedy powtórz `ln`.
- `certificate verify failed: unable to get local issuer certificate` – OpenSSL 3 nie ma pliku certyfikatów CA:
  `ln -sfn /opt/homebrew/opt/ca-certificates/share/ca-certificates/cacert.pem /opt/homebrew/etc/openssl@3/cert.pem`.
- `Client with IP address '…' is not allowed to access the server` – brak reguły zapory dla Twojego IP (punkt 3).

## 6. Bezpieczeństwo

- Brak sekretów w plikach: `.env`, `passwd`, `secrets.h`, `local.settings.json` są w `.gitignore`;
  w repozytorium tylko wzory (`*.example`).
- MQTT: logowanie obowiązkowe, ACL (symulator tylko zapis, odbiornik tylko odczyt, czujnik fizyczny
  tylko swój temat), broker dostępny tylko z localhost; opcjonalnie TLS 8883. W Azure: tożsamość
  urządzenia w IoT Hub i TLS.
- Odbiornik waliduje każdy komunikat (pola, zakresy, czas, temat lub urządzenie zgodne z miejscem,
  rozmiar ≤ 1 KB). Błędny trafia do `odrzucone_komunikaty` i nie zmienia stanu.
- Baza: wyłącznie zapytania parametryzowane; w Azure tożsamość zarządzana i minimalne uprawnienia.
- Web: kierowca tylko odczyt; panel zarządcy po logowaniu (hasło jako skrót scrypt), CSRF,
  limit 5 nieudanych logowań na 5 min, nagłówki CSP / X-Frame-Options / nosniff, ciasteczko HttpOnly.

TLS lokalnie (opcjonalnie): wygeneruj CA i certyfikat serwera do `mosquitto/config/certs/`
(`openssl req -x509 ...`), odkomentuj sekcję TLS w `mosquitto.conf` i port 8883 w `docker-compose.yml`,
w `.env` ustaw `MQTT_PORT=8883`, `MQTT_TLS=true`, `MQTT_CA_FILE=mosquitto/config/certs/ca.crt`.

## 7. Dane

| Plik | Zawartość |
|---|---|
| `data/miejsca.csv` | 90 miejsc, strefy, tematy MQTT, identyfikatory urządzeń |
| `data/przyklady_komunikatow.jsonl` | poprawne i błędne komunikaty z powodem odrzucenia |
| `data/logi/*.csv` | logi symulatora ze scenariuszy (wysłane i utracone komunikaty) |
| `data/wyniki/*.csv`, `raport_kryteriow.md` | dowody K1–K5, punkty kontrolne, historia, alerty |
| `data/historia_7dni_syntetyczna.csv` | **syntetyczne** próbki obłożenia do wykresu (nie pomiar) |

## 8. Ograniczenia prototypu

- Czujniki są symulowane; progi 150/200 cm i 3 s wymagają kalibracji na parkingu.
- ESP32 nie buforuje komunikatów: w czasie przerwy łączności historia jest niepełna.
- Kontrola sprawdza ciszę co 10 s, więc BRAK DANYCH pojawia się 180–190 s po ostatnim komunikacie.
- Na subskrypcji działa tylko Azure SQL (krok 5a). IoT Hub, funkcje i App Service są przygotowane, ale niewdrożone.
- Do Azure SQL łączymy się z komputera zespołu loginem SQL i regułą zapory na jedno IP. Docelowo:
  tożsamość zarządzana funkcji i aplikacji, bez publicznego dostępu do bazy.
- Wykres 7 dni w demonstracji korzysta z danych syntetycznych.

## 9. Wkład autorów

| Osoba | Kod | Dokumentacja i diagramy |
|---|---|---|
| Radosław Sieroń | symulator i reguła 3 s (`src/simulator`), broker i bezpieczeństwo MQTT, szkic ESP32, testy K1, K3, K5 | architektura, bezpieczeństwo, diagram 2 |
| Michał Zarzycki | serwis, baza i kontrola braku danych (`src/parking`), aplikacja web, testy K2, K4 i scenariusze | analiza wymagań, testy, wnioski, diagramy 1 i 3 |

Wspólnie: tryb Azure, przegląd kodu i dokumentacji, przygotowanie obrony.
