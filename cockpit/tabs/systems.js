/* Systems-Tab: Reset & Run Economics (Cockpit-Spec Kap. 14, M3-Ausbaustufe)
   plus Metaphysics-Status. Weitere System-Panels folgen mit M4–M6. */

(() => {
  const { tile, escapeHtml, fmtNum } = KGP;

  function render(store) {
    const plan = store.plan;
    const box = document.getElementById("run-economics");
    if (!box) return;
    box.innerHTML = "";
    const s = store.status;
    const rst = plan && plan.reset;

    if (s) {
      box.appendChild(tile("Run", (plan ? plan.runType : "–"),
        "Phase " + (plan ? plan.phase : "–"), "ok"));
      box.appendChild(tile("Paragon", fmtNum(s.paragon, 0),
        "aktuell verfügbar", "ok"));
    }
    if (rst) {
      box.appendChild(tile("Reset-Projektion", "+" + rst.projection + " Paragon",
        escapeHtml(rst.reason || ""),
        rst.recommended ? "warn" : "ok"));
      if (rst.nextPerk) {
        box.appendChild(tile("Nächstes Meta-Ziel", escapeHtml(rst.nextPerk),
          "wird durch Reset finanziert", "ok"));
      }
    }

    // Gates-Checkliste (Spec 14.3)
    const gatesBox = document.getElementById("reset-gates");
    gatesBox.innerHTML = (rst && rst.gates ? rst.gates : []).map(g =>
      '<div class="ms-row ' + (g.pass ? "ms-done" : "ms-pending") + '">' +
      '<span class="ms-icon">' + (g.pass ? "✓" : "○") + "</span>" +
      escapeHtml(g.name) + ' <span class="muted small">— ' + escapeHtml(g.detail) + "</span></div>"
    ).join("") || "<span class='muted'>–</span>";

    // Space-Panel (M4)
    const sys = store.systems;
    const spaceBox = document.getElementById("space-box");
    if (spaceBox && sys && sys.space) {
      const programs = sys.space.programs || [];
      const done = programs.filter(p => p.val > 0).map(p => escapeHtml(p.label));
      const planets = (sys.space.planets || []).map(pl =>
        "<strong>" + escapeHtml(pl.label) + "</strong>: " +
        (pl.buildings.map(b => escapeHtml(b.label) + " ×" + b.val).join(", ") || "–")
      );
      const energy = sys.energy || {};
      spaceBox.innerHTML = programs.length === 0
        ? "<span class='muted'>Noch kein Zugang zum Weltraum (Rocketry fehlt).</span>"
        : "Missionen: " + (done.join(" · ") || "<span class='muted'>keine abgeschlossen</span>") +
          "<br>" + (planets.join("<br>") || "") +
          "<br><span class='muted small'>Energie-Saldo: " +
          (energy.balance !== undefined ? energy.balance.toFixed(1) + " Wt" : "–") + "</span>";
    }

    // Metaphysics-Reihenfolge
    const metaBox = document.getElementById("metaphysics-box");
    const perk = plan && plan.nextPerk;
    if (perk) {
      const price = (perk.prices || []).map(p => p.val + " " + p.name).join(", ");
      metaBox.innerHTML = "Feste Kaufreihenfolge (Spec 9.1): Engineering → Diplomacy → " +
        "Golden Ratio → Divine Proportion → Vitruvian Feline → Renaissance" +
        "<br>Nächstes Ziel: <strong>" + escapeHtml(perk.label) + "</strong> (" + escapeHtml(price) + ")";
    } else if (plan) {
      metaBox.textContent = "Price-Ratio-Kette vollständig — nächste Meta-Ziele folgen mit M4+.";
    }
  }

  KGP.onUpdate(render);
})();
