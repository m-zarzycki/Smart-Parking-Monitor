// Tablica i mapa: odpytywanie /api/stan co 2 s (HTTPS/JSON, diagram 2_Architektura).
(function () {
  "use strict";
  const POLL_MS = 2000;
  const STALE_MS = 10000;
  const TZ = "Europe/Warsaw";
  const measure = new URLSearchParams(location.search).get("pomiar") === "1";
  const lastState = {};
  const delays = [];
  let lastOk = 0;

  function fmtTime(iso) {
    if (!iso) return "–";
    return new Date(iso).toLocaleTimeString("pl-PL", { timeZone: TZ });
  }
  function fmtDateTime(iso) {
    if (!iso) return "brak komunikatu";
    return new Date(iso).toLocaleString("pl-PL", { timeZone: TZ });
  }
  function cls(state) {
    if (state === "WOLNE") return "st-wolne";
    if (state === "ZAJĘTE") return "st-zajete";
    return "st-brak";
  }
  function short(state) {
    if (state === "WOLNE") return "W";
    if (state === "ZAJĘTE") return "Z";
    return "–";
  }

  function renderBoard(tablica) {
    for (const zone of ["A", "B", "C"]) {
      const el = document.getElementById("board-" + zone);
      if (!el) continue;
      const label = tablica[zone].napis;
      el.textContent = label;
      el.classList.toggle("full", label === "PEŁNA");
      el.classList.toggle("nodata", label === "BRAK DANYCH");
    }
  }

  function renderMap(data) {
    const serverTime = Date.parse(data.czas_serwera);
    for (const s of data.miejsca) {
      const el = document.getElementById("spot-" + s.id);
      if (!el) continue;
      el.className = "spot " + cls(s.stan);
      el.querySelector(".sst").textContent = short(s.stan);
      el.title = s.id + ": " + s.stan + "\nzmiana: " + fmtDateTime(s.czas_zmiany_stanu) +
        "\nostatni komunikat: " + fmtDateTime(s.czas_ostatniego_komunikatu);
      // Pomiar K2: czas od odebrania komunikatu ZMIANA w chmurze do pobrania danych przez widok.
      if (measure && lastState[s.id] && lastState[s.id] !== s.stan && s.czas_ostatniego_komunikatu &&
          s.stan !== "BRAK DANYCH") {
        const d = (serverTime - Date.parse(s.czas_ostatniego_komunikatu)) / 1000;
        delays.push(d);
        console.log("[K2]", s.id, s.stan, "opóźnienie", d.toFixed(2), "s");
      }
      lastState[s.id] = s.stan;
    }
    if (measure && delays.length) {
      document.getElementById("measure").hidden = false;
      const sum = delays.reduce((a, b) => a + b, 0);
      document.getElementById("k2-n").textContent = delays.length;
      document.getElementById("k2-avg").textContent = (sum / delays.length).toFixed(2);
      document.getElementById("k2-max").textContent = Math.max(...delays).toFixed(2);
      document.getElementById("k2-ok").textContent =
        delays.filter((d) => d <= 5).length + " z " + delays.length;
    }
  }

  async function poll() {
    try {
      const resp = await fetch("/api/stan", { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      renderBoard(data.tablica);
      if (data.miejsca) renderMap(data);
      document.getElementById("updated").textContent = fmtTime(data.czas_serwera);
      lastOk = Date.now();
    } catch (err) {
      console.warn("Błąd pobierania stanu:", err);
    }
    const stale = document.getElementById("stale");
    if (stale) stale.hidden = Date.now() - lastOk < STALE_MS;
  }

  poll();
  setInterval(poll, POLL_MS);
})();
