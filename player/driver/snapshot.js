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
            // Alle vier Saison-Modifikatoren (Frühling..Winter) für die
            // Catnip-Saisonprojektion (Spec 7.2):
            seasonCatnipModifiers: (c.seasons || []).map(s =>
                (s.modifiers || {}).catnip !== undefined ? s.modifiers.catnip : 1),
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

        // Effektive Marginalraten PRO KITTEN und Sekunde je Job (#40,
        // Spec 12.2): Nachbau von village.js updateResourceProduction
        // (505-587) für EIN marginales Skill-0-Kitten (Skill < 100 →
        // getValueModifierPerSkill = 0, village.js:1117-1145), multipliziert
        // mit der calcResourcePerTick-Kette (game.js:3243-3331), soweit sie
        // auf Villager-Produktion wirkt. Weather bewusst NICHT: der
        // Saisonmodifikator wird im Spiel VOR der Villager-Addition
        // multipliziert (game.js:3240 vs. 3255) und trifft Jobs nie.
        // Verstärkte Happiness (village.js:510-511):
        const ampHappiness = v.happiness + (v.happiness - 1)
            * (g.getEffect("happinessKittenProductionRatio") || 0);
        // Team-Boost des Leaders für Nicht-Leader (village.js:538-541);
        // das marginale Kitten ist nie selbst Leader:
        let teamBoost = 1;
        if (v.leader && typeof v.getLeaderBonus === "function") {
            teamBoost = 1 + (v.getLeaderBonus(v.leader.rank) - 1)
                * (g.getEffect("boostFromLeader") || 0);
        }
        const hgScaling = (g.religion && typeof g.religion.getHGScalingBonus === "function")
            ? (g.religion.getHGScalingBonus() || 1) : 1;
        const marginalMult = (resName) => {
            const res = g.resPool.get(resName);
            if (!res) { return 1; }
            // game.js:3249-3259: ×HolyGenocide, +resProduction×JobRatio:
            let m = hgScaling * (1 + (g.getEffect(resName + "JobRatio") || 0));
            // game.js:3262-3272: Global/Buildings/Religion/Super:
            m *= 1 + (g.getEffect(resName + "GlobalRatio") || 0);
            m *= 1 + (g.getEffect(resName + "Ratio") || 0);
            m *= 1 + (g.getEffect(resName + "RatioReligion") || 0);
            m *= 1 + (g.getEffect(resName + "SuperRatio") || 0);
            // Steamworks-Coal-Hack (game.js:3274-3279):
            const sw = g.bld.get("steamworks");
            const swGlobal = sw && sw.effects && sw.effects[resName + "RatioGlobal"];
            if (sw && sw.on > 0 && swGlobal) { m *= 1 + swGlobal; }
            // Paragon (game.js:3281-3287; Winter-Challenge nullt catnip):
            let paragonRatio = g.prestige.getParagonProductionRatio() || 0;
            if (resName === "catnip" && g.challenges.isActive("winterIsComing")) {
                paragonRatio = 0;
            }
            m *= 1 + paragonRatio;
            // Pollution (game.js:3289-3292):
            if (resName === "catnip") {
                m *= 1 + ((g.bld.pollutionEffects || {})["catnipPollutionRatio"] || 0);
            }
            // Magnetos (game.js:3303-3310):
            if (!res.transient && g.bld.get("magneto").on > 0
                    && resName !== "catnip" && resName !== "oil") {
                const swRatio = (sw && sw.on > 0)
                    ? 1 + ((sw.effects || {})["magnetoBoostRatio"] || 0) * sw.on : 1;
                m *= 1 + (g.getEffect("magnetoRatio") || 0) * swRatio;
            }
            // Reaktor (game.js:3317-3319):
            if (!res.transient && resName !== "uranium" && resName !== "catnip") {
                m *= 1 + (g.getEffect("productionRatio") || 0);
            }
            // Solar Revolution inkl. Pollution-Malus auf wood/catnip
            // (game.js:3326):
            m *= 1 + (g.religion.getSolarRevolutionRatio() || 0)
                * (1 + ((resName === "wood" || resName === "catnip")
                    ? ((g.bld.pollutionEffects || {})["solarRevolutionPollution"] || 0) : 0));
            // Kosmische Strahlung (game.js:3329-3331):
            if (!(g.opts && g.opts.disableCMBR) && resName !== "coal"
                    && typeof g.getCMBRBonus === "function") {
                m *= 1 + (g.getCMBRBonus() || 0);
            }
            return m;
        };

        const jobs = [];
        for (const j of v.jobs) {
            if (!j.unlocked) { continue; }
            const entry = { name: j.name, title: j.title, value: j.value };
            try {
                // modifiers sind bei scholar/geologist lazy (erst
                // calculateEffects füllt sie, village.js:42/108).
                // priest.calculateEffects NIE aufrufen — es entlässt bei
                // Atheism alle Priester (village.js:87-98, Seiteneffekt!).
                let mods = j.modifiers;
                if ((!mods || Object.keys(mods).length === 0)
                        && j.name !== "priest"
                        && typeof j.calculateEffects === "function") {
                    j.calculateEffects(j, g);
                    mods = j.modifiers;
                }
                const rates = {};
                for (const resName in (mods || {})) {
                    const base = mods[resName];
                    if (typeof base !== "number" || !isFinite(base)) { continue; }
                    // village.js:530-543: diff = mod × (1 + skillMod)
                    // [Skill 0 → ×1]; nur POSITIVE Produktion bekommt
                    // TeamBoost und Happiness:
                    let perTick = base;
                    if (perTick > 0) { perTick *= teamBoost * ampHappiness; }
                    rates[resName] = perTick * marginalMult(resName) * TPS;
                }
                entry.ratesPerKitten = rates;
            } catch (e) { /* Feld weglassen → Python-Fallback JOB_BASE_RATES */ }
            jobs.push(entry);
        }
        let leader = null;
        if (v.leader) {
            leader = {
                name: (v.leader.name || "") + " " + (v.leader.surname || ""),
                trait: v.leader.trait ? v.leader.trait.name : null,
                job: v.leader.job || null,
            };
        }
        // Census-Kurzliste für die Leader-Wahl (Spec 12.3): nur die vier
        // relevanten Felder, defensiv und auf 60 Einträge begrenzt —
        // village.sim.kittens kann sehr groß werden.
        const CENSUS_LIMIT = 60;
        let census = [];
        let censusTruncated = false;
        try {
            const sim = (v.sim && v.sim.kittens) || [];
            censusTruncated = sim.length > CENSUS_LIMIT;
            for (let i = 0; i < sim.length && i < CENSUS_LIMIT; i++) {
                const k = sim[i];
                census.push({
                    index: i,
                    name: ((k.name || "") + " " + (k.surname || "")).trim(),
                    trait: (k.trait && k.trait.name) || null,
                    job: k.job || null,
                    isLeader: !!k.isLeader,
                });
            }
        } catch (e) { census = []; censusTruncated = false; }
        out.village = {
            kittens: v.getKittens(),
            maxKittens: v.maxKittens,
            freeKittens: v.getFreeKittens(),
            happiness: v.happiness,          // 1.0 = 100 %
            jobs: jobs,
            leader: leader,
            census: census,
            censusTruncated: censusTruncated,
            // Catnip-Verbrauch der Population pro Sekunde (positiv = Verbrauch):
            catnipDemandPerSec: (() => {
                const cons = v.getResConsumption();
                return cons && cons.catnip ? -cons.catnip * TPS : 0;
            })(),
            // Kitten-Ankunftsrate pro Sekunde (Spec 5.2, Lücke #36):
            // village.js calculateKittensPerTick() = kittensPerTickBase(0.01)
            // × (1 + kittenGrowthRatio), ×(2 + festivalArrivalRatio) während
            // eines Festivals, ÷ pollutionArrivalSlowdown (wenn > 1);
            // gespawnt wird via sim.nextKittenProgress, solange Housing-
            // Kapazität frei ist (village.js update/sim.update).
            kittensPerSec: (() => {
                try {
                    if (typeof v.calculateKittensPerTick === "function") {
                        return v.calculateKittensPerTick() * TPS;
                    }
                    // Fallback ältere Versionen: Basisrate × Growth-Effekt.
                    return (v.kittensPerTickBase || 0.01)
                        * (1 + (g.getEffect("kittenGrowthRatio") || 0)) * TPS;
                } catch (e) { return 0; }
            })(),
        };
    });

    section("buildings", () => {
        out.buildings = [];
        for (const bd of g.bld.buildingsData) {
            const ext = g.bld.getBuildingExt(bd.name);
            // getMeta() mischt bei Staged Buildings (library/pasture/
            // aqueduct/amphitheatre …) die Attribute der AKTUELLEN Stage
            // ein — deren effects setzt calculateEffects zur Laufzeit in
            // stages[stage].effects (buildings.js:608 stageMeta.effects),
            // die Top-Level-Effekte sind dort 0/leer. Ohne den Merge war
            // die Gebäudebewertung (#35) für diese Klasse blind (Live-
            // Fund: Library ohne effects → flacher Engpass-Bonus).
            let meta = ext.meta || bd;
            try {
                if (typeof ext.getMeta === "function") { meta = ext.getMeta() || meta; }
            } catch (e) { /* Merge-Fehler → Rohobjekt reicht */ }
            if (!meta.unlocked && !(bd.val > 0)) { continue; }
            let prices = [];
            try { prices = g.bld.getPrices(bd.name) || []; } catch (e) { /* stage-Sonderfälle */ }
            // Effekte PRO EINHEIT (Spec 13.1/16.4), defensiv: die Effekte
            // liegen je nach Gebäude in buildingsData bzw. den Stage-Metadaten
            // (calculateEffects hält sie zur Laufzeit aktuell). Volles Dict
            // für die Gebäudebewertung (#35): nur numerisch-endliche Werte
            // ≠ 0 — Namenskonvention aus buildings.js: <res>PerTickProd/Con/
            // Base, <res>Max, <res>Ratio/DemandRatio, happiness,
            // cathPollutionPerTickProd. Aggregation im Spiel: effect =
            // effectValue × bld.on (Max-Effekte × bld.val, coalRatioGlobal
            // ungestaffelt — buildings.js getEffect).
            const effects = meta.effects || bd.effects || {};
            const eff = {};
            for (const k in effects) {
                const v = effects[k];
                if (typeof v === "number" && isFinite(v) && v !== 0) { eff[k] = v; }
            }
            out.buildings.push({
                name: bd.name,
                label: meta.label || bd.name,
                val: bd.val,
                on: bd.on,
                unlocked: !!meta.unlocked,
                prices: prices.map(p => ({ name: p.name, val: p.val })),
                effects: eff,
                energyConsumption: +effects.energyConsumption || 0,
                energyProduction: +effects.energyProduction || 0,
            });
        }
    });

    section("pollution", () => {
        // Pollution-Zustand (#35): kumulierte cathPollution (buildings.js
        // Feld cathPollution) und der aktuelle Arrival-Slowdown aus
        // calculatePollutionEffects (buildings.js: ab Level 2 linear
        // 1 + 1.68e-8·(pollution − POL_LBASE·100/2), höhere Level log10) —
        // village.js teilt kittensPerTick durch den Slowdown (> 1).
        out.pollution = {
            cathPollution: (g.bld && +g.bld.cathPollution) || 0,
            arrivalSlowdown: (g.bld && g.bld.pollutionEffects
                && +g.bld.pollutionEffects.pollutionArrivalSlowdown) || 0,
        };
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
        // ACHTUNG Namenstrennung (religion.js): religion.faith ist der
        // WORSHIP-Pool, religion.faithRatio die EPIPHANY; der Live-Faith-
        // Pool ist die resPool-Ressource "faith" (religion.js:1569-1622).
        const guard = (fn, fallback) => { try { return fn(); } catch (e) { return fallback; } };
        out.religion = {
            worship: worship,                    // "Total faith" = Worship-Pool
            epiphany: g.religion.faithRatio,     // permanenter Faith-Bonus
            faith: guard(() => g.resPool.get("faith").value, 0),  // Live-Pool
            transcendenceTier: g.religion.transcendenceTier || 0,
            // Apocrypha (sic — Spielname "apocripha", religion.js:1199) und
            // sein Bonus über die offizielle API (religion.js:1523-1525):
            apocrypha: {
                on: guard(() => !!g.religion.getRU("apocripha").on, false),
                bonus: guard(() => g.religion.getApocryphaBonus(), 0),
            },
            transcendenceOn: guard(() => !!g.religion.getRU("transcendence").on, false),
            // Epiphany-Preis des nächsten Tiers (religion.js:1659-1661):
            transcendenceNextPrice: guard(() => g.religion._getTranscendNextPrice(), null),
            // TC je 25 geopferten Alicorns = 1 + tcRefineRatio (religion.js:3040):
            tcRefineRatio: guard(() => g.getEffect("tcRefineRatio") || 0, 0),
            upgrades: mapUpgrades(g.religion.religionUpgrades, true),
            ziggurat: mapUpgrades(g.religion.zigguratUpgrades, false),
        };
    });

    section("pacts", () => {
        // Pacts & Necrocorn-Ökonomie (Spec 15.5): religion.pactsManager
        // (religion.js pactsManager). Die Sektion existiert NUR, wenn die
        // Pact-Schicht erreichbar ist (ein Pact unlocked/gekauft oder
        // Schuld vorhanden) — vorher fehlt der Key komplett.
        const rel = g.religion;
        const pm = rel && rel.pactsManager;
        if (!pm || !pm.pacts) { return; }
        const anyRelevant = pm.pacts.some(p => p.unlocked || (p.val > 0))
            || (pm.necrocornDeficit || 0) > 0;
        if (!anyRelevant) { return; }
        const getEff = (n) => { try { return g.getEffect(n) || 0; } catch (e) { return 0; } };
        const tryBool = (fn) => { try { return !!fn(); } catch (e) { return false; } };
        out.pacts = {
            list: pm.pacts.map(p => ({
                name: p.name, label: p.label,
                val: p.val || 0, on: p.on || 0,
                unlocked: !!p.unlocked,
                special: !!p.special,               // payDebt/fractured
                // priceRatio ist bei Pacts fest 1 (pactsManager.constructor):
                prices: (p.prices || []).map(x => ({ name: x.name, val: x.val })),
            })),
            necrocorns: (g.resPool.get("necrocorn") || {}).value || 0,
            necrocornDeficit: pm.necrocornDeficit || 0,
            pactsAvailable: getEff("pactsAvailable"),
            // Gesamtverbrauch/Tag (negativ, religion.js effectsBase 1459):
            necrocornPerDay: getEff("necrocornPerDay"),
            necrocornUpfrontCost: getEff("pactNecrocornUpfrontCost"),
            // Siphoning-Policy aktiv? (religion.js:374-392, Policy science.js):
            siphoning: tryBool(() => g.science.getPolicy("siphoning").researched),
            fractured: tryBool(() => rel.getPact("fractured").on > 0),
            // Debt-Penalty-Faktor 1…0 (religion.js getDebtPenaltyRatio):
            deficitPenaltyRatio: (() => {
                try { return pm.getDebtPenaltyRatio(); } catch (e) { return 1; }
            })(),
        };
    });

    section("diplomacy", () => {
        out.diplomacy = { races: [], undiscovered: false, standingRatio: 0, tradeRatio: 0 };
        if (g.diplomacy && g.diplomacy.races) {
            // Globale Handelsboni (diplomacy.js tradeImpl, 1.5.0.2):
            // standingRatio verbessert Standing-Würfe (Tradeposts/Perks),
            // tradeRatio erhöht die Erfolgsmenge (+1 % pro Trade Ship).
            try { out.diplomacy.standingRatio = g.getEffect("standingRatio") || 0; } catch (e) { /* optional */ }
            try { out.diplomacy.tradeRatio = g.getEffect("tradeRatio") || 0; } catch (e) { /* optional */ }
            for (const r of g.diplomacy.races) {
                if (!r.unlocked) { out.diplomacy.undiscovered = true; continue; }
                out.diplomacy.races.push({
                    name: r.name,
                    title: r.title,
                    unlocked: !!r.unlocked,
                    // Standing-Daten für die EV-Rechnung (Spec 14.1):
                    // attitude "friendly"|"neutral"|"hostile", standing = Wurf-Basis.
                    attitude: r.attitude || null,
                    standing: (typeof r.standing === "number") ? r.standing : 0,
                    embassyLevel: r.embassyLevel || 0,
                    // Was die Rasse pro Trade verlangt (zusätzlich zu 15 Gold + 50 Catpower):
                    buys: (r.buys || []).map(p => ({ name: p.name, val: p.val })),
                    // Was sie liefert (value = Menge pro Trade, chance in %,
                    // seasons = additive Saison-Modifikatoren, delta = Streuung):
                    sells: (r.sells || []).map(s => ({
                        name: s.name, value: s.value, chance: s.chance,
                        delta: (typeof s.delta === "number") ? s.delta : null,
                        seasons: (s.seasons && typeof s.seasons === "object") ? {
                            spring: +s.seasons.spring || 0,
                            summer: +s.seasons.summer || 0,
                            autumn: +s.seasons.autumn || 0,
                            winter: +s.seasons.winter || 0,
                        } : null,
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
                        .map(b => {
                            // Effekte PRO EINHEIT (Spec 16.2/16.3, #35),
                            // defensiv wie in der buildings-Sektion:
                            const effects = b.effects || {};
                            const eff = {};
                            for (const k in effects) {
                                const v = effects[k];
                                if (typeof v === "number" && isFinite(v) && v !== 0) { eff[k] = v; }
                            }
                            return {
                                name: b.name, label: b.label, val: b.val || 0,
                                unlocked: !!b.unlocked,
                                effects: eff,
                                energyConsumption: +effects.energyConsumption || 0,
                                energyProduction: +effects.energyProduction || 0,
                                // Effektivpreise inkl. Price Ratio:
                                prices: (b.prices || []).map(x => ({
                                    name: x.name,
                                    val: x.val * Math.pow(b.priceRatio || 1, b.val || 0),
                                })),
                            };
                        }),
                });
            }
        }
    });

    section("time", () => {
        const mapTU = (list) => (list || [])
            .filter(u => u.unlocked || u.val > 0)
            .map(u => ({
                name: u.name, label: u.label, val: u.val || 0,
                unlocked: !!u.unlocked,
                prices: (u.prices || []).map(p => ({
                    name: p.name,
                    val: p.val * Math.pow(u.priceRatio || 1, u.val || 0),
                })),
            }));
        // Tempus-Fugit-Zustand (Anhang B): isAccelerated ist der Toggle
        // (time.js:1086-1097), temporalFlux die verbrauchte Ressource
        // (−1 je Tick, time.js:153-155) — defensiv, falls noch gesperrt.
        let temporalFlux = null;
        try {
            const tf = g.resPool.get("temporalFlux");
            if (tf) { temporalFlux = { value: tf.value, maxValue: tf.maxValue || 0 }; }
        } catch (e) { /* optional */ }
        out.time = {
            heat: (g.time && g.time.heat) || 0,
            heatMax: g.getEffect("heatMax") || 0,
            flux: (g.time && g.time.flux) || 0,
            isAccelerated: !!(g.time && g.time.isAccelerated),
            temporalFlux: temporalFlux,
            chronoforge: g.time ? mapTU(g.time.chronoforgeUpgrades) : [],
            voidspace: g.time ? mapTU(g.time.voidspaceUpgrades) : [],
        };
    });

    section("policies", () => {
        // Policies (Spec 13.4 / I-07): game.science.policies (science.js:850 ff).
        // blocked = eine exklusive Alternative wurde zuerst erforscht — bleibt
        // bis zum Reset gesperrt (science.js:847-849). Effektivpreise wie
        // PolicyBtnController.getPrices: ×1.25^policyFakeBought (Pacifism).
        if (!g.science || !g.science.policies) { return; }
        let fake = 0;
        try { fake = g.getEffect("policyFakeBought") || 0; } catch (e) { /* optional */ }
        out.policies = [];
        for (const p of g.science.policies) {
            if (!p.unlocked && !p.researched && !p.blocked) { continue; }
            out.policies.push({
                name: p.name,
                label: p.label,
                researched: !!p.researched,
                blocked: !!p.blocked,
                unlocked: !!p.unlocked,
                // Exklusive Alternativen (I-07-Bewertung):
                blocks: (p.blocks || []).slice(),
                prices: (p.prices || []).map(x => ({
                    name: x.name,
                    val: x.val * Math.pow(1.25, fake),
                })),
            });
        }
    });

    section("challenges", () => {
        // Challenges (Spec Kap. 18): game.challenges.challenges (challenges.js:42 ff).
        // researched = Erstabschluss, on = Anzahl Abschlüsse, active = läuft
        // gerade, pending = beim nächsten Reset aktivieren (challenges.js:508-514).
        if (!g.challenges || !g.challenges.challenges) { return; }
        const list = [];
        for (const c of g.challenges.challenges) {
            if (!c.unlocked && !c.researched && !(c.on > 0) && !c.active) { continue; }
            list.push({
                name: c.name,
                label: c.label,
                researched: !!c.researched,
                on: c.on || 0,
                unlocked: !!c.unlocked,
                active: !!c.active,
                pending: !!c.pending,
            });
        }
        let anyActive = list.some(c => c.active);
        try {
            if (typeof g.challenges.anyChallengeActive === "function") {
                anyActive = !!g.challenges.anyChallengeActive();
            }
        } catch (e) { /* optional */ }
        let reservesExist = false;
        try {
            reservesExist = !!(g.challenges.reserves
                && g.challenges.reserves.reservesExist
                && g.challenges.reserves.reservesExist());
        } catch (e) { /* optional */ }
        out.challenges = {
            list: list,
            anyActive: anyActive,
            countPending: list.filter(c => c.pending).length,
            reservesExist: reservesExist,
        };
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
