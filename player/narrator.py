"""Deterministische Narrationsschicht (Cockpit-Spec Kap. 18).

Erzeugt Erzähl-Karten ausschließlich aus echten Ereignissen und festen
Templates — kein LLM, keine freie Textgenerierung (Spec 18.1). Prioritäten:

    P1  Wendepunkt (Kapitelkarte): Phasenwechsel, Reset, Session-Start
    P2  Meilenstein: Forschung, Meilenstein-Abschluss, Erstereignisse
    P3  Taktisch: Engpasswechsel
    P4  Routine: bleibt stumm (Aggregation übernimmt der Feed)

Der Narrator ist zustandsbehaftet (er kennt „Firsts"), aber rein ableitend:
identische Ereignisfolgen erzeugen identische Karten.
"""

from __future__ import annotations

from player.events import EventBus

# Template-Karten für Erstereignisse: Aktionstyp -> (Titel, Warum es zählt)
FIRST_TIME_CARDS = {
    "HUNT": ("Erste Jagd!",
             "Catpower wird ab jetzt in Felle und Elfenbein umgemünzt — Happiness und Handwerk profitieren."),
    "TRADE": ("Erster Handel!",
              "Die Karawane steht: Ressourcen lassen sich ab jetzt gegen Gold und Catpower eintauschen."),
    "PRAISE": ("Erstes Sonnengebet!",
               "Faith wird zu dauerhaftem Worship — der Grundstein der Religionsökonomie."),
    "FESTIVAL": ("Erstes Festival!",
                 "+30 % Happiness für ein ganzes Jahr und doppelte Kitten-Ankunft."),
    "CRAFT": ("Erstes Handwerk!",
              "Rohstoffe werden ab jetzt zu wertvollen Materialien veredelt."),
}


class Narrator:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._seen_action_types: set[str] = set()
        self._last_bottleneck: str | None = None

    # ------------------------------------------------------------ Hooks

    def on_action_executed(self, action_type: str, label: str, ok: bool) -> None:
        """Erstereignisse als P2-Karte feiern (einmal pro Aktionstyp)."""
        if not ok or action_type in self._seen_action_types:
            return
        self._seen_action_types.add(action_type)
        card = FIRST_TIME_CARDS.get(action_type)
        if card:
            title, why = card
            self.bus.publish("narrative.milestone", {
                "priority": "P2", "title": title, "body": why,
            })

    def on_research(self, tech_label: str, next_objective: str) -> None:
        self.bus.publish("narrative.milestone", {
            "priority": "P2",
            "title": f"Erforscht: {tech_label}",
            "body": f"Nächstes Ziel: {next_objective}",
        })

    def on_bottleneck_change(self, old: str | None, new: str | None,
                             objective: str) -> None:
        """Engpasswechsel = taktische Story (Spec 18.2, P3)."""
        if new is None or new == old or old is None:
            self._last_bottleneck = new
            return
        self._last_bottleneck = new
        self.bus.publish("narrative.tactical", {
            "priority": "P3",
            "title": f"Engpasswechsel: {old} → {new}",
            "body": f"Für „{objective}“ zählt jetzt {new}.",
        })

    def track_bottleneck(self, resource: str | None, objective: str) -> None:
        if resource != self._last_bottleneck:
            self.on_bottleneck_change(self._last_bottleneck, resource, objective)
