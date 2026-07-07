/* Decisions-Tab (Cockpit-Spec Kap. 6): Journal + Decision Inspector mit
   Candidate Matrix, Score-Zerlegung und Why-not-Begründungen. */

(() => {
  const { fmtClock, fmtDuration, escapeHtml } = KGP;
  let openId = null;

  function render(store) {
    const tbody = document.querySelector("#decision-journal tbody");
    if (!tbody) return;
    tbody.innerHTML = "";
    for (const d of store.decisions.slice(0, 60)) {
      const tr = document.createElement("tr");
      tr.className = "clickable" + (openId === d.decisionId ? " selected-row" : "");
      const ex = d.execution || {};
      const outcome = ex.state === "FAILED" ? "✗" : d.observed ? escapeHtml(d.observed) : (ex.state || "");
      tr.innerHTML =
        "<td class='num'>" + d.decisionId + "</td>" +
        "<td class='num muted'>" + fmtClock(d.ts) + "</td>" +
        "<td>" + escapeHtml(d.selected.action.label) + "</td>" +
        "<td class='num'>" + d.selected.score.toFixed(2) + "</td>" +
        "<td class='muted'>" + escapeHtml(d.reason) + "</td>" +
        "<td class='small'>" + outcome + "</td>";
      tr.onclick = () => { openId = (openId === d.decisionId ? null : d.decisionId); render(store); };
      tbody.appendChild(tr);
    }
    renderInspector(store);
  }

  function renderInspector(store) {
    const panel = document.getElementById("decision-inspector");
    const d = store.decisions.find(x => x.decisionId === openId);
    panel.classList.toggle("hidden", !d);
    if (!d) return;
    document.getElementById("di-id").textContent =
      "#" + d.decisionId + " · " + fmtClock(d.ts) + " · Spieljahr " + (d.gameTime || {}).year;

    let html = "";

    // Provenance-Kette (Spec 6.3, kompakt)
    html += "<div class='di-provenance mono small'>";
    html += prov("Trigger", d.trigger +
      (d.replanReason ? " [" + d.replanReason.type + "/" + d.replanReason.source + "]" : ""));
    if (d.stateHash) html += prov("State-Hash", d.stateHash);
    if (d.predictionOk === false && d.observedDelta) {
      html += prov("Prognose", "ABWEICHUNG — beobachtet: " + JSON.stringify(d.observedDelta));
    }
    html += prov("Phase / Run", d.phase + " · " + d.runType);
    html += prov("Ziel", d.objective);
    if (d.bottleneck && d.bottleneck.resource) {
      html += prov("Engpass", d.bottleneck.resource + " (ETA " +
        (d.bottleneck.etaSeconds != null ? fmtDuration(d.bottleneck.etaSeconds) : "∞") + ")");
    }
    html += prov("Entscheidung", d.selected.action.label);
    if (d.observed) html += prov("Beobachtet", d.observed);
    html += "</div>";

    // Candidate Matrix (Spec 6.4)
    html += "<h4>Kandidaten</h4><table class='datatable'><thead><tr>" +
      "<th></th><th>Aktion</th><th class='num'>Score</th><th>Score-Zerlegung</th>" +
      "<th>Warum (nicht)?</th></tr></thead><tbody>";
    for (const c of d.candidates) {
      const cls = c.selected ? "selected-row" : (!c.feasible ? "infeasible-row" : "");
      html += "<tr class='" + cls + "'>" +
        "<td>" + (c.selected ? "✓" : c.feasible ? "" : "🔒") + "</td>" +
        "<td>" + escapeHtml(c.action.label) + "</td>" +
        "<td class='num'>" + c.score.toFixed(2) + "</td>" +
        "<td>" + scoreBar(c.components) + "</td>" +
        "<td class='small muted'>" + escapeHtml(c.rejectReason ||
          (c.selected ? "gewählt (höchster Score)" : "Score niedriger als Gewinner")) + "</td>" +
        "</tr>";
    }
    html += "</tbody></table>";
    document.getElementById("di-content").innerHTML = html;
  }

  function prov(label, value) {
    return "<div><span class='prov-label'>" + label + "</span> " + escapeHtml(value) + "</div>";
  }

  // Score-Komponenten als Mini-Balken (positive rechts, negative links)
  function scoreBar(components) {
    const entries = Object.entries(components || {});
    if (!entries.length) return "";
    return entries.map(([k, v]) =>
      "<span class='score-chip " + (v < 0 ? "neg-chip" : "") + "' title='" + k + "'>" +
      k + " " + (v >= 0 ? "+" : "") + v.toFixed(2) + "</span>").join(" ");
  }

  KGP.onUpdate(render);
})();
