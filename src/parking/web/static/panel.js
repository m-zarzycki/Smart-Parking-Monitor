// Panel zarządcy: alerty (z potwierdzaniem), wykres 7 dni, historia, odrzucone komunikaty.
(function () {
  "use strict";
  const TZ = "Europe/Warsaw";
  const csrf = document.getElementById("csrf").getAttribute("content");
  const COLORS = { A: "#0072B2", B: "#E69F00", C: "#009E73" };

  function fmt(iso) {
    if (!iso) return "–";
    return new Date(iso).toLocaleString("pl-PL", { timeZone: TZ });
  }
  function cell(row, text) {
    const td = document.createElement("td");
    td.textContent = text;
    row.appendChild(td);
    return td;
  }
  function fillTable(id, rows, build, emptyText) {
    const tbody = document.querySelector("#" + id + " tbody");
    tbody.replaceChildren();
    if (!rows.length) {
      const tr = document.createElement("tr");
      const td = cell(tr, emptyText || "Brak danych");
      td.colSpan = document.querySelectorAll("#" + id + " thead th").length;
      tbody.appendChild(tr);
      return;
    }
    for (const r of rows) {
      const tr = document.createElement("tr");
      build(tr, r);
      tbody.appendChild(tr);
    }
  }
  async function getJSON(url) {
    const resp = await fetch(url, { cache: "no-store" });
    if (resp.status === 401) { location.href = "/logowanie?next=/panel"; throw new Error("401"); }
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    return resp.json();
  }

  async function acknowledge(id, btn) {
    btn.disabled = true;
    const resp = await fetch("/api/alerty/" + id + "/potwierdz", {
      method: "POST", headers: { "X-CSRF-Token": csrf },
    });
    if (!resp.ok && resp.status !== 409) btn.disabled = false;
    loadAlerts();
  }

  async function loadAlerts() {
    const all = await getJSON("/api/alerty");
    const active = all.filter((a) => !a.czas_zamkniecia);
    const closed = all.filter((a) => a.czas_zamkniecia).slice(0, 20);
    document.getElementById("alert-count").textContent = active.length;
    fillTable("alerts", active, (tr, a) => {
      cell(tr, a.miejsce);
      cell(tr, a.czas_ostatniego_komunikatu ? fmt(a.czas_ostatniego_komunikatu) : "brak od uruchomienia");
      cell(tr, fmt(a.czas_otwarcia));
      cell(tr, a.czas_potwierdzenia ? fmt(a.czas_potwierdzenia) + " (" + a.potwierdzil + ")" : "niepotwierdzony");
      const td = cell(tr, "");
      if (!a.czas_potwierdzenia) {
        const b = document.createElement("button");
        b.textContent = "Potwierdź";
        b.addEventListener("click", () => acknowledge(a.id, b));
        td.appendChild(b);
      }
    }, "Brak aktywnych alertów – wszystkie czujniki nadają.");
    fillTable("closed", closed, (tr, a) => {
      cell(tr, a.miejsce);
      cell(tr, fmt(a.czas_ostatniego_komunikatu));
      cell(tr, fmt(a.czas_otwarcia));
      cell(tr, fmt(a.czas_zamkniecia));
      const from = a.czas_ostatniego_komunikatu || a.czas_otwarcia;
      const mins = (Date.parse(a.czas_zamkniecia) - Date.parse(from)) / 60000;
      cell(tr, mins.toFixed(1) + " min");
      cell(tr, a.potwierdzil || "–");
    }, "Brak zamkniętych alertów.");
  }

  async function loadTables() {
    const hist = await getJSON("/api/historia?limit=15");
    fillTable("history", hist, (tr, h) => {
      cell(tr, fmt(h.czas_zmiany)); cell(tr, h.miejsce); cell(tr, h.nowy_stan); cell(tr, h.zrodlo);
    });
    const rej = await getJSON("/api/odrzucone");
    fillTable("rejected", rej.slice(0, 20), (tr, r) => {
      cell(tr, fmt(r.czas_odebrania)); cell(tr, r.powod); cell(tr, r.szczegoly || ""); cell(tr, r.zrodlo || "");
    }, "Brak odrzuconych komunikatów.");
  }

  // --- wykres SVG bez bibliotek zewnętrznych (CSP: tylko 'self') ---------------------------
  function svg(tag, attrs, text) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (text !== undefined) el.textContent = text;
    return el;
  }
  async function loadChart() {
    const rows = await getJSON("/api/oblozenie?dni=7");
    const box = document.getElementById("chart");
    box.replaceChildren();
    const note = document.getElementById("chart-note");
    if (!rows.length) { note.textContent = "Brak próbek obłożenia (zapisywane co 5 min)."; return; }
    const W = 900, H = 260, L = 40, R = 90, T = 10, B = 30;
    const times = rows.map((r) => Date.parse(r.czas));
    const t0 = Math.min(...times), t1 = Math.max(...times) || t0 + 1;
    const x = (t) => L + (W - L - R) * (t1 === t0 ? 0 : (t - t0) / (t1 - t0));
    const y = (v) => T + (H - T - B) * (1 - v / 30);
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });
    for (const v of [0, 10, 20, 30]) {
      s.appendChild(svg("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }));
      s.appendChild(svg("text", { x: L - 6, y: y(v) + 4, class: "axis", "text-anchor": "end" }, v));
    }
    const day = 86400000;
    for (let t = Math.ceil(t0 / day) * day; t <= t1; t += day) {
      const label = new Date(t).toLocaleDateString("pl-PL", { timeZone: TZ, day: "2-digit", month: "2-digit" });
      s.appendChild(svg("line", { x1: x(t), x2: x(t), y1: T, y2: H - B, class: "grid" }));
      s.appendChild(svg("text", { x: x(t), y: H - 10, class: "axis", "text-anchor": "middle" }, label));
    }
    const labels = [];
    for (const zone of ["A", "B", "C"]) {
      const pts = rows.filter((r) => r.strefa === zone)
        .map((r) => `${x(Date.parse(r.czas)).toFixed(1)},${y(r.wolne).toFixed(1)}`).join(" ");
      s.appendChild(svg("polyline", { points: pts, fill: "none", stroke: COLORS[zone], "stroke-width": 1.6 }));
      const last = rows.filter((r) => r.strefa === zone).pop();
      if (last) labels.push({ zone, value: last.wolne, y: y(last.wolne) + 4 });
    }
    // Etykiety na końcu linii rozsunięte o min. 15 px, żeby się nie nakładały.
    labels.sort((a, b) => a.y - b.y);
    for (let i = 1; i < labels.length; i++) {
      labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 15);
    }
    for (const l of labels) {
      s.appendChild(svg("text", { x: W - R + 8, y: l.y, fill: COLORS[l.zone], class: "lbl" },
        `Strefa ${l.zone}: ${l.value}`));
    }
    box.appendChild(s);
    note.textContent = "Oś Y: liczba wolnych miejsc (0–30 na strefę). Próbki co 5 min, czas lokalny.";
  }

  async function refresh() {
    try { await Promise.all([loadAlerts(), loadTables()]); } catch (e) { console.warn(e); }
  }
  refresh();
  loadChart().catch(console.warn);
  setInterval(refresh, 5000);
  setInterval(() => loadChart().catch(console.warn), 300000);
})();
