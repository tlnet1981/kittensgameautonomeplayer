"""Policy-Wahl (Spielmechanik-Spec 13.4 + Invariante I-07).

Policies sind exklusive, irreversible Modifierpakete: wer z. B. Liberty
erforscht, blockiert Tradition für den ganzen Run (science.js:847-849:
„Once policy is blocked, there is no way to unlock it other than reset").
Deshalb gilt Invariante I-07: Eine exklusive Policy DARF nur gewählt
werden, wenn alle ausgeschlossenen Alternativen im Planwert berücksichtigt
wurden — hier: PolicyValue(gewählt) ≥ PolicyValue(Alternative) für jede
Alternative aus dem `blocks`-Vektor, beide über denselben λ-Horizont.

Bewertung (PolicyValue in Ziel-Sekunden, wie shadow.net_value):

    PolicyValue(p) = Benefit_time(ΔRate(p), λ, H) − Cost_time(prices(p), λ)

ΔRate(p) kommt aus der Effekt-Referenztabelle POLICY_EFFECTS unten. Die
Tabelle deckt seit #37 ALLE 66 Policies des policies-Arrays der
Referenzversion ab (gamefiles/js/science.js, Zeilen 850-2189); jede Zeile
nennt die Quelle. Übersetzungs-Konventionen (dokumentierte
REFERENZSCHÄTZUNGEN, keine Spielkonstanten):

- rate_ratio {res: r}: ±r × aktuelle Produktionsrate der Ressource.
  Exakt (estimate False), wo das Spiel einen "...PolicyRatio"-Effekt
  trägt (z. B. rationality: sciencePolicyRatio 0.05); sonst Schätzung.
- global_ratio g: g × Rate für JEDE Ressource mit λ > 0 — Proxy für
  Happiness-/Global-Effekte. Konvention: 0.01 je Happiness-Punkt
  (environmentalism +3 → 0.03; stripMining environmentUnhappiness −2
  → −0.02 zusätzlich zum exakten rate_ratio).
- Job-/Hunt-Ratio (hunterRatio): rate_ratio auf die Jobressource als
  OBERGRENZE (griffinRelationsScouts hunterRatio 0.5 → manpower 0.5).
- Cap-Effekte: Konvention ×0.25 des Cap-Ratios als Ratenschätzung
  (cityOnAHill onAHillCultureCap 0.05 → culture 0.0125).
- Schmale Gebäude-Craft-Effekte: Gewicht 0.2 (fullIndustrialization).
- Embassy-skalierte Effekte: Mittelschätzung des Spielbereichs
  (spiderRelationsGeologists min(0.002·Embassies, 0.15) → 0.075).
- {"unratable": True}: der Effekt ist ehrlich NICHT auf beobachtbare
  Raten abbildbar (Meme-/Pact-/Terraforming-/Trade-Mechaniken, tote
  Effekte). PolicyValue = 0.0 — weder Nutzen noch Malus behauptet. Als
  Alternative zählt sie 0 (die I-07-Alternativen-Prüfung entscheidet,
  kein stiller Ausschluss mehr); als Kandidat scheitert sie am
  >0-Filter.

Kombinationsbewertung (13.4, #37): branch_value bewertet eine Policy als
ZWEIG über den Restplan — eigener Wert plus die per unlocks.policies
erreichbaren Nachfolger (BFS, Tiefe ≤ 3). Je Frontier-Gruppe (blocks-
Zusammenhangskomponente, nur EINE ist kaufbar) zählt das MAXIMUM,
Beitrag max(0, ·) × 1/(1+Tiefe) — harmonischer Diskont wie
shadow.path_weight (Nachfolger kommen später; geometrisch über den
Horizont würde sie totentwerten). Gemeinsame Nachfolger konkurrierender
Zweige (stoicism/epicurianism → rationality/mysticism) neutralisieren
sich im Vergleich. i07_check und best_policy vergleichen Zweigwerte;
best_policy nutzt run_plan["restzeitS"] (meta.determine_run_plan) als
Restplan-Horizont, falls endlich.

Suchraum-Prior (Spec 13.4, „Statische Defaults nur zur Suchraumreduktion"):
POLICY_PRIOR bildet die 13.4-Starttabelle auf unsere Run-Typen ab. Der
Prior wird um die exklusiven Gegenstücke der Kandidaten erweitert — sonst
könnte I-07 die Wahl dauerhaft blockieren, obwohl die (bewertete!)
Alternative die bessere ist.

Fallbacks: ohne `policies`-Sektion im Snapshot, ohne λ-Daten oder ohne
Effekt-Referenz entsteht KEIN Kandidat (Wert 0 → nicht positiv).
"""

from __future__ import annotations

import math

from player.state import access as A

from . import shadow

EPS = 1e-9

