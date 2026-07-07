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

    renderFocus(store);
    renderHero(store);
    renderChain(store);
    renderSafety(store);
    renderMilestones(store);
    renderBottleneck(store);
  }

  // ================== Fokus-Panel (Gewichtung · Sparziel · Warum jetzt?) ==================
  // Datenquelle: decision.committed / status.currentDecision (DecisionRecord.to_dict)
  // + plan.updated (MetaView). Rendert deterministisch: nur bei neuer decisionId.

  // Reine Sekundenwert-Anzeigen der Score-Zerlegung (Spiegel von
  // SHADOW_INFO_KEYS in player/brain/tactics.py) — Darstellung mit „s"-Suffix,
  // sie zählen nicht additiv zum Score:
  const SECONDS_KEYS = new Set(["costTime", "benefitTime", "netValue", "optionValue",
    "jobScore", "csValue", "tradeValue", "huntValue", "praiseValue",
    "storageB", "storageC", "leaderValue", "policyValue", "tapValue", "pactValue",
    "rrValue", "furnaceValue", "shatterValue", "voidValue", "tfValue",
    "potential", "savingFor"]);
  // Sparhorizont wie brain/tactics.py SAVING_HORIZON_S:
  const SAVING_HORIZON_S = 180;

  let focusRenderedId = null;

  function renderFocus(store) {
    const d = store.currentDecision;
    const panel = document.getElementById("focus-panel");
    if (!panel) return;
    if (!d || !d.selected) { panel.classList.add("hidden"); return; }
    panel.classList.remove("hidden");
    if (d.decisionId === focusRenderedId) return;   // kein Flackern
    focusRenderedId = d.decisionId;

    panel.innerHTML =
      "<h3>Fokus <span class='muted small'>Gewichtung · Sparziel · Warum jetzt?</span></h3>" +
      focusHead(d, store.plan) + focusSaving(d) + focusBars(d) + focusWhy(d);
    // Tap/Klick klappt die Komponenten-Zerlegung eines Balkens fest auf:
    panel.querySelectorAll(".fb-row").forEach(row => {
      row.onclick = () => row.classList.toggle("open");
    });
  }

  // 1. Kopfzeile: Run-Typ · Phase · aktives Ziel + Engpass-Fortschritt mit ETA.
  function focusHead(d, plan) {
    const variant = plan && plan.runVariant ? " (" + plan.runVariant + ")" : "";
    let html = "<div class='focus-context'>" +
      escapeHtml((d.runType || "?") + variant + " · " + (d.phase || "?") + " · " +
        (d.objective || "?")) + "</div>";
    const bn = d.bottleneck;
    if (bn && bn.resource) {
      // missing-Einträge: {name, missing, need} (state/access.py missing_for)
      const m = (bn.missing || []).find(x => x.name === bn.resource) || (bn.missing || [])[0];
      let pct = 0, detail = "";
      if (m && m.need > 0) {
        pct = Math.max(0, Math.min(100, (m.need - m.missing) / m.need * 100));
        detail = Math.floor(m.need - m.missing) + " / " + Math.ceil(m.need) + " " + m.name;
      }
      html += "<div class='focus-bn'>" +
        "<span class='small'>Engpass <strong class='warn-text'>" + escapeHtml(bn.resource) +
        "</strong></span>" +
        "<div class='fillbar focus-bn-bar'><div style='width:" + pct.toFixed(1) + "%'></div></div>" +
        "<span class='small muted'>" + escapeHtml(detail) + (detail ? " · " : "") + "ETA " +
        (bn.etaSeconds === null || bn.etaSeconds === undefined
          ? "∞ (Produktion nötig)" : "~" + fmtDuration(bn.etaSeconds)) + "</span></div>";
    } else if (bn && bn.affordable) {
      html += "<div class='focus-bn small muted'>kein Engpass — Ziel ist bezahlbar</div>";
    }
    return html;
  }

  // Sparziel wie brain/tactics.py _apply_saving_rule: unbezahlbarer Kandidat
  // mit potential > 0 (bzw. unbezahlbares Meilensteinziel) und endlicher ETA
  // innerhalb des Sparhorizonts; bester zuerst (potential, dann ETA, dann id).
  function savingTarget(d) {
    const targets = [];
    for (const c of d.candidates || []) {
      if (c.feasible || c.etaSeconds === null || c.etaSeconds === undefined
          || !isFinite(c.etaSeconds)) continue;
      const comp = c.components || {};
      let pot = comp.potential || 0;
      if (pot <= 0 && comp.milestone) pot = 3.0;   // Meilensteinziel ist immer Sparziel
      if (pot > 0 && c.etaSeconds <= SAVING_HORIZON_S) targets.push([pot, c]);
    }
    if (!targets.length) return null;
    targets.sort((a, b) => (b[0] - a[0]) || (a[1].etaSeconds - b[1].etaSeconds) ||
      (a[1].action.id < b[1].action.id ? -1 : 1));
    return targets[0][1];
  }

  // 2. Sparziel-Karte: worauf gespart wird + welche Käufe dafür zurückstehen.
  function focusSaving(d) {
    const target = savingTarget(d);
    const held = (d.candidates || [])
      .filter(c => ((c.components || {}).delayPenalty || 0) < 0);
    if (!target && !held.length) return "";
    let html = "<div class='focus-saving'>";
    html += "<div class='fs-target'>💰 Spart auf: <strong>" +
      escapeHtml(target ? target.action.label : "(Sparlogik aktiv)") + "</strong>" +
      (target ? " — noch ~" + fmtDuration(target.etaSeconds) : "") + "</div>";
    if (held.length) {
      html += "<div class='small muted'>Dafür zurückgehalten: " + held.map(c =>
        escapeHtml(c.action.label) + " (" + c.components.delayPenalty.toFixed(2) + ")")
        .join(" · ") + "</div>";
    }
    return html + "</div>";
  }

  // 3. Gewichtungs-Balken: Top-6-Kandidaten, Score-normiert; Gewinner cyan,
  // unmachbare grau-gestreift; negative additive Komponenten als roter Anteil.
  function focusBars(d) {
    const top = (d.candidates || []).slice(0, 6);
    if (!top.length) return "";
    let scale = 1e-4;
    const rows = top.map(c => {
      let neg = 0;
      for (const [k, v] of Object.entries(c.components || {})) {
        if (v < 0 && !SECONDS_KEYS.has(k)) neg += -v;   // delayPenalty, foodRisk, opportunity …
      }
      const pos = Math.max(c.score, 0);
      scale = Math.max(scale, pos + neg);
      return { c, pos, neg };
    });
    let html = "<div class='focus-bars'>";
    for (const r of rows) {
      const c = r.c;
      const cls = "fb-row" + (c.selected ? " winner" : "") + (c.feasible ? "" : " infeasible");
      const posW = r.pos / scale * 100, negW = r.neg / scale * 100;
      html += "<div class='" + cls + "'>" +
        "<div class='fb-line'><span class='fb-label'>" +
        (c.selected ? "✓ " : c.feasible ? "" : "🔒 ") + escapeHtml(c.action.label) +
        "</span><span class='fb-score mono'>" + c.score.toFixed(2) + "</span></div>" +
        "<div class='fb-bar'><div class='fb-pos' style='width:" + posW.toFixed(1) + "%'></div>" +
        (negW > 0.5 ? "<div class='fb-neg' style='width:" + negW.toFixed(1) +
          "%' title='negative Komponenten (Abzug " + r.neg.toFixed(2) + ")'></div>" : "") +
        "</div>" +
        (!c.feasible && c.rejectReason ? "<div class='fb-reject small muted'>" +
          escapeHtml(shortText(c.rejectReason, 80)) + "</div>" : "") +
        "<div class='fb-chips'>" + componentChips(c.components) + "</div>" +
        "</div>";
    }
    return html + "</div>";
  }

  function shortText(s, n) { return s.length > n ? s.slice(0, n - 1) + "…" : s; }

  // Komponenten-Chips wie im Decision Inspector; Sekundenwerte mit „s"-Suffix.
  function componentChips(components) {
    const entries = Object.entries(components || {});
    if (!entries.length) return "<span class='muted small'>keine Zerlegung</span>";
    return entries.map(([k, v]) => {
      const val = SECONDS_KEYS.has(k)
        ? (v >= 0 ? "+" : "-") + (Math.abs(v) >= 100 ? Math.abs(v).toFixed(0)
          : Math.abs(v).toFixed(1)) + "s"
        : (v >= 0 ? "+" : "") + v.toFixed(2);
      return "<span class='score-chip " + (v < 0 ? "neg-chip" : "") + "' title='" +
        escapeHtml(k) + "'>" + escapeHtml(k) + " " + val + "</span>";
    }).join(" ");
  }

  // 4. „Warum jetzt?": reason-Satz + replanReason-Quelle als Badge.
  function focusWhy(d) {
    let html = "<div class='focus-why'><span class='fw-label'>Warum jetzt?</span>" +
      escapeHtml(d.reason || "–");
    const rr = d.replanReason;
    if (rr && rr.source) {
      html += " <span class='replan-badge" + (rr.type === "hard" ? " hard" : "") +
        "' title='" + escapeHtml(rr.detail || "") + "'>" +
        escapeHtml(rr.source) + "</span>";
    }
    return html + "</div>";
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
      const f = eco.food;
      const cls = f.status === "critical" ? "crit" : f.status === "warn" ? "warn" : "ok";
      strip.appendChild(tile("Food (Winter-Projektion)",
        f.projectedMin === undefined ? "–" :
          "min. " + Math.round(f.projectedMin) + " Catnip",
        "Tiefpunkt in " + fmtDuration(f.projectedMinInSeconds) +
        " · Winter " + fmtRate(f.worstWinterNetPerSec) + "/s",
        cls));
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
