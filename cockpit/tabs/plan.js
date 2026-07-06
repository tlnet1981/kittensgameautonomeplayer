/* Plan-Tab (Cockpit-Spec Kap. 7): Zielhierarchie + Meilenstein-Roadmap. */

(() => {
  const { escapeHtml, fmtDuration } = KGP;

  function render(store) {
    const plan = store.plan;
    const hier = document.getElementById("plan-hierarchy");
    const list = document.getElementById("plan-milestones");
    if (!plan) {
      hier.innerHTML = "<span class='muted'>Agent noch nicht gestartet.</span>";
      list.innerHTML = "";
      return;
    }

    // Zielhierarchie (Spec 7.2)
    const bn = plan.bottleneck;
    const rows = [
      ["North Star", "Minimale Realzeit bis zur vollständigen Progressionsfront"],
      ["Phase", plan.phase + " — Erstwirtschaft aufbauen"],
      ["Run", plan.runType],
      ["Meilenstein", plan.objective],
    ];
    if (bn && bn.resource) {
      rows.push(["Task", "Beschaffe " + (bn.missing || []).map(m =>
        Math.ceil(m.missing) + " " + m.name).join(", ") +
        " (ETA " + (bn.etaSeconds != null ? fmtDuration(bn.etaSeconds) : "∞") + ")"]);
    }
    hier.innerHTML = rows.map(([k, v], i) =>
      '<div class="chain-step' + (i === rows.length - 1 ? " now" : "") + '">' +
      (i > 0 ? '<span class="chain-arrow">↓</span>' : "") +
      "<span class='prov-label'>" + k + "</span> " + escapeHtml(v) + "</div>").join("");

    // Roadmap
    list.innerHTML = (plan.milestones || []).map(m => {
      const icon = m.state === "done" ? "✓" : m.state === "active" ? "▶" : "○";
      return '<div class="ms-row ms-' + m.state + '"><span class="ms-icon">' + icon +
        "</span>" + escapeHtml(m.label) + "</div>";
    }).join("");
  }

  KGP.onUpdate(render);
})();