# ------------------------------------------------------- Effekt-Referenztabelle
# Quelle: gamefiles/js/science.js, policies-Array (Kittens Game 1.5.0.2 r3).
# "estimate": True = der Spieleffekt ist keine direkte Produktionsrate;
# die rate_ratio-/global_ratio-Übersetzung ist eine dokumentierte
# REFERENZSCHÄTZUNG (ehrlich gekennzeichnet, keine Spielkonstante).
POLICY_EFFECTS: dict[str, dict] = {
    # --- Frühzeit (writing unlocks liberty/tradition, science.js:161) ---
    "liberty": {
        # science.js: happinessKittenProductionRatio 0.1 (+maxKittens 1) —
        # globaler Produktions-Proxy.
        "global_ratio": 0.10, "estimate": True,
        "source": "science.js liberty: happinessKittenProductionRatio 0.1",
    },
    "tradition": {
        # science.js: cultureFromManuscripts +1, manuscriptParchmentCost −5 —
        # als +10 % Culture-Rate geschätzt.
        "rate_ratio": {"culture": 0.10}, "estimate": True,
        "source": "science.js tradition: cultureFromManuscripts 1",
    },
    # --- Klassik (liberty/tradition unlocks, science.js:866/887) ---
    "monarchy": {
        # science.js: goldPolicyRatio −0.1 (exakter Ratensatz).
        "rate_ratio": {"gold": -0.10}, "estimate": False,
        "source": "science.js monarchy: goldPolicyRatio -0.1",
    },
    "republic": {
        # science.js: boostFromLeader 0.01 — kleiner globaler Proxy.
        "global_ratio": 0.01, "estimate": True,
        "source": "science.js republic: boostFromLeader 0.01",
    },
    "authocracy": {
        # science.js: rankLeaderBonusConversion (0.004 × uncapped Housing).
        "global_ratio": 0.005, "estimate": True,
        "source": "science.js authocracy: rankLeaderBonusConversion",
    },
    # --- Foreign Policy (currency unlocks, science.js:149) ---
    "diplomacy": {
        # science.js: tradeCatpowerDiscount 5 (−5 Catpower je Trade) —
        # als +5 % effektive Catpower-Rate geschätzt.
        "rate_ratio": {"manpower": 0.05}, "estimate": True,
        "source": "science.js diplomacy: tradeCatpowerDiscount 5",
    },
    "isolationism": {
        # science.js: tradeGoldDiscount 1 (−1 Gold je Trade) — klein.
        "rate_ratio": {"gold": 0.01}, "estimate": True,
        "source": "science.js isolationism: tradeGoldDiscount 1",
    },
    "zebraRelationsAppeasement": {
        # science.js: zebraRelationModifier +15, goldPolicyRatio −0.05.
        # Zebra-Standing verbessert Titanium-Trades → Titanium-Schätzung.
        "rate_ratio": {"gold": -0.05, "titanium": 0.15}, "estimate": True,
        "source": "science.js zebraRelationsAppeasement: zebraRelationModifier 15, goldPolicyRatio -0.05",
    },
    "zebraRelationsBellicosity": {
        # science.js: nonZebraRelationModifier +5, zebraRelationModifier −10.
        "rate_ratio": {"titanium": -0.10}, "estimate": True,
        "source": "science.js zebraRelationsBellicosity: zebraRelationModifier -10",
    },
    "knowledgeSharing": {
        # science.js: sciencePolicyRatio 0.05 (exakter Ratensatz).
        "rate_ratio": {"science": 0.05}, "estimate": False,
        "source": "science.js knowledgeSharing: sciencePolicyRatio 0.05",
    },
    "culturalExchange": {
        # science.js: culturePolicyRatio 0.05 (exakter Ratensatz).
        "rate_ratio": {"culture": 0.05}, "estimate": False,
        "source": "science.js culturalExchange: culturePolicyRatio 0.05",
    },
    "outerSpaceTreaty": {
        # science.js: globalRelationsBonus 10 — bessere Trades, kleiner Proxy.
        "global_ratio": 0.01, "estimate": True,
        "source": "science.js outerSpaceTreaty: globalRelationsBonus 10",
    },
    "militarizeSpace": {
        # science.js: satelliteSynergyBonus 0.1 → Starchart-Schätzung.
        "rate_ratio": {"starchart": 0.10}, "estimate": True,
        "source": "science.js militarizeSpace: satelliteSynergyBonus 0.1",
    },
    # --- Philosophie (philosophy unlocks, science.js:175) ---
    "epicurianism": {
        # science.js (sic!): luxuryHappinessBonus 1 — Happiness-Proxy.
        "global_ratio": 0.05, "estimate": True,
        "source": "science.js epicurianism: luxuryHappinessBonus 1",
    },
    "stoicism": {
        # science.js: luxuryDemandRatio −0.5, breweryConsumptionRatio −0.25 —
        # gesparter Luxuskonsum, kleiner globaler Proxy.
        "global_ratio": 0.02, "estimate": True,
        "source": "science.js stoicism: luxuryDemandRatio -0.5",
    },
    "carnivale": {
        # science.js: festivalArrivalRatio 0.3 — Kitten-Ankünfte-Proxy.
        "global_ratio": 0.02, "estimate": True,
        "source": "science.js carnivale: festivalArrivalRatio 0.3",
    },
    "extravagance": {
        # science.js: luxuryDemandRatio +2 — Netto-Malus.
        "global_ratio": -0.02, "estimate": True,
        "source": "science.js extravagance: luxuryDemandRatio 2",
    },
    # --- Industrie (evaluateLocks: Factory, science.js:1021 ff) ---
    "liberalism": {
        # science.js: goldCostReduction 0.2 → wie +20 % effektives Gold.
        "rate_ratio": {"gold": 0.20}, "estimate": True,
        "source": "science.js liberalism: goldCostReduction 0.2",
    },
    "communism": {
        # science.js: coal/iron/titaniumPolicyRatio 0.25 (exakte Ratensätze;
        # factoryCostReduction 0.3 unbewertet).
        "rate_ratio": {"coal": 0.25, "iron": 0.25, "titanium": 0.25},
        "estimate": False,
        "source": "science.js communism: coal/iron/titaniumPolicyRatio 0.25",
    },
    "fascism": {
        # science.js: logHouseCostReduction 0.5 — Housing-Proxy.
        "global_ratio": 0.02, "estimate": True,
        "source": "science.js fascism: logHouseCostReduction 0.5",
    },
    # --- Informationszeitalter (science.js:1075 ff) ---
    "technocracy": {
        # science.js: technocracyScienceCap 0.2 (Cap!), antimatterPolicyRatio
        # 0.0625 — Science-Cap als kleine Ratenschätzung, AM exakt.
        "rate_ratio": {"science": 0.05, "antimatter": 0.0625}, "estimate": True,
        "source": "science.js technocracy: technocracyScienceCap 0.2, antimatterPolicyRatio 0.0625",
    },
    "theocracy": {
        # science.js: faithPolicyRatio 0.2 (exakter Ratensatz).
        "rate_ratio": {"faith": 0.20}, "estimate": False,
        "source": "science.js theocracy: faithPolicyRatio 0.2",
    },
    "expansionism": {
        # science.js: unobtainiumPolicyRatio 0.15 (exakter Ratensatz).
        "rate_ratio": {"unobtainium": 0.15}, "estimate": False,
        "source": "science.js expansionism: unobtainiumPolicyRatio 0.15",
    },
    # --- Government-Seitenzweig (authocracy/republic unlocks socialism) ---
    "socialism": {
        # science.js: effects {} — „Empty on purpose; this is a meme policy!"
        "unratable": True,
        "source": "science.js socialism: effects {} (meme policy)",
    },
    "scientificCommunism": {
        # science.js: multipliziert nur die (leeren) socialism-Effekte ×1.25.
        "unratable": True,
        "source": "science.js scientificCommunism: skaliert leere socialism-Effekte",
    },
    # --- Tier 5 (1.5M Culture, science.js:1091-1152) ---
    "transkittenism": {
        # science.js: aiCoreProductivness 1, aiCoreUpgradeBonus 0.1 —
        # AI-Core-Endgame-Mechanik, aus dem Snapshot nicht seriös bewertbar.
        "unratable": True,
        "source": "science.js transkittenism: aiCoreProductivness 1",
    },
    "necrocracy": {
        # science.js: blsProductionBonus 0.001/BLS, leviathansEnergyModifier —
        # Sorrow-/Leviathan-Endgame, nicht auf Raten abbildbar.
        "unratable": True,
        "source": "science.js necrocracy: blsProductionBonus 0.001",
    },
    "radicalXenophobia": {
        # science.js: mausoleumBonus 1, pactsAvailable 5 — Pact-Mechanik.
        "unratable": True,
        "source": "science.js radicalXenophobia: mausoleumBonus 1, pactsAvailable 5",
    },
    # --- Foreign-Zweig unter isolationism (science.js:1199-1232) ---
    "bigStickPolicy": {
        # science.js: embassyCostReduction 0.15 — Einmalersparnis beim
        # Botschaftsbau, keine laufende Rate.
        "unratable": True,
        "source": "science.js bigStickPolicy: embassyCostReduction 0.15",
    },
    "cityOnAHill": {
        # science.js: onAHillCultureCap 0.05 (Culture-Cap, resources.js:940)
        # — Cap-Konvention ×0.25.
        "rate_ratio": {"culture": 0.0125}, "estimate": True,
        "source": "science.js cityOnAHill: onAHillCultureCap 0.05 (Cap ×0.25)",
    },
    # --- Race Relations (science.js:1233-1785, je Rasse ein Dreier-Block) ---
    "lizardRelationsEcologists": {
        # science.js: cathPollutionRatio −0.05 — weniger Pollution wirkt
        # global (Happiness/Catnip), kleiner Proxy.
        "global_ratio": 0.01, "estimate": True,
        "source": "science.js lizardRelationsEcologists: cathPollutionRatio -0.05",
    },
    "lizardRelationsPriests": {
        # science.js: faithFromManuscripts 1, cultureFromManuscripts −0.25 —
        # Konvention wie tradition (1 FromManuscripts ≈ +10 % Rate).
        "rate_ratio": {"faith": 0.10, "culture": -0.025}, "estimate": True,
        "source": "science.js lizardRelationsPriests: faithFromManuscripts 1, cultureFromManuscripts -0.25",
    },
    "lizardRelationsDiplomats": {
        # science.js: neutralRaceEmbassyStanding 0.001 — Standing neutraler
        # Rassen, ohne Handelsvolumen nicht bewertbar.
        "unratable": True,
        "source": "science.js lizardRelationsDiplomats: neutralRaceEmbassyStanding 0.001",
    },
    "sharkRelationsScribes": {
        # science.js: parchment-/manuscriptTradeChanceIncrease, ironBuy —
        # Trade-Chancen ohne beobachtbares Handelsvolumen.
        "unratable": True,
        "source": "science.js sharkRelationsScribes: parchmentTradeChanceIncrease 0.25",
    },
    "sharkRelationsMerchants": {
        # science.js: dynamischer Trade-Bonus (calculateTradeBonusFromPolicies).
        "unratable": True,
        "source": "science.js sharkRelationsMerchants: calculateTradeBonusFromPolicies",
    },
    "sharkRelationsBotanists": {
        # science.js: refinePolicyRatio 0.25 (Craft), biolabEnergyRatio −0.75,
        # breweryPolicyManpowerRatio — Craft-/Energie-Effekte ohne Ratenbasis.
        "unratable": True,
        "source": "science.js sharkRelationsBotanists: refinePolicyRatio 0.25 (Craft)",
    },
    "griffinRelationsMetallurgists": {
        # science.js: calcinerSteelRatioBonus 0.15 (buildings.js:1167,
        # Calciner-Stahl-Autoproduktion) — Schätzung auf die Steel-Rate.
        "rate_ratio": {"steel": 0.15}, "estimate": True,
        "source": "science.js griffinRelationsMetallurgists: calcinerSteelRatioBonus 0.15",
    },
    "griffinRelationsScouts": {
        # science.js: hunterRatio 0.5 (village.js:909-925, Jagdertrag) —
        # Job-Ratio-Obergrenze auf die Catpower-Verwertung.
        "rate_ratio": {"manpower": 0.50}, "estimate": True,
        "source": "science.js griffinRelationsScouts: hunterRatio 0.5",
    },
    "griffinRelationsMachinists": {
        # science.js: magnetoBoostBonusPolicy 0.005 — kleiner globaler
        # Produktions-Proxy (Magneto-Boost je Steamworks).
        "global_ratio": 0.005, "estimate": True,
        "source": "science.js griffinRelationsMachinists: magnetoBoostBonusPolicy 0.005",
    },
    "nagaRelationsMasons": {
        # science.js: quarrySlabCraftBonus 0.025 (Craft-Bonus, keine Rate).
        "unratable": True,
        "source": "science.js nagaRelationsMasons: quarrySlabCraftBonus 0.025",
    },
    "nagaRelationsCultists": {
        # science.js: zigguratTempleEffectPolicy 0.1 (buildings.js:2015) —
        # Tempel-Effektskalierung je Ziggurat, gebäudemix-abhängig.
        "unratable": True,
        "source": "science.js nagaRelationsCultists: zigguratTempleEffectPolicy 0.1",
    },
    "nagaRelationsArchitects": {
        # science.js: nagaBlueprintTradeChance/blueprintCraftRatio (Embassy-
        # abhängige Trade-/Craft-Chancen).
        "unratable": True,
        "source": "science.js nagaRelationsArchitects: nagaBlueprintTradeChance",
    },
    "spiderRelationsGeologists": {
        # science.js: minerals/coal/goldPolicyRatio = min(0.002·Embassies,
        # 0.15) — Embassy-Mittelschätzung 0.075.
        "rate_ratio": {"minerals": 0.075, "coal": 0.075, "gold": 0.075},
        "estimate": True,
        "source": "science.js spiderRelationsGeologists: min(0.002*Embassies, 0.15)",
    },
    "spiderRelationsChemists": {
        # science.js: schaltet Kerosene-Handel frei (neue Handelsware, kein
        # Ratio-Effekt).
        "unratable": True,
        "source": "science.js spiderRelationsChemists: Kerosene-Handel",
    },
    "spiderRelationsPaleontologists": {
        # science.js: oilPolicyRatio 0.1 (exakter Ratensatz); mintIvoryRatio
        # 0.15 bewusst unbewertet (schmaler Mint-Effekt).
        "rate_ratio": {"oil": 0.10}, "estimate": False,
        "source": "science.js spiderRelationsPaleontologists: oilPolicyRatio 0.1",
    },
    "dragonRelationsPhysicists": {
        # science.js: reactorEnergyRatio 0.25, harborLimitRatioPolicy 0.05 —
        # Energie-/Cap-Effekte ohne seriöse Ratenbasis.
        "unratable": True,
        "source": "science.js dragonRelationsPhysicists: reactorEnergyRatio 0.25",
    },
    "dragonRelationsAstrologers": {
        # science.js: starchartPolicyRatio 0.03 × (cycleYear+1) ∈ 0.03..0.15
        # — Mittelschätzung 0.09 (cycleYear 2).
        "rate_ratio": {"starchart": 0.09}, "estimate": True,
        "source": "science.js dragonRelationsAstrologers: starchartPolicyRatio 0.03*(cycleYear+1)",
    },
    "dragonRelationsDynamicists": {
        # science.js: trade-/huntCatpowerDiscount 5/10, catpowerReduction —
        # Konvention wie diplomacy (Discount 5 ≈ +5 %), hier dreifach.
        "rate_ratio": {"manpower": 0.15}, "estimate": True,
        "source": "science.js dragonRelationsDynamicists: tradeCatpowerDiscount 5, huntCatpowerDiscount 10",
    },
    # --- Philosophie-Nachfolger (stoicism/epicurianism unlocks) ---
    "rationing": {
        # science.js: hunterRatio 0.1 (Jagdertrag) + hapinnessConsumption-
        # Ratio −0.1 (game.js:3363, gesparter Konsum → kleiner Proxy).
        "rate_ratio": {"manpower": 0.10}, "global_ratio": 0.01,
        "estimate": True,
        "source": "science.js rationing: hunterRatio 0.1, hapinnessConsumptionRatio -0.1",
    },
    "frugality": {
        # science.js: mintRatio 0.1 (buildings.js:1690, Mint-Ertrag) — die
        # beobachteten Furs-/Ivory-Raten stammen aus dem Mint.
        "rate_ratio": {"furs": 0.10, "ivory": 0.10}, "estimate": True,
        "source": "science.js frugality: mintRatio 0.1",
    },
    "rationality": {
        # science.js: science-/ironPolicyRatio 0.05 (exakte Ratensätze).
        "rate_ratio": {"science": 0.05, "iron": 0.05}, "estimate": False,
        "source": "science.js rationality: sciencePolicyRatio 0.05, ironPolicyRatio 0.05",
    },
    "mysticism": {
        # science.js: culture-/faithPolicyRatio 0.05 (exakte Ratensätze).
        "rate_ratio": {"culture": 0.05, "faith": 0.05}, "estimate": False,
        "source": "science.js mysticism: culturePolicyRatio 0.05, faithPolicyRatio 0.05",
    },
    # --- Umwelt-Zweig (ecology unlocks, science.js:139) ---
    "stripMining": {
        # science.js: mineralsPolicyRatio 0.3 (exakt) + environment-
        # Unhappiness −2 (−0.02-Malus) + cathPollutionRatio 0.05.
        "rate_ratio": {"minerals": 0.30}, "global_ratio": -0.02,
        "estimate": True,
        "source": "science.js stripMining: mineralsPolicyRatio 0.3, environmentUnhappiness -2",
    },
    "clearCutting": {
        # science.js: woodPolicyRatio 0.3 (exakt) + environmentUnhappiness −2.
        "rate_ratio": {"wood": 0.30}, "global_ratio": -0.02,
        "estimate": True,
        "source": "science.js clearCutting: woodPolicyRatio 0.3, environmentUnhappiness -2",
    },
    "environmentalism": {
        # science.js: environmentHappinessBonus 3 → 0.01/Punkt.
        "global_ratio": 0.03, "estimate": True,
        "source": "science.js environmentalism: environmentHappinessBonus 3",
    },
    "sustainability": {
        # science.js: environmentHappinessBonus 5 → 0.05.
        "global_ratio": 0.05, "estimate": True,
        "source": "science.js sustainability: environmentHappinessBonus 5",
    },
    "fullIndustrialization": {
        # science.js: environmentFactoryCraftBonus 0.05 (schmaler Craft-
        # Effekt, Gewicht 0.2) + cathPollutionRatio 0.05.
        "global_ratio": 0.01, "estimate": True,
        "source": "science.js fullIndustrialization: environmentFactoryCraftBonus 0.05 (×0.2)",
    },
    "conservation": {
        # science.js: environmentHappinessBonus 5 → 0.05.
        "global_ratio": 0.05, "estimate": True,
        "source": "science.js conservation: environmentHappinessBonus 5",
    },
    "openWoodlands": {
        # science.js: minerals-/woodPolicyRatio 0.125 (exakt; cathPollution-
        # Ratio 0.05 bewusst unbewertet — kleiner Malus).
        "rate_ratio": {"minerals": 0.125, "wood": 0.125}, "estimate": False,
        "source": "science.js openWoodlands: minerals/woodPolicyRatio 0.125",
    },
    # --- Terraforming (Manpower-Preise, science.js:1979-2016) ---
    "cryochamberExtraction": {
        # science.js: kein effects-Dict; wandelt einmalig eine used
        # Cryochamber (onResearch) — Einmaleffekt, keine Rate.
        "unratable": True,
        "source": "science.js cryochamberExtraction: onResearch usedCryochambers +1",
    },
    "terraformingInsight": {
        # science.js: terraformingMaxKittensRatio 0.1 — Kitten-Cap auf
        # Terraforming-Stationen, nicht auf Raten abbildbar.
        "unratable": True,
        "source": "science.js terraformingInsight: terraformingMaxKittensRatio 0.1",
    },
    "spaceBasedTerraforming": {
        # science.js: mysticismBonus 0.05 — der Effekt hat in 1.5.0.2 KEINEN
        # Konsumenten im Spielcode (toter Effekt).
        "unratable": True,
        "source": "science.js spaceBasedTerraforming: mysticismBonus 0.05 (ohne Konsument)",
    },
    "clearSkies": {
        # science.js: mysticismBonus 0.05 — wie spaceBasedTerraforming.
        "unratable": True,
        "source": "science.js clearSkies: mysticismBonus 0.05 (ohne Konsument)",
    },
    # --- Pacts (Necrocorn-Preise, science.js:2017-2140) ---
    "siphoning": {
        # science.js: smallDebtPunishmentExemption, repayDebtOnNecrocorn-
        # Generation — Necrocorn-Schuldenmechanik.
        "unratable": True,
        "source": "science.js siphoning: smallDebtPunishmentExemption 5",
    },
    "feedingFrenzy": {
        # science.js: feedEldersEfficiencyRatio (UnlimitedDR über Pacts),
        # necrocornCorruptionInterference −0.1.
        "unratable": True,
        "source": "science.js feedingFrenzy: feedEldersEfficiencyRatio",
    },
    "upfrontPayment": {
        # science.js: pactNecrocornConsumption 5e-5, Upfront-Kosten 2/Pact.
        "unratable": True,
        "source": "science.js upfrontPayment: pactNecrocornConsumption 5e-5",
    },
}

