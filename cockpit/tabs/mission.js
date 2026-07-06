/* Mission Control (Cockpit-Spec Kap. 5): Current-Action-Hero-Card,
   Missionskette (Kausalität), Meilenstein-Strip, Safety-Strip, Engpass. */

(() => {
  const { fmtRate, fmtDuration, tile, escapeHtml } = KGP;

  const TYPE_LABELS = {
    BUY_BUILDING: "BAUEN", RESEARCH: "FORSCHEN", BUY_UPGRADE: "UPGRADE",
    CRAFT: "CRAFTEN", HUNT: "JAGEN", ASSIGN_JOB: "JOBS", GATHER: "SAMMELN",
    REFINE: "VEREDELN", WAIT: "WARTEN", SAFETY: "SAFETY",
  };
  const EXEC_LABELS = {
    COMPLETED: "✓ ausgeführt", FAILED: "✗ fehlgeschlagen", WAITING: "…wartet",
  };

  function render(store) {
    const s = store.status;
    const live = s && s.agentState !== "IDLE";
    document.getElementById("mission-placeholder").classList.toggle("hidden", live);
    document.getElementById("mission-live").classList.toggle("hidden", !live);
    if (!live) return;

    renderHero(store);
    renderChain(store);
    renderSafety(store);
    renderMilestones(store);
    renderBottleneck(store);
  }

  function renderHero(store) {
    const d = store.currentDecision;
    if (!d) return;
    const a = d.selected.action;
    document.getElementById("hero-type").textContent = TYPE_LABELS[a.type] || a.type;
    document.getElementById("hero-action").textContent =
      a.type === "WAIT" ? "Warten — " + (d.bottleneck && d.bottleneck.resource
        ? "auf " + d.bottleneck.resource : "beobachten") : a.label;
    document.getElementById("hero-reason").textContent = d.reason;
    const ex = d.execution || {};
    const execEl = document.getElementById("hero-exec");
    execEl.textContent = EXEC_LABELS[ex.state] || "";
    execEl.className = "hero-exec " + (ex.state === "FAILED" ? "crit-text" : "");
    document.getElementById("hero-meta").innerHTML =
      '<span class="muted small">Trigger: ' + escapeHtml(d.trigger) +
      (d.observed ? ' · Beobachtet: <strong>' + escapeHtml(d.observed) + "</strong>" : "") +
      (ex.method === "js-fallback" ? ' · <span class="warn-text">JS-Fallback</span>' : "") +
      "</span>";
  }

  function renderChain(store) {
    const d = store.currentDecision;
    const plan = store.plan;
    if (!d) return;
    const steps = [
      { label: d.selected.action.label, cls: "now" },
      { label: "Meilenstein: " + d.objective, cls: "" },
      { label: "Run: " + (plan ? plan.runType : d.runType) + " · Phase " + d.phase, cls: "" },
      { label: "North Star: minimale Realzeit bis zur Progressionsfront", cls: "muted" },
    ];
    document.getElementById("causal-chain").innerHTML = steps.map((s, i) =>
      '<div class="chain-step ' + s.cls + '">' + (i > 0 ? '<span class="chain-arrow">↓</span>' : "") +
      escapeHtml(s.label) + "</div>").join("");
  }

  function renderSafety(store) {
    const eco = store.economy;
    const strip = document.getElementById("safety-strip");
    strip.innerHTML = "";
    if (eco && eco.food) {
      strip.appendChild(tile("Food (Worst-Winter)",
        eco.food.reserveSeconds === null || eco.food.reserveSeconds === undefined
          ? "stabil" : fmtDuration(eco.food.reserveSeconds),
        fmtRate(eco.food.worstWinterNetPerSec) + "/s im Winter",
        eco.food.safe ? "ok" : "crit"));
    }
    if (eco && eco.energy && (eco.energy.prod || eco.energy.cons)) {
      strip.appendChild(tile("Energie", fmtRate(eco.energy.balance) + " Wt",
        eco.energy.prod.toFixed(1) + " / " + eco.energy.cons.toFixed(1),
        eco.energy.balance >= 0 ? "ok" : "warn"));
    }
    if (store.population) {
      const p = store.population;
      strip.appendChild(tile("Kitten", p.kittens + " / " + p.maxKittens,
        "Happiness " + Math.round(p.happiness * 100) + "% · " + p.freeKittens + " frei",
        p.freeKittens > 0 ? "warn" : "ok"));
    }
  }

  function renderMilestones(store) {
    const plan = store.plan;
    const box = document.getElementById("milestone-strip");
    if (!plan || !plan.milestones) { box.innerHTML = "<span class='muted'>–</span>"; return; }
    // Fensterausschnitt: letzter fertiger, aktiver, nächste drei (Spec 5.5)
    const ms = plan.milestones;
    const activeIdx = ms.findIndex(m => m.state === "active");
    const start = Math.max(0, (activeIdx === -1 ? ms.length : activeIdx) - 1);
    const window = ms.slice(start, start + 5);
    box.innerHTML = window.map(m => {
      const icon = m.state === "done" ? "✓" : m.state === "active" ? "▶" : "○";
      return '<div class="ms-row ms-' + m.state + '"><span class="ms-icon">' + icon +
        "</span>" + escapeHtml(m.label) + "</div>";
    }).join("");
  }

  function renderBottleneck(store) {
    const bn = (store.plan || {}).bottleneck;
    const box = document.getElementById("bottleneck-box");
    if (!bn || !bn.resource) {
      box.innerHTML = "<span class='muted'>kein Engpass — Ziel " +
        ((bn && bn.affordable) ? "ist bezahlbar" : "wird geprüft") + "</span>";
      return;
    }
    const missing = (bn.missing || []).map(m =>
      "<strong>" + Math.ceil(m.missing) + "</strong> " + escapeHtml(m.name)).join(", ");
    box.innerHTML =
      '<div class="bn-res">' + escapeHtml(bn.resource) + "</div>" +
      "<div>fehlen " + missing + "</div>" +
      '<div class="muted small">ETA ' +
      (bn.etaSeconds === null || bn.etaSeconds === undefined ? "∞ (Produktion nötig)"
        : fmtDuration(bn.etaSeconds)) + "</div>" +
      (bn.capBlocked ? '<div class="warn-text small">Cap von ' + escapeHtml(bn.capBlocked) +
        " blockiert — Storage nötig</div>" : "");
  }

  KGP.onUpdate(render);
})();
