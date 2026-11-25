# Analiza logów – scenariusz_3

Źródła: `data/logi/scenariusz_3.csv` (1980 wierszy), `data/wyniki/historia_scenariusz_3.csv` (92 wpisów). Czas lokalny CET (UTC+1).

## E1. Integralność danych

| Miara | Wartość |
|---|---|
| Komunikaty wygenerowane przez czujniki | 1980 |
| Wysłane (dostarczone do brokera) | 1961 |
| Utracone (brak łączności, brak bufora) | 19 |
| ZMIANA / HEARTBEAT wysłane | 90 / 1871 |
| Duplikaty (to samo miejsce, typ i czas) | 0 |
| ZMIANA z odpowiednim wpisem w historii | 90 z 90 |

## Luki w komunikatach (> 61 s między kolejnymi komunikatami czujnika)

| Miejsce | Ostatni przed luką | Pierwszy po luce | Luka | Brakujące heartbeaty |
|---|---|---|---|---|
| C05 | 11:00:00 | 11:20:00 | 20.0 min | 19 |

## Reakcja systemu (historia zmian)

- C05: BRAK DANYCH o 11:03:10, powrót: WOLNE o 11:20:00 (HEARTBEAT)

## Ustalenia

- **Obserwacja:** brak komunikatów C05 przez 20.0 min. **Dowód z logu:** 19 komunikatów z flagą „brak łączności”, ostatni wysłany 11:00:00, następny 11:20:00. **Dowód z bazy:** BRAK DANYCH o 11:03:10 (źródło KONTROLA). **Wniosek:** przerwa łączności czujnika, komunikaty nie były buforowane, więc historia z tego okresu jest niepełna; stan miejsca w tym czasie jest nieznany (nie zgadujemy). **Pewność:** wysoka – oba źródła są zgodne.
- Brak duplikatów; gdyby wystąpiły (QoS 1), odbiornik traktuje drugi egzemplarz jako zgodny ze stanem i nie tworzy wpisu w historii.