# Referenzpreise (volle Preisvektoren) aus science.js — für die I-07-
# Bewertung von Alternativen, die im Snapshot (noch) nicht sichtbar sind,
# und für die Zweig-Nachfolger in branch_value. Fast alle Policies kosten
# Culture; Ausnahmen: stripMining/clearCutting SCIENCE (science.js:1889/
# 1912), Terraforming MANPOWER (:1981/2001), Pacts NECROCORN (:2020 ff).
# Exklusive Paare kosten im Spiel stets gleich viel („Policies with the
# same numerical cost are mutually exclusive", i18n msg.policy.exclusivity).
POLICY_REF_PRICES: dict[str, dict[str, float]] = {
    "liberty": {"culture": 150}, "tradition": {"culture": 150},
    "monarchy": {"culture": 1500}, "authocracy": {"culture": 1500},
    "republic": {"culture": 1500},
    "socialism": {"culture": 7500}, "scientificCommunism": {"culture": 8500},
    "diplomacy": {"culture": 1600}, "isolationism": {"culture": 1600},
    "environmentalism": {"culture": 2000},
    "stripMining": {"science": 2000}, "clearCutting": {"science": 2000},
    "lizardRelationsEcologists": {"culture": 2100},
    "lizardRelationsPriests": {"culture": 2100},
    "lizardRelationsDiplomats": {"culture": 2100},
    "sharkRelationsScribes": {"culture": 2200},
    "sharkRelationsMerchants": {"culture": 2200},
    "sharkRelationsBotanists": {"culture": 2200},
    "epicurianism": {"culture": 2500}, "stoicism": {"culture": 2500},
    "rationality": {"culture": 3000}, "mysticism": {"culture": 3000},
    "carnivale": {"culture": 3500}, "extravagance": {"culture": 3500},
    "rationing": {"culture": 3500}, "frugality": {"culture": 3500},
    "knowledgeSharing": {"culture": 4000}, "culturalExchange": {"culture": 4000},
    "bigStickPolicy": {"culture": 4000}, "cityOnAHill": {"culture": 4000},
    "zebraRelationsAppeasement": {"culture": 5000},
    "zebraRelationsBellicosity": {"culture": 5000},
    "nagaRelationsMasons": {"culture": 8000},
    "nagaRelationsCultists": {"culture": 8000},
    "nagaRelationsArchitects": {"culture": 8000},
    "outerSpaceTreaty": {"culture": 10000}, "militarizeSpace": {"culture": 10000},
    "sustainability": {"culture": 10000},
    "fullIndustrialization": {"culture": 10000},
    "conservation": {"culture": 10000}, "openWoodlands": {"culture": 10000},
    "cryochamberExtraction": {"manpower": 10000},
    "terraformingInsight": {"manpower": 10000},
    "liberalism": {"culture": 15000}, "communism": {"culture": 15000},
    "fascism": {"culture": 15000},
    "griffinRelationsMetallurgists": {"culture": 16000},
    "griffinRelationsScouts": {"culture": 16000},
    "griffinRelationsMachinists": {"culture": 16000},
    "spiderRelationsGeologists": {"culture": 20000},
    "spiderRelationsChemists": {"culture": 20000},
    "spiderRelationsPaleontologists": {"culture": 20000},
    "dragonRelationsPhysicists": {"culture": 30000},
    "dragonRelationsAstrologers": {"culture": 30000},
    "dragonRelationsDynamicists": {"culture": 30000},
    "spaceBasedTerraforming": {"culture": 45000}, "clearSkies": {"culture": 45000},
    "technocracy": {"culture": 150000}, "theocracy": {"culture": 150000},
    "expansionism": {"culture": 150000},
    "transkittenism": {"culture": 1500000}, "necrocracy": {"culture": 1500000},
    "radicalXenophobia": {"culture": 1500000},
    "siphoning": {"necrocorn": 1}, "feedingFrenzy": {"necrocorn": 1},
    "upfrontPayment": {"necrocorn": 1},
}

