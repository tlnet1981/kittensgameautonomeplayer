// State-Reader: liest den kompletten relevanten Spielzustand in EINEM
// page.evaluate()-Aufruf (atomar genug für unsere Zwecke).
//
// Verifizierte API-Zugriffe (Kittens Game 1.5.0.2 r3) sind in
// docs/game-api.md dokumentiert. Jede Sektion ist defensiv gekapselt:
// ein Fehler in einer Sektion füllt `errors`, killt aber nicht den Rest.
() => {
    const g = window.game || window.gamePage;
    if (!g || !g.resPool || !g.bld || !g.calendar) {
        return { ready: false };
    }
    const out = { ready: true, errors: [] };
    const TPS = g.ticksPerSecond || 5; // Ticks pro Sekunde (Raten -> pro Sekunde)

    const section = (name, fn) => {
        try { fn(); } catch (e) { out.errors.push(name + ": " + (e && e.message)); }
    };

    section("meta", () => {
        out.meta = {
            version: (g.telemetry && g.telemetry.version) || null,
            buildRevision: (g.telemetry && g.telemetry.buildRevision) || null,
            paused: !!g.isPaused,
            ticksPerSecond: TPS,
        };
    });

    section("calendar", () => {
        const c = g.calendar;
        out.calendar = {
            year: c.year,
            season: c.season,                    // 0=Frühling .. 3=Winter
            seasonName: c.getCurSeason().name,   // "spring" | "summer" | "autumn" | "winter"
            day: Math.floor(c.day),
            daysPerSeason: c.daysPerSeason,
            weather: c.weather || "normal",
            cycle: c.cycle,
            cycleYear: c.cycleYear,
            festivalDays: c.festivalDays,
            // Winter-Catnip-Modifikator für Worst-Case-Food-Rechnung:
            winterCatnipModifier: (c.seasons && c.seasons[3] && c.seasons[3].modifiers)
                ? c.seasons[3].modifiers.catnip : 0.25,
            currentCatnipModifier: (c.getCurSeason().modifiers || {}).catnip || 1,
        };
    });

    section("resources", () => {
        out.resources = [];
        for (const r of g.resPool.resources) {
            if (!r.unlocked && !(r.value > 0)) { continue; }
            out.resources.push({
                name: r.name,
                title: r.title || r.name,
                value: r.value,
                maxValue: r.maxValue || 0,   // 0 = kein Cap
                craftable: !!r.craftable,
                unlocked: !!r.unlocked,
                // Netto-Rate inkl. Konsum & Konversionen, pro Sekunde:
                perSec: g.getResourcePerTick(r.name, true) * TPS,
            });
        }
    });

    section("village", () => {
        const v = g.village;
        const jobs = [];
        for (const j of v.jobs) {
            if (!j.unlocked) { continue; }
            jobs.push({ name: j.name, title: j.title, value: j.value });
        }
        let leader = null;
        if (v.leader) {
            leader = {
                name: (v.leader.name || "") + " " + (v.leader.surname || ""),
                trait: v.leader.trait ? v.leader.trait.name : null,
                job: v.leader.job || null,
            };
        }
        out.village = {
            kittens: v.getKittens(),
            maxKittens: v.maxKittens,
            freeKittens: v.getFreeKittens(),
            happiness: v.happiness,          // 1.0 = 100 %
            jobs: jobs,
            leader: leader,
            // Catnip-Verbrauch der Population pro Sekunde (positiv = Verbrauch):
            catnipDemandPerSec: (() => {
                const cons = v.getResConsumption();
                return cons && cons.catnip ? -cons.catnip * TPS : 0;
            })(),
        };
    });

    section("buildings", () => {
        out.buildings = [];
        for (const bd of g.bld.buildingsData) {
            const ext = g.bld.getBuildingExt(bd.name);
            const meta = ext.meta || bd;
            if (!meta.unlocked && !(bd.val > 0)) { continue; }
            let prices = [];
            try { prices = g.bld.getPrices(bd.name) || []; } catch (e) { /* stage-Sonderfälle */ }
            out.buildings.push({
                name: bd.name,
                label: meta.label || bd.name,
                val: bd.val,
                on: bd.on,
                unlocked: !!meta.unlocked,
                prices: prices.map(p => ({ name: p.name, val: p.val })),
            });
        }
    });

    section("science", () => {
        out.science = { techs: [] };
        for (const t of g.science.techs) {
            if (!t.unlocked && !t.researched) { continue; }
            out.science.techs.push({
                name: t.name,
                label: t.label,
                researched: !!t.researched,
                unlocked: !!t.unlocked,
                prices: (t.prices || []).map(p => ({ name: p.name, val: p.val })),
            });
        }
    });

    section("workshop", () => {
        out.workshop = { upgrades: [], crafts: [] };
        for (const u of g.workshop.upgrades) {
            if (!u.unlocked && !u.researched) { continue; }
            out.workshop.upgrades.push({
                name: u.name,
                label: u.label,
                researched: !!u.researched,
                unlocked: !!u.unlocked,
                prices: (u.prices || []).map(p => ({ name: p.name, val: p.val })),
            });
        }
        for (const c of g.workshop.crafts) {
            if (!c.unlocked) { continue; }
            out.workshop.crafts.push({
                name: c.name,
                label: c.label,
                prices: (c.prices || []).map(p => ({ name: p.name, val: p.val })),
            });
        }
        out.workshop.craftRatio = g.getResCraftRatio ? g.getResCraftRatio("_generic") : 0;
    });

    section("energy", () => {
        out.energy = {
            prod: g.resPool.energyProd,
            cons: g.resPool.energyCons,
        };
    });

    section("prestige", () => {
        const get = (n) => { const r = g.resPool.get(n); return r ? r.value : 0; };
        out.prestige = {
            paragon: get("paragon"),
            burnedParagon: get("burnedParagon"),
            karma: get("karma"),
            perks: (g.prestige && g.prestige.perks ? g.prestige.perks : [])
                .filter(p => p.unlocked || p.researched)
                .map(p => ({
                    name: p.name, label: p.label,
                    researched: !!p.researched, unlocked: !!p.unlocked,
                    prices: (p.prices || []).map(x => ({ name: x.name, val: x.val })),
                })),
        };
    });

    section("religion", () => {
        // Religion-Upgrades werden über den WORSHIP-Stand sichtbar
        // (religion.js:1925: visible = on > 0 || religion.faith >= meta.faith),
        // das unlocked-Flag der Metadaten bleibt dabei false!
        const worship = g.religion.faith || 0;
        const mapUpgrades = (list, worshipGated) => (list || [])
            .filter(u => u.unlocked || (u.val > 0) || u.on
                || (worshipGated && worship >= (u.faith || Infinity)))
            .map(u => ({
                name: u.name, label: u.label,
                val: u.val || 0, on: u.on || 0,
                unlocked: !!u.unlocked
                    || (worshipGated && worship >= (u.faith || Infinity)),
                noStackable: !!u.noStackable,
                prices: (u.prices || []).map(p => ({
                    name: p.name,
                    val: p.val * Math.pow(u.priceRatio || 1, u.val || 0),
                })),
            }));
        out.religion = {
            worship: worship,                    // "Total faith" = Worship-Pool
            epiphany: g.religion.faithRatio,     // permanenter Faith-Bonus
            transcendenceTier: g.religion.transcendenceTier || 0,
            upgrades: mapUpgrades(g.religion.religionUpgrades, true),
            ziggurat: mapUpgrades(g.religion.zigguratUpgrades, false),
        };
    });

    section("diplomacy", () => {
        out.diplomacy = { races: [], undiscovered: false };
        if (g.diplomacy && g.diplomacy.races) {
            for (const r of g.diplomacy.races) {
                if (!r.unlocked) { out.diplomacy.undiscovered = true; continue; }
                out.diplomacy.races.push({
                    name: r.name,
                    title: r.title,
                    // Was die Rasse pro Trade verlangt (zusätzlich zu 15 Gold + 50 Catpower):
                    buys: (r.buys || []).map(p => ({ name: p.name, val: p.val })),
                    // Was sie liefert (value = Menge pro Trade, chance in %):
                    sells: (r.sells || []).map(s => ({
                        name: s.name, value: s.value, chance: s.chance,
                    })),
                });
            }
        }
    });

    section("space", () => {
        out.space = { programs: [], planets: [] };
        if (g.space && g.space.programs) {
            for (const p of g.space.programs) {
                if (!p.unlocked && !(p.val > 0)) { continue; }
                out.space.programs.push({
                    name: p.name, label: p.label, val: p.val || 0,
                    unlocked: !!p.unlocked,
                    prices: (p.prices || []).map(x => ({ name: x.name, val: x.val })),
                });
            }
            for (const planet of (g.space.planets || [])) {
                if (!planet.unlocked) { continue; }
                out.space.planets.push({
                    name: planet.name, label: planet.label,
                    buildings: (planet.buildings || [])
                        .filter(b => b.unlocked || b.val > 0)
                        .map(b => ({
                            name: b.name, label: b.label, val: b.val || 0,
                            unlocked: !!b.unlocked,
                            // Effektivpreise inkl. Price Ratio:
                            prices: (b.prices || []).map(x => ({
                                name: x.name,
                                val: x.val * Math.pow(b.priceRatio || 1, b.val || 0),
                            })),
                        })),
                });
            }
        }
    });

    section("effects", () => {
        // Basis-Catnip-Produktion der Felder (pro Tick, vor Saison-Modifier).
        // Grundlage der Worst-Winter-Reserverechnung (Spec 7.2).
        out.effects = {
            catnipPerTickBase: g.getEffect("catnipPerTickBase") || 0,
        };
    });

    section("tabs", () => {
        out.tabs = (g.tabs || []).map(t => ({ id: t.tabId, visible: !!t.visible }));
    });

    return out;
}
