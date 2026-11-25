/*
  Czujnik miejsca parkingowego: ESP32 + ultradźwiękowy JSN-SR04T (lub HC-SR04).
  Grupa 2 (Sieroń, Zarzycki) – status: PRZYGOTOWANE, nietestowane na sprzęcie
  (w prototypie czujniki zastępuje symulator: src/simulator/edge.py, ta sama logika).

  F01: pomiar co 0,5 s; stan zatwierdzony po 7 kolejnych odczytach (3 s):
       wszystkie < 150 cm -> ZAJĘTE, wszystkie >= 200 cm -> WOLNE, inaczej bez zmiany.
  ZMIANA tylko przy zmianie zatwierdzonego stanu; HEARTBEAT co 60 s.
  Brak bufora: gdy nie ma Wi-Fi/MQTT, komunikat przepada (ograniczenie prototypu).

  Biblioteki: PubSubClient (Nick O'Leary). Płytka: ESP32 Dev Module.
  Dane dostępowe tylko w secrets.h (poza repozytorium) – wzór: secrets.h.example.

  Podłączenie: TRIG -> GPIO 5, ECHO -> GPIO 18 przez dzielnik napięcia 5 V -> 3,3 V
  (np. 1 kΩ / 2 kΩ), VCC czujnika 5 V, GND wspólne.
*/
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <time.h>
#include "secrets.h"   // WIFI_SSID, WIFI_PASS, MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, SPOT_ID, (MQTT_CA)

const int PIN_TRIG = 5;
const int PIN_ECHO = 18;

const unsigned long SAMPLE_MS = 500;
const unsigned long HEARTBEAT_MS = 60000;
const int CONFIRM_SAMPLES = 7;
const float OCCUPIED_BELOW_CM = 150.0;
const float FREE_FROM_CM = 200.0;
const float MAX_RANGE_CM = 450.0;

#ifdef MQTT_CA
WiFiClientSecure net;
#else
WiFiClient net;
#endif
PubSubClient mqtt(net);

float windowCm[CONFIRM_SAMPLES];
int windowCount = 0, windowPos = 0;
const char* confirmed = nullptr;   // nullptr = jeszcze brak zatwierdzonego stanu
float lastDistance = 0;
unsigned long lastSample = 0, lastHeartbeat = 0;
char topic[32];

float measureCm() {
  digitalWrite(PIN_TRIG, LOW);  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  unsigned long us = pulseIn(PIN_ECHO, HIGH, 30000);   // limit ok. 5 m
  if (us == 0) return MAX_RANGE_CM;                    // brak echa = nic w zasięgu
  float cm = us * 0.0343f / 2.0f;
  return cm > MAX_RANGE_CM ? MAX_RANGE_CM : cm;
}

void isoNow(char* out, size_t len) {
  time_t now = time(nullptr);
  struct tm t;
  gmtime_r(&now, &t);
  strftime(out, len, "%Y-%m-%dT%H:%M:%S.000Z", &t);
}

void publish(const char* state, const char* type) {
  if (!mqtt.connected()) return;                       // brak bufora – komunikat przepada
  char ts[32], payload[200];
  isoNow(ts, sizeof(ts));
  snprintf(payload, sizeof(payload),
           "{\"spot_id\":\"%s\",\"zone\":\"%c\",\"state\":\"%s\",\"distance_cm\":%.1f,"
           "\"msg_type\":\"%s\",\"event_time_utc\":\"%s\"}",
           SPOT_ID, SPOT_ID[0], state, lastDistance, type, ts);
  mqtt.publish(topic, payload);                        // PubSubClient: QoS 0 przy publikacji
}

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
}

void connectMqtt() {
  if (mqtt.connected() || WiFi.status() != WL_CONNECTED) return;
  char clientId[24];
  snprintf(clientId, sizeof(clientId), "czujnik-%s", SPOT_ID);
  mqtt.connect(clientId, MQTT_USER, MQTT_PASS);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  snprintf(topic, sizeof(topic), "parking/%c/%s", SPOT_ID[0], SPOT_ID);
  connectWifi();
  configTime(0, 0, "pool.ntp.org", "time.google.com");   // czas UTC do event_time_utc
#ifdef MQTT_CA
  net.setCACert(MQTT_CA);
#endif
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  connectMqtt();
  lastHeartbeat = millis();
}

void loop() {
  connectWifi();
  connectMqtt();
  mqtt.loop();

  unsigned long now = millis();
  if (now - lastSample < SAMPLE_MS) return;
  lastSample = now;

  lastDistance = measureCm();
  windowCm[windowPos] = lastDistance;
  windowPos = (windowPos + 1) % CONFIRM_SAMPLES;
  if (windowCount < CONFIRM_SAMPLES) windowCount++;

  if (windowCount == CONFIRM_SAMPLES) {
    bool allBelow = true, allAbove = true;
    for (int i = 0; i < CONFIRM_SAMPLES; i++) {
      if (windowCm[i] >= OCCUPIED_BELOW_CM) allBelow = false;
      if (windowCm[i] < FREE_FROM_CM) allAbove = false;
    }
    const char* candidate = allBelow ? "ZAJĘTE" : (allAbove ? "WOLNE" : nullptr);
    if (candidate && (confirmed == nullptr || strcmp(candidate, confirmed) != 0)) {
      confirmed = candidate;
      publish(confirmed, "ZMIANA");
    }
  }

  if (confirmed && now - lastHeartbeat >= HEARTBEAT_MS) {
    lastHeartbeat = now;
    publish(confirmed, "HEARTBEAT");
  }
}