# unlocks.policies aus science.js (#37, Kombinationsbewertung 13.4): welche
# Nachfolge-Policies eine Policy freischaltet — die 13 Familien der
# Referenzversion (science.js liberty:866, tradition:887, monarchy:908,
# authocracy:942, republic:958, socialism:984, diplomacy:1183,
# isolationism:1199, stoicism:1786, epicurianism:1811, stripMining/
# clearCutting:1898/1920, environmentalism:1941).
POLICY_UNLOCKS: dict[str, tuple[str, ...]] = {
    "liberty": ("authocracy", "republic"),
    "tradition": ("authocracy", "monarchy"),
    "monarchy": ("liberalism", "fascism"),
    "authocracy": ("communism", "fascism", "socialism"),
    "republic": ("liberalism", "communism", "socialism"),
    "socialism": ("scientificCommunism",),
    "diplomacy": ("knowledgeSharing", "culturalExchange"),
    "isolationism": ("bigStickPolicy", "cityOnAHill"),
    "stoicism": ("rationality", "mysticism", "rationing", "frugality"),
    "epicurianism": ("rationality", "mysticism", "carnivale", "extravagance"),
    "stripMining": ("sustainability", "fullIndustrialization"),
    "clearCutting": ("sustainability", "fullIndustrialization"),
    "environmentalism": ("conservation", "openWoodlands"),
}

