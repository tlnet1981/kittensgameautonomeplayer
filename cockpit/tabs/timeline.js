/* Timeline-Tab (Cockpit-Spec Kap. 17, vereinfacht): chronologische Event-Liste
   aus dem Session-Log (/api/timeline) plus Live-Events, filterbar nach Klasse.
   Aufeinanderfolgende gleichartige Entscheidungen werden gruppiert (17.2). */

(() => {
  const { fmtClock, escapeHtml } = KGP;
  let items = [];        // {ts, type, text, cls}
  let filter = "";
  let historyLoaded = false;

  const RENDERERS = {
    "decision.committed": e => ({
      cls: "decision",
      text: e.payload.selected.action.label +
        (e.payload.trigger && e.payload.trigger.startsWith("SAFETY") ? " ⚠" : ""),
      group: e.payload.selected.action.id,
    }),
    "narrative.milestone": e => ({ cls: "narrative", text: "★ " + e.payload.title + " — " + e.payload.body }),
    "narrative.chapter": e => ({ cls: "narrative", text: "📖 " + e.payload.title + " — " + e.payload.body }),
    "narrative.tactical": e => ({ cls: "narrative", text: e.payload.title }),
    "agent.state": e => (["PAUSED", "ERROR", "DEGRADED", "IDLE", "STARTING"].includes(e.payload.to)
      ? { cls: "model", text: "Agent: " + e.payload.from + " → " + e.payload.to } : null),
    "model.error": e => ({ cls: "model", text: "Fehler: " + e.payload.error }),
    "model.warning": e => ({ cls: "model", text: "Warnung: " + e.payload.error }),
    "model.version_mismatch": e => ({ cls: "model", text: "Versionsabweichung erkannt" }),
    "frontier.reached": e => ({ cls: "safety", text: "⚠ Ausbaugrenze: " + e.payload.title }),
    "state.save_exported": e => ({ cls: "model", text: "Save-Backup exportiert" }),
  };

  function ingest(e) {
    const fn = RENDERERS[e.type];
    if (!fn) return;
    const r = fn(e);
    if (!r) return;
    if (e.type === "decision.committed" && e.payload.trigger &&
        e.payload.trigger.startsWith("SAFETY")) r.cls = "safety";
    // Gruppierung: gleiche Aktion direkt hintereinander → Zähler hochziehen
    const last = items[0];
    if (r.group && last && last.group === r.group) {
      last.count += 1;
      last.ts = e.ts;
      return;
    }
    items.unshift({ ts: e.ts, type: e.type, text: r.text, cls: r.cls, group: r.group, count: 1 });
    if (items.length > 500) items.pop();
  }

  async function loadHistory() {
    historyLoaded = true;
    try {
      const res = await fetch("/api/timeline?limit=1000");
      const data = await res.json();
      for (const e of data.events || []) ingest(e);
      render(KGP.store);
    } catch (err) { /* Session evtl. noch ohne Log */ }
  }

  function render() {
    const box = document.getElementById("tl-items");
    if (!box) return;
    const visible = items.filter(it => !filter || it.cls === filter).slice(0, 200);
    box.innerHTML = visible.map(it =>
      '<div class="tl-item tl-' + it.cls + '"><span class="ts">' + fmtClock(it.ts) + "</span>" +
      escapeHtml(it.text) + (it.count > 1 ? ' <span class="tl-count">×' + it.count + "</span>" : "") +
      "</div>").join("") || "<div class='muted'>noch keine Ereignisse</div>";
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".tl-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        document.querySelectorAll(".tl-chip").forEach(c => c.classList.remove("active"));
        chip.classList.add("active");
        filter = chip.dataset.filter;
        render();
      });
    });
    // Historie laden, sobald der Tab erstmals geöffnet wird:
    document.querySelector('[data-tab="timeline"]').addEventListener("click", () => {
      if (!historyLoaded) loadHistory();
    });
  });

  KGP.onEvent(e => { ingest(e); render(); });

  KGP.onUpdate(() => {});   // Timeline hängt nur an Events
})();
