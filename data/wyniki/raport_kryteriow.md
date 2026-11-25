# Raport kryteriów sukcesu (LAB02, cz. 8)

Wygenerowano: 23:19:43 (CET), `python tools/kryteria.py`

| Kryterium | Wynik | Szczegóły |
|---|---|---|
| K1 | SPEŁNIONE | 20 z 20 komunikatów ZMIANA zapisanych |
| K2 | SPEŁNIONE | 10 z 10 zmian widocznych ≤ 5 s (śr. 1.09 s, maks. 1.93 s, odpytywanie co 2 s) |
| K3 | SPEŁNIONE | 10 wykryć 1–2,5 s: 0 ZMIANA, 0 nowych wpisów |
| K4 | SPEŁNIONE | 35 z 35 punktów kontrolnych zgodnych |
| K5 | SPEŁNIONE | 5 przebiegów: zawsze 1 alert, opóźnienie 180.3–189.8 s (limit 190 s), alert zamknięty przez pierwszy komunikat |

| Scenariusz | Wynik |
|---|---|
| Scenariusz 1 – zwykła praca | OK |
| Scenariusz 2 – strefa A się zapełnia | OK |
| Scenariusz 3 – awaria czujnika | OK |
| Scenariusz dodatkowy – krótkie wykrycie | OK |

Walidacja: 8 z 8 błędnych odrzuconych.

Pliki z danymi: `data/wyniki/*.csv`, logi symulatora: `data/logi/*.csv`.