# blocks-Vektoren aus science.js (#37) — für die Gruppenbildung der Zweig-
# Nachfolger (Stubs tragen keine Snapshot-blocks): exklusive Gruppen sind
# die Zusammenhangskomponenten dieser Relation.
POLICY_REF_BLOCKS: dict[str, tuple[str, ...]] = {
    "liberty": ("tradition",), "tradition": ("liberty",),
    "monarchy": ("authocracy", "republic", "communism"),
    "authocracy": ("monarchy", "republic", "liberalism"),
    "republic": ("monarchy", "authocracy", "fascism"),
    "socialism": (), "scientificCommunism": (),
    "liberalism": ("communism", "fascism"),
    "communism": ("liberalism", "fascism"),
    "fascism": ("liberalism", "communism"),
    "technocracy": ("theocracy", "expansionism"),
    "theocracy": ("technocracy", "expansionism"),
    "expansionism": ("technocracy", "theocracy"),
    "transkittenism": ("necrocracy", "radicalXenophobia"),
    "necrocracy": ("transkittenism", "radicalXenophobia"),
    "radicalXenophobia": ("transkittenism", "necrocracy"),
    "diplomacy": ("isolationism",), "isolationism": ("diplomacy",),
    "zebraRelationsAppeasement": ("zebraRelationsBellicosity",),
    "zebraRelationsBellicosity": ("zebraRelationsAppeasement",),
    "knowledgeSharing": ("culturalExchange",),
    "culturalExchange": ("knowledgeSharing",),
    "bigStickPolicy": ("cityOnAHill",), "cityOnAHill": ("bigStickPolicy",),
    "outerSpaceTreaty": ("militarizeSpace",),
    "militarizeSpace": ("outerSpaceTreaty",),
    "lizardRelationsEcologists": ("lizardRelationsPriests", "lizardRelationsDiplomats"),
    "lizardRelationsPriests": ("lizardRelationsEcologists", "lizardRelationsDiplomats"),
    "lizardRelationsDiplomats": ("lizardRelationsEcologists", "lizardRelationsPriests"),
    "sharkRelationsScribes": ("sharkRelationsMerchants", "sharkRelationsBotanists"),
    "sharkRelationsMerchants": ("sharkRelationsScribes", "sharkRelationsBotanists"),
    "sharkRelationsBotanists": ("sharkRelationsScribes", "sharkRelationsMerchants"),
    "griffinRelationsMetallurgists": ("griffinRelationsMachinists", "griffinRelationsScouts"),
    "griffinRelationsScouts": ("griffinRelationsMachinists", "griffinRelationsMetallurgists"),
    "griffinRelationsMachinists": ("griffinRelationsMetallurgists", "griffinRelationsScouts"),
    "nagaRelationsMasons": ("nagaRelationsCultists", "nagaRelationsArchitects"),
    "nagaRelationsCultists": ("nagaRelationsMasons", "nagaRelationsArchitects"),
    "nagaRelationsArchitects": ("nagaRelationsMasons", "nagaRelationsCultists"),
    "spiderRelationsGeologists": ("spiderRelationsChemists", "spiderRelationsPaleontologists"),
    "spiderRelationsChemists": ("spiderRelationsGeologists", "spiderRelationsPaleontologists"),
    "spiderRelationsPaleontologists": ("spiderRelationsChemists", "spiderRelationsGeologists"),
    "dragonRelationsPhysicists": ("dragonRelationsAstrologers", "dragonRelationsDynamicists"),
    "dragonRelationsAstrologers": ("dragonRelationsPhysicists", "dragonRelationsDynamicists"),
    "dragonRelationsDynamicists": ("dragonRelationsPhysicists", "dragonRelationsAstrologers"),
    "stoicism": ("epicurianism",), "epicurianism": ("stoicism",),
    "carnivale": ("extravagance",), "extravagance": ("carnivale",),
    "rationing": ("frugality",), "frugality": ("rationing",),
    "rationality": ("mysticism",), "mysticism": ("rationality",),
    "stripMining": ("clearCutting", "environmentalism"),
    "clearCutting": ("stripMining", "environmentalism"),
    "environmentalism": ("stripMining", "clearCutting"),
    "sustainability": ("fullIndustrialization",),
    "fullIndustrialization": ("sustainability",),
    "conservation": ("openWoodlands",), "openWoodlands": ("conservation",),
    "cryochamberExtraction": ("terraformingInsight",),
    "terraformingInsight": ("cryochamberExtraction",),
    "spaceBasedTerraforming": ("clearSkies",),
    "clearSkies": ("spaceBasedTerraforming",),
    "siphoning": ("feedingFrenzy", "upfrontPayment"),
    "feedingFrenzy": ("siphoning", "upfrontPayment"),
    "upfrontPayment": ("siphoning", "feedingFrenzy"),
}

