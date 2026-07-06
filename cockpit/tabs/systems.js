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
