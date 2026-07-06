"""Entscheidungslogik des autonomen Spielers.

Module (siehe docs/brain.md):
- records.py  DecisionRecord: vollständige, erklärbare Entscheidungsakte
- actions.py  Aktionsklassen mit Ausführungsbeschreibung für den Actor
- safety.py   Sicherheitsinvarianten (Food zuerst) — Vorrang vor Nutzen
- meta.py     Meta-Controller: Phase, Run-Typ, Meilenstein-Graph
- tactics.py  Kandidaten-Generierung + transparentes NetValue-Scoring
- loop.py     Steuerzyklus: read → safety → goal → score → execute → observe
"""