# ------------------------------------------------------------ 13.4-Prior
# Spec-13.4-Starttabelle → Run-Typ-Kontexte (Suchraumreduktion, kein Zwang).
# Spielnamen der Referenzversion: „Epicureanism" = epicurianism (sic),
# „Zebra Appeasement" = zebraRelationsAppeasement.
_EARLY = ("tradition", "monarchy", "diplomacy", "epicurianism",
          "zebraRelationsAppeasement", "rationality")
_TRADE = ("diplomacy", "liberalism", "zebraRelationsAppeasement",
          "outerSpaceTreaty")
# Industrie-Kontexte (#37): rationality (Science/Iron) und stripMining
# (Minerals) sind seit der Vollabdeckung bewertbar und gehören in den
# Suchraum der Industrie-/Zeitalter-Runs.
_INDUSTRY = ("technocracy", "expansionism", "communism", "rationality",
             "stripMining")
POLICY_PRIOR: dict[str, tuple[str, ...]] = {
    # „Früher Reset" (13.4 Zeile 1):
    "FIRST_RUN": _EARLY,
    "PRICE_RATIO_RUN": _EARLY,
    "CORE_META_RUN": _EARLY,
    "CHALLENGE_RUN": _EARLY,
    # „Housing-/Paragon-Run" (Fascism/Carnivale/Arrival-orientiert; die
    # Umwelt-Happiness-Policies zahlen auf die Kitten-Basis ein):
    "PARAGON_RUN": ("fascism", "carnivale", "epicurianism", "tradition",
                    "monarchy", "diplomacy", "environmentalism",
                    "conservation"),
    # „Handels-/Titanium-Run":
    "UNICORN_RUN": _TRADE,
    "LEVIATHAN_RUN": _TRADE,
    # „Faith" (Order-of-the-Stars-Pfad → theocracy in 1.5.0.2; mysticism
    # trägt den exakten faithPolicyRatio 0.05):
    "RELIGION_RUN": ("theocracy", "mysticism") + _EARLY,
    # „Industrie"/„Unobtainium" (Communism, Expansionism):
    "RELIC_STATION_RUN": _INDUSTRY + _TRADE,
    "SHATTER_RUN": _INDUSTRY + _TRADE,
    "SEED_RUN": ("technocracy", "expansionism", "rationality",
                 "stripMining") + _TRADE,
}
DEFAULT_PRIOR: tuple[str, ...] = _EARLY


