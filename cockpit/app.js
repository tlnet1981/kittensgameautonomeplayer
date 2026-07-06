/* Cockpit-Kern: WebSocket-Client, View-Model-Store, globale Leiste, Live-Feed.
   Tab-spezifisches Rendering liegt in tabs/*.js und registriert sich über
   KGP.onUpdate(fn). Kein Framework, kein Build-Step. */

window.KGP = (() => {
  const store = {
    status: null,      // StatusVM
    economy: null,     // EconomyVM
    population: null,  // PopulationVM
    health: null,      // HealthVM
    connected: false,
  };
  const updateHandlers = [];
  const eventHandlers = [];

  // ---------- Formatierung ----------
  function fmtNum(v, digits) {
    if (v === null || v === undefined) return "–";
    const abs = Math.abs(v);
    if (abs >= 1e9) return (v / 1e9).toFixed(2) + "G";
    if (abs >= 1e6) return (v / 1e6).toFixed(2) + "M";
    if (abs >= 1e4) return (v / 1e3).toFixed(1) + "K";
    if (abs >= 100) return v.toFixed(0);
    return v.toFixed(digits === undefined ? 2 : digits);
  }
  function fmtRate(v) {
    if (v === null || v === undefined) return "–";
    const s = fmtNum(v);
    return (v > 0 ? "+" : "") + s;
  }
  function fmtDuration(sec) {
    if (sec === null || sec === undefined || !isFinite(sec)) return "–";
    if (sec < 0) sec = 0;
    if (sec < 90) return Math.round(sec) + "s";
    const m = Math.floor(sec / 60), s = Math.round(sec % 60);
    if (m < 90) return m + ":" + String(s).padStart(2, "0") + " min";
    const h = Math.floor(m / 60);
    return h + "h " + String(m % 60).padStart(2, "0") + "m";
  }
  function fmtClock(ts) {
    const d = new Date(ts * 1000);
    return d.toTimeString().slice(0, 8);
  }

  // ---------- Steuerung ----------
  async function control(cmd) {
    try {
      await fetch("/api/control/" + cmd, { method: "POST" });
    } catch (e) { console.error("control failed", e); }
  }

  // ---------- Globale Leiste ----------
  function renderGlobalBar() {
    const s = store.status;
    const statePill = document.getElementById("gb-state");
    const state = s ? s.agentState : "IDLE";
    statePill.textContent = state;
    statePill.className = "state-pill state-" + state;

    if (s) {
      document.getElementById("gb-phase").textContent = s.run.phase || "–";
      document.getElementById("gb-run").textContent = s.run.type || "–";
      document.getElementById("gb-objective").textContent = s.run.objective || "–";
      document.getElementById("gb-year").textContent = s.calendar.year ?? "–";
      document.getElementById("gb-season").textContent =
        (s.calendar.season ?? "–") + (s.calendar.day !== null ? " · Tag " + s.calendar.day : "");
      document.getElementById("gb-kittens").textContent = s.kittens + " / " + s.maxKittens;
      document.getElementById("gb-paragon").textContent =
        fmtNum(s.paragon, 0) + (s.resetParagon ? " (+" + s.resetParagon + ")" : "");

      const vg = s.versionGuard || {};
      const badge = document.getElementById("gb-version");
      if (vg.gameVersion) {
        badge.textContent = "v" + vg.gameVersion + " r" + vg.buildRevision;
        badge.className = "version-badge " + (vg.match ? "ok" : "mismatch");
        badge.title = vg.match
          ? "Spielversion entspricht der Referenzversion der Spezifikation."
          : "Abweichung von Referenz v" + vg.referenceVersion + " r" + vg.referenceBuild
            + " — Agent läuft im toleranten Modus.";
      }
    }

    const h = store.health;
    const dot = document.getElementById("gb-health");
    dot.className = "health-dot " + (h && h.dataFresh ? "fresh" : (h && h.snapshotAge !== null ? "stale" : ""));

    // Buttons je nach Zustand freischalten
    const running = ["RUNNING", "PLANNING", "EXECUTING", "WAITING", "DEGRADED"].includes(state);
    document.getElementById("btn-start").disabled = running || state === "STARTING" || state === "PAUSED";
    document.getElementById("btn-pause").disabled = !running;
    document.getElementById("btn-resume").disabled = state !== "PAUSED";
    document.getElementById("btn-step").disabled = state !== "PAUSED";
    document.getElementById("btn-stop").disabled = state === "IDLE";
  }

  // ---------- Live-Feed ----------
  const FEED_LABELS = {
    "agent.state": e => "Agent: " + e.payload.from + " → " + e.payload.to
      + (e.payload.reason ? " (" + e.payload.reason + ")" : ""),
    "model.error": e => "Fehler: " + e.payload.error,
    "model.warning": e => "Warnung: " + e.payload.error,
    "model.version_mismatch": e => "Versionsabweichung: Spiel v" + e.payload.gameVersion
      + " r" + e.payload.buildRevision + " ≠ Referenz v" + e.payload.referenceVersion,
    "state.save_exported": e => "Save exportiert: " + e.payload.path,
    "narrative.chapter": e => e.payload.title + " — " + e.payload.body,
  };

  function feedClass(e) {
    if (e.type === "model.error") return "crit";
    if (e.type === "model.warning" || e.type === "model.version_mismatch") return "warn";
    if (e.type === "narrative.chapter") return "p1";
    return "";
  }

  function addFeedItem(e) {
    const fn = FEED_LABELS[e.type];
    if (!fn) return; // Telemetrie etc. nicht im Feed
    const div = document.createElement("div");
    div.className = "feed-item " + feedClass(e);
    div.innerHTML = '<span class="ts">' + fmtClock(e.ts) + "</span>" + fn(e);
    const box = document.getElementById("feed-items");
    box.prepend(div);
    while (box.children.length > 80) box.removeChild(box.lastChild);
  }

  // ---------- Diagnostics-Tab (Kern, da klein) ----------
  function renderDiagnostics() {
    const h = store.health;
    if (!h) return;
    document.getElementById("diag-content").textContent = JSON.stringify({
      agentState: h.agentState,
      snapshotAge: h.snapshotAge !== null ? h.snapshotAge.toFixed(1) + "s" : null,
      dataFresh: h.dataFresh,
    }, null, 2);
    const errBox = document.getElementById("diag-errors");
    errBox.textContent = (h.errors && h.errors.length) ? h.errors.join("\n") : "keine";
  }

  // ---------- Mission Control (M0: Telemetrie-Ansicht) ----------
  function renderMission() {
    const s = store.status;
    const live = s && s.agentState !== "IDLE";
    document.getElementById("mission-placeholder").classList.toggle("hidden", live);
    document.getElementById("mission-live").classList.toggle("hidden", !live);
    if (!live) return;

    const eco = store.economy;
    const strip = document.getElementById("safety-strip");
    strip.innerHTML = "";
    if (eco && eco.food) {
      strip.appendChild(tile("Food-Sicherheit",
        eco.food.reserveSeconds === null ? "stabil" : fmtDuration(eco.food.reserveSeconds),
        "Worst-Winter " + fmtRate(eco.food.worstWinterNetPerSec) + "/s",
        eco.food.safe ? "ok" : "crit"));
    }
    if (eco && eco.energy) {
      const b = eco.energy.balance;
      strip.appendChild(tile("Energie", fmtRate(b) + " Wt",
        eco.energy.prod.toFixed(1) + " Prod / " + eco.energy.cons.toFixed(1) + " Verbrauch",
        b >= 0 ? "ok" : "warn"));
    }
    if (store.population) {
      const p = store.population;
      strip.appendChild(tile("Bevölkerung", p.kittens + " / " + p.maxKittens,
        "Happiness " + Math.round(p.happiness * 100) + "% · " + p.freeKittens + " frei",
        "ok"));
    }
  }

  function tile(label, val, sub, cls) {
    const div = document.createElement("div");
    div.className = "tile " + (cls || "");
    div.innerHTML = "<label>" + label + "</label><div class='val'>" + val +
      "</div><div class='sub'>" + sub + "</div>";
    return div;
  }

  // ---------- WebSocket ----------
  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(proto + "//" + location.host + "/ws");
    ws.onopen = () => { store.connected = true; };
    ws.onmessage = (msg) => {
      const e = JSON.parse(msg.data);
      if (e.type === "hello") {
        applyStatus(e.payload.status);
        (e.payload.recentEvents || []).forEach(addFeedItem);
      } else if (e.type === "state.snapshot") {
        applyStatus(e.payload);
      } else {
        addFeedItem(e);
        if (e.type === "agent.state") {
          if (store.status) store.status.agentState = e.payload.to;
          renderAll();
        }
        eventHandlers.forEach(fn => fn(e));
      }
    };
    ws.onclose = () => {
      store.connected = false;
      setTimeout(connect, 1500); // automatische Wiederverbindung
    };
  }

  function applyStatus(payload) {
    if (!payload) return;
    store.status = payload.status;
    store.economy = payload.economy;
    store.population = payload.population;
    store.health = payload.health;
    renderAll();
  }

  function renderAll() {
    renderGlobalBar();
    renderMission();
    renderDiagnostics();
    updateHandlers.forEach(fn => fn(store));
  }

  // ---------- Tab-Navigation ----------
  function initTabs() {
    document.querySelectorAll(".tab-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
      });
    });
  }

  // ---------- Init ----------
  document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    document.getElementById("btn-start").onclick = () => control("start");
    document.getElementById("btn-stop").onclick = () => control("stop");
    document.getElementById("btn-pause").onclick = () => control("pause");
    document.getElementById("btn-resume").onclick = () => control("resume");
    document.getElementById("btn-step").onclick = () => control("step_action");
    connect();
  });

  return {
    store,
    onUpdate: fn => updateHandlers.push(fn),
    onEvent: fn => eventHandlers.push(fn),
    fmtNum, fmtRate, fmtDuration, fmtClock,
  };
})();
