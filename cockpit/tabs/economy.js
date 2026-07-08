/* Economy-Tab: Ressourcen-Matrix (Cockpit-Spec Kap. 8).
   Zeigt Bestand/Cap, Füllgrad, Nettofluss, Zeit bis Cap/Leerstand und
   die λ-Topliste der Pfad-Schattenpreise (#34, plan.lambdaTop). */

(() => {
  const { fmtNum, fmtRate, fmtDuration } = KGP;

  function render(store) {
    const eco = store.economy;
    if (!eco) return;

    // --- Safety-Kacheln oben ---
    const strip = document.getElementById("eco-safety");
    strip.innerHTML = "";
    if (eco.food) {
      const f = eco.food;
      const cls = f.status === "critical" ? "crit" : f.status === "warn" ? "warn" : "ok";
      strip.appendChild(mkTile("Catnip-Projektion (bis Winterende)",
        f.projectedMin === undefined ? "–" : "min. " + Math.round(f.projectedMin),
        "aktuell " + fmtRate(f.netNowPerSec) + "/s · Bedarf " +
        fmtRate(-(f.demandPerSec || 0)) + "/s",
        cls));
    }
    if (eco.energy && (eco.energy.prod || eco.energy.cons)) {
      strip.appendChild(mkTile("Energie", fmtRate(eco.energy.balance) + " Wt",
        eco.energy.prod.toFixed(1) + " / " + eco.energy.cons.toFixed(1),
        eco.energy.balance >= 0 ? "ok" : "warn"));
    }

    // --- Ressourcen-Tabelle ---
    const tbody = document.querySelector("#eco-table tbody");
    tbody.innerHTML = "";
    for (const r of eco.resources) {
      const tr = document.createElement("tr");
      const hasCap = r.maxValue > 0;
      const pct = r.pctFull !== null && r.pctFull !== undefined ? Math.min(1, r.pctFull) : null;
      const limit = r.perSec > 0 && hasCap ? r.fillTime
                  : r.perSec < 0 ? r.depletionTime : null;
      const limitLabel = r.perSec > 0 && hasCap && r.fillTime !== null ? fmtDuration(r.fillTime) + " bis Cap"
                       : r.perSec < 0 && r.depletionTime !== null ? fmtDuration(r.depletionTime) + " bis leer"
                       : "–";
      tr.innerHTML =
        "<td>" + r.title + (r.craftable ? ' <span class="muted small">craft</span>' : "") + "</td>" +
        '<td class="num">' + fmtNum(r.value) + "</td>" +
        '<td class="num muted">' + (hasCap ? fmtNum(r.maxValue) : "∞") + "</td>" +
        '<td class="bar-col">' + (pct !== null
            ? '<div class="fillbar' + (pct > 0.9 ? " high" : "") + '"><div style="width:' + (pct * 100).toFixed(0) + '%"></div></div>'
            : "") + "</td>" +
        '<td class="num ' + (r.perSec > 0 ? "pos" : r.perSec < 0 ? "neg" : "muted") + '">' + fmtRate(r.perSec) + "</td>" +
        '<td class="num muted">' + limitLabel + "</td>";
      tbody.appendChild(tr);
    }

    // --- Bevölkerung / Jobs ---
    const pop = store.population;
    if (pop) {
      const jobs = (pop.jobs || []).map(j => j.title + " " + j.value).join(" · ") || "keine Jobs";
      document.getElementById("eco-population").innerHTML =
        "<strong>" + pop.kittens + "</strong> / " + pop.maxKittens + " Kitten (" +
        pop.freeKittens + " frei) · Happiness <strong>" + Math.round(pop.happiness * 100) + "%</strong>" +
        "<br><span class='muted'>" + jobs + "</span>" +
        (pop.leader ? "<br><span class='muted'>Leader: " + pop.leader.name + "</span>" : "");
    }

    // --- λ-Topliste (#34): Pfad-Schattenpreise aus dem Plan-Payload ---
    const lambdaBox = document.getElementById("eco-lambda");
    if (lambdaBox) {
      const rows = (store.plan && store.plan.lambdaTop) || [];
      if (!rows.length) {
        lambdaBox.textContent = "–";
      } else {
        lambdaBox.innerHTML = rows.map(r =>
          '<span class="score-chip" title="λ: Zielsekunden je Einheit · λ̇: je Einheit/s">' +
          "<strong>" + r.name + "</strong> λ " + fmtNum(r.lam) +
          "s · λ̇ " + fmtNum(r.lamRate) + "s</span>"
        ).join(" ");
      }
    }
  }

  function mkTile(label, val, sub, cls) {
    const div = document.createElement("div");
    div.className = "tile " + cls;
    div.innerHTML = "<label>" + label + "</label><div class='val'>" + val +
      "</div><div class='sub'>" + sub + "</div>";
    return div;
  }

  KGP.onUpdate(render);
})();