# ------------------------------------------------------------ Bewertung

def _rate_delta(snap: dict, name: str, lam: dict[str, float]) -> dict[str, float]:
    """ΔRate der Policy aus der Referenztabelle (nur Ressourcen mit
    positiver laufender Produktion — ohne Rate keine seriöse Ratio-Basis)."""
    eff = POLICY_EFFECTS.get(name)
    if not eff:
        return {}
    delta: dict[str, float] = {}
    for res, ratio in sorted(eff.get("rate_ratio", {}).items()):
        rate = A.res_rate(snap, res)
        if rate > 0:
            delta[res] = ratio * rate
    g = eff.get("global_ratio", 0.0)
    if g and lam:
        for res in sorted(lam):
            if lam[res] <= 0:
                continue
            rate = A.res_rate(snap, res)
            if rate > 0:
                delta[res] = delta.get(res, 0.0) + g * rate
    return delta


def policy_value(snap: dict, policy: dict, lam: dict[str, float],
                 horizon: float) -> float:
    """PolicyValue in Ziel-Sekunden: λ-bewerteter Ratengewinn über den
    Restplan-Horizont minus λ-bewertete Kaufkosten (Spec 13.4 / 10.2).
    Ohne Effekt-Referenz oder λ-Daten: 0 (kein Wert behauptbar).
    Unratable Policies (#37): exakt 0.0 — weder Nutzen noch Malus wird
    behauptet, die I-07-Prüfung entscheidet über die Gruppe."""
    eff = POLICY_EFFECTS.get(policy["name"])
    if eff and eff.get("unratable"):
        return 0.0
    delta = _rate_delta(snap, policy["name"], lam or {})
    benefit = shadow.benefit_time(delta, lam or {}, horizon)
    cost = shadow.cost_time(policy.get("prices") or [], lam or {})
    return benefit - cost


def _alternative_stub(name: str) -> dict:
    """Pseudo-Policy für Alternativen/Nachfolger, die der Snapshot (noch)
    nicht führt — Referenz-Preisvektor aus science.js, Effekte aus der
    Referenztabelle."""
    prices = POLICY_REF_PRICES.get(name) or {}
    return {"name": name,
            "prices": [{"name": res, "val": val}
                       for res, val in sorted(prices.items())]}


# ------------------------------------------------- Zweig-Bewertung (13.4)

# BFS-Tiefe der Zweig-Bewertung: die Unlock-Ketten der Referenzversion sind
# höchstens 3 Stufen tief (authocracy → socialism → scientificCommunism).
BRANCH_DEPTH_MAX = 3


def _exclusivity_groups(names: list[str]) -> list[list[str]]:
    """Exklusivitätsgruppen einer Namensmenge: Zusammenhangskomponenten der
    blocks-Relation (POLICY_REF_BLOCKS) — nur EIN Mitglied je Gruppe ist
    kaufbar. Deterministisch: Gruppen und Mitglieder sortiert."""
    names = sorted(set(names))
    parent = {n: n for n in names}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for n in names:
        for b in POLICY_REF_BLOCKS.get(n, ()):
            if b in parent:
                ra, rb = find(n), find(b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(find(n), []).append(n)
    return [groups[k] for k in sorted(groups)]


def branch_value(snap: dict, policy: dict, lam: dict[str, float],
                 horizon: float) -> float:
    """Zweigwert (#37, Kombinationsbewertung 13.4): eigener PolicyValue
    plus die per unlocks.policies erreichbaren Nachfolger (BFS, Tiefe ≤
    BRANCH_DEPTH_MAX). Je Frontier-Gruppe (blocks-Zusammenhangskomponente)
    zählt das MAXIMUM der Mitglieder (nur eines ist kaufbar), Beitrag
    max(0, ·) × 1/(1+Tiefe) — harmonischer Diskont wie shadow.path_weight:
    Nachfolger kommen später im Restplan, ein geometrischer Zeitdiskont
    über den Horizont würde sie totentwerten. Bereits erforschte oder
    blockierte Nachfolger tragen 0 (kein Zusatzwert des Zweigs mehr);
    gemeinsame Nachfolger konkurrierender Zweige liefern beiden Seiten
    denselben Beitrag und neutralisieren sich im I-07-Vergleich."""
    name = policy["name"]
    total = policy_value(snap, policy, lam, horizon)
    by_name = {p["name"]: p for p in snap.get("policies") or []}
    seen = {name}
    frontier = [name]
    for depth in range(1, BRANCH_DEPTH_MAX + 1):
        succ: list[str] = []
        for n in frontier:
            for s in POLICY_UNLOCKS.get(n, ()):
                if s not in seen:
                    seen.add(s)
                    succ.append(s)
        if not succ:
            break
        for group in _exclusivity_groups(succ):
            best = 0.0   # implizit max(0, ·): negative Zweige zwingt niemand
            for s in group:
                p = by_name.get(s)
                if p is not None and (p.get("researched") or p.get("blocked")):
                    continue
                val = policy_value(snap, p if p is not None
                                   else _alternative_stub(s), lam, horizon)
                best = max(best, val)
            total += best / (1.0 + depth)
        frontier = succ
    return total


def i07_check(snap: dict, policy: dict, lam: dict[str, float],
              horizon: float) -> tuple[bool, dict[str, float]]:
    """Invariante I-07: Zweigwert(gewählt) ≥ Zweigwert(Alternative) für
    JEDE per `blocks` ausgeschlossene Alternative, beide über denselben
    Horizont (seit #37 Zweig- statt Einzelwerte — eine schwache Policy
    mit starkem Unlock-Zweig darf gewinnen). Unbekannte Alternativen
    (weder Snapshot noch Referenztabelle) ⇒ konservativ nicht zulässig.
    Rückgabe: (zulässig, {alt: zweigwert})."""
    own = branch_value(snap, policy, lam, horizon)
    by_name = {p["name"]: p for p in snap.get("policies") or []}
    alt_values: dict[str, float] = {}
    ok = True
    for alt_name in sorted(policy.get("blocks") or []):
        alt = by_name.get(alt_name)
        if alt is None:
            if alt_name not in POLICY_EFFECTS and alt_name not in POLICY_REF_PRICES:
                return False, alt_values   # nicht bewertbar → I-07 verletzt
            alt = _alternative_stub(alt_name)
        val = branch_value(snap, alt, lam, horizon)
        alt_values[alt_name] = val
        if own + EPS < val:
            ok = False
    return ok, alt_values


def best_policy(snap: dict, run_type: str, lam: dict[str, float],
                horizon: float, run_plan: dict | None = None
                ) -> tuple[dict, float, dict[str, float]] | None:
    """Beste zulässige Policy für den aktuellen Kontext (Run-Typ).

    Suchraum = 13.4-Prior des Run-Typs ∪ exklusive Gegenstücke der
    Prior-Kandidaten (I-07: die bewertete Alternative darf gewinnen).
    Zulässig: unlocked, nicht researched, nicht blocked, bezahlbar,
    Zweigwert > 0 UND I-07 bestanden (#37). Horizont: die projizierte
    Restzeit des Run-Plans (run_plan["restzeitS"], meta.determine_run_plan),
    falls endlich > 0 — sonst der übergebene Horizont. Rückgabe:
    (policy, zweigwert, alternativen-Zweigwerte) — deterministisch
    (Wert absteigend, Name)."""
    policies = snap.get("policies")
    if not policies:
        return None
    rz = (run_plan or {}).get("restzeitS")
    if isinstance(rz, (int, float)) and math.isfinite(rz) and rz > 0:
        horizon = float(rz)
    by_name = {p["name"]: p for p in policies}
    prior = POLICY_PRIOR.get(run_type, DEFAULT_PRIOR)
    names: set[str] = set(prior)
    for n in prior:
        p = by_name.get(n)
        if p:
            names.update(p.get("blocks") or [])
    scored: list[tuple[float, str, dict, dict[str, float]]] = []
    for name in sorted(names):
        p = by_name.get(name)
        if p is None or p.get("researched") or p.get("blocked") \
                or not p.get("unlocked"):
            continue
        if not A.affordable(snap, p.get("prices") or []):
            continue
        value = branch_value(snap, p, lam, horizon)
        if value <= 0:
            continue
        ok, alt_values = i07_check(snap, p, lam, horizon)
        if not ok:
            continue
        scored.append((value, name, p, alt_values))
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], t[1]))
    value, _, pol, alt_values = scored[0]
    return pol, value, alt_values
