// Minimal, dependency-free i18n for a booth audience expected to be both
// German- and English-speaking (the presenter bridges gaps live, so this
// doesn't need to be exhaustive -- just cover the UI chrome a visitor reads
// unassisted). No build-time extraction tooling: this is a ~50-string app,
// not worth the overhead. Defaults to the browser's own language, sticks to
// whatever the visitor last picked (so switching topology/query doesn't
// reset it), and every consumer re-renders on change via onLangChange.

export type Lang = "en" | "de";

const STORAGE_KEY = "kraken-lang";

function detectLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "de") return saved;
  } catch {
    // private browsing / storage disabled -- fall through to browser language
  }
  return navigator.language.toLowerCase().startsWith("de") ? "de" : "en";
}

let current: Lang = detectLang();
const listeners: Array<() => void> = [];

export function getLang(): Lang {
  return current;
}

export function setLang(lang: Lang): void {
  if (lang === current) return;
  current = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // ignore -- language just won't stick across reloads
  }
  listeners.forEach((fn) => fn());
}

export function onLangChange(fn: () => void): void {
  listeners.push(fn);
}

interface Strings {
  // ---- static chrome (index.html, set via DOM on load + lang change) ----
  pageTitle: string;
  metaDescription: string;
  tagline: string;
  aboutBtn: string;
  langToggleLabel: string;
  langToggleAria: string;
  networkRegionAria: string;

  // ---- top-level states ----
  loading: string;
  loadScenariosFailed: (detail: string) => string;
  loadScenarioFailed: (id: string, detail: string) => string;

  // ---- topology / query bar ----
  topologyTitle: (label: string, nodes: number) => string;
  queryTitle: (title: string, subqueries: string) => string;
  subqueries: (n: number) => string;

  // ---- tray ----
  subqueriesToPlace: string;
  tapSubqueryThenNode: string;
  selectedNowTapNode: (name: string) => string;
  stillNeedPushPull: (names: string) => string;
  allSubqueriesPlaced: string;
  autoBadge: string;
  needs: string;

  // ---- push/pull row ----
  ppLabel: string;
  roleHere: string;
  rolePush: string;
  rolePull: string;
  alreadyHere: string;
  rateUnknown: string;
  pushAllTitle: string;
  pullAllTitle: string;
  pushAllLabel: string;
  pullAllLabel: string;

  // ---- stage picker ----
  stageTitleFor: (stage: string) => string;
  stageRowTitle: string;
  stageLabel: (enLabel: string) => string;

  // ---- scorecard: empty / scoring ----
  choosePushPullFor: (n: number) => string;
  placeAllToScore: (subqueries: string) => string;
  scEmptySub: string;
  scoringTitle: string;
  scoringSub: string;

  // ---- scorecard: results ----
  verdictMatched: string;
  verdictMid: (n: number) => string;
  modePushPull: string;
  modeEstimate: string;
  tupleLabel: string;
  latencyLabel: string;
  krakenScoreLabel: string;
  youLabel: string;
  sameAsKraken: string;
  vsKraken: (sign: string, v: string) => string;
  leaderboardTitle: string;
  leaderboardHint: string;
  legendHint: string;
  legendPush: string;
  legendPull: string;
  revealPlan: string;
  hidePlan: string;
  tryAgain: string;

  // ---- reef aria labels ----
  cloudSink: string;
  watchtower: (id: number) => string;
  sourceNode: (id: number) => string;
  holdsSubqueries: (n: number) => string;
  producesEvents: (letters: string) => string;
  topologyAria: string;
  subqueryChipAria: (tag: string, node: number) => string;

  // ---- placement errors ----
  unknownNode: (node: number) => string;
  unreachableSource: (node: number, dep: string) => string;
  noPathFrom: (node: number, dep: string) => string;
  autoPlacedAtCloud: (dep: string) => string;

  // ---- modal ----
  modalTitle: string;
  modalLede: string;
  yourTask: string;
  taskStep1: string;
  taskStep2: string;
  taskStep3: string;
  taskStep4: string;
  whyJoint: string;
  jointBody: string;
  headlineResults: string;
  result1: string;
  result2: string;
  result3: string;
  aboutScoring: string;
  scoringFine: string;
  linkPaper: string;
  linkRepo: string;
}

const EN: Strings = {
  pageTitle: "Kraken — subquery placement demo",
  metaDescription:
    "Interactive demo of the Kraken cloud-fog subquery placement engine for distributed complex event processing.",
  tagline: "place the subqueries · can you beat the engine?",
  aboutBtn: "About this demo",
  langToggleLabel: "DE",
  langToggleAria: "Switch to German",
  networkRegionAria: "Fog-cloud network",

  loading: "Loading…",
  loadScenariosFailed: (detail) => `Failed to load scenarios: ${detail}`,
  loadScenarioFailed: (id, detail) => `Failed to load scenario ${id}: ${detail}`,

  topologyTitle: (label, nodes) => `${label} — ${nodes} nodes`,
  queryTitle: (title, subqueries) => `${title} — ${subqueries}`,
  subqueries: (n) => `${n} subquer${n === 1 ? "y" : "ies"}`,

  subqueriesToPlace: "Subqueries to place",
  tapSubqueryThenNode: "Tap a subquery, then tap a node.",
  selectedNowTapNode: (name) => `Selected ${name} — now tap a node.`,
  stillNeedPushPull: (names) => `Still need a push/pull call for ${names}.`,
  allSubqueriesPlaced: "All subqueries placed.",
  autoBadge: "auto",
  needs: "needs",

  ppLabel: "push",
  roleHere: "here",
  rolePush: "PUSH",
  rolePull: "pull",
  alreadyHere: "is already at this node",
  rateUnknown: "rate unknown",
  pushAllTitle: "Push every input, pull nothing",
  pullAllTitle: "Pull every input, push nothing",
  pushAllLabel: "push all",
  pullAllLabel: "pull all",

  stageTitleFor: (stage) => `Kraken optimised for ${stage}`,
  stageRowTitle: "How Kraken balances cost (fewer messages) vs. latency (speed)",
  stageLabel: (enLabel) => enLabel,

  choosePushPullFor: (n) => `Choose push or pull for ${n} more subquer${n > 1 ? "ies" : "y"} to score your plan`,
  placeAllToScore: (subqueries) => `Place all ${subqueries} to score your plan`,
  scEmptySub:
    "You choose where each subquery runs, and — for push-pull scoring — which stream it pushes. We compute the network cost and latency, then pit it against Kraken and four baselines.",
  scoringTitle: "Kraken is crunching the numbers…",
  scoringSub: "Optimising push/pull for your placement.",

  verdictMatched: "You matched Kraken.",
  verdictMid: (n) => `You beat ${n} of 4 baselines — Kraken still wins.`,
  modePushPull: "push-pull optimised",
  modeEstimate: "all-push estimate — no live scoring available",
  tupleLabel: "Tuples moved",
  latencyLabel: "Latency (hops)",
  krakenScoreLabel: "Kraken score",
  youLabel: "You",
  sameAsKraken: "same as Kraken",
  vsKraken: (sign, v) => `${sign}${v} vs Kraken`,
  leaderboardTitle: "Leaderboard",
  leaderboardHint: "lower is better — cost & latency, balanced",
  legendHint: "edge color = event type ·",
  legendPush: "push",
  legendPull: "pull",
  revealPlan: "Reveal Kraken's plan",
  hidePlan: "Hide Kraken's plan",
  tryAgain: "Try again",

  cloudSink: "König Cloud, the sink",
  watchtower: (id) => `Watchtower ${id}`,
  sourceNode: (id) => `Reef source node ${id}`,
  holdsSubqueries: (n) => `, holds ${n} subquer${n === 1 ? "y" : "ies"}`,
  producesEvents: (letters) => `, produces ${letters}`,
  topologyAria: "Fog-cloud topology; tap a node to place the selected subquery",
  subqueryChipAria: (tag, node) => `Subquery ${tag} on node ${node}, click to move`,

  unknownNode: (node) => `Unknown node n${node}.`,
  unreachableSource: (node, dep) =>
    `n${node} doesn't reach every source of ${dep} — a subquery needs the complete stream, and events only flow upward from where they're produced. Check which nodes sit downstream of n${node}.`,
  noPathFrom: (node, dep) =>
    `n${node} has no path from ${dep} — a subquery needs to sit above (or at) all of its inputs in the network.`,
  autoPlacedAtCloud: (dep) =>
    `Placed at König Cloud automatically — its input ${dep} is already there, and no other node can reach it.`,

  modalTitle: "Kraken — subquery placement",
  modalLede:
    'A hands-on view of <b>Kraken</b>, a placement engine for distributed Complex Event Processing on <b>fog-cloud</b> networks. Continuous queries over geo-distributed event streams run as subqueries that must be placed on nodes, and each subquery must acquire its inputs — either <b>all-push</b> (forward every tuple upward) or <b>push-pull</b> (push the low-rate stream, then pull only the matches). Placement and communication are tightly coupled.',
  yourTask: "Your task",
  taskStep1: "Pick a query (the animal tokens).",
  taskStep2: "Place <b>every</b> subquery onto a node — cloud, fog, or a source.",
  taskStep3:
    "We compute the <b>tuples transmitted</b> and the <b>latency</b> of your plan, and rank it against four baselines and Kraken on a balanced (cost + latency) score.",
  taskStep4:
    "Subqueries near their sources move fewer tuples; subqueries near the cloud shorten the path to the sink. Find the balance the Kraken finds.",
  whyJoint: "Why joint optimisation wins",
  jointBody:
    'Existing planners decide placement and communication <i>in stages</i> — fix the placement first, then optimise input acquisition. Committing to a placement early rules out globally better plans. Kraken instead searches over <b>atomic deploy decisions</b>, weighing <i>both</i> communication schemes as it places each subquery. In the paper\'s factory example (a windowed join <span class="mono">[A ∘ B]</span>), all-push moves <b>3010</b> tuples, a staged planner <b>2120</b>, and Kraken <b>360</b> — a plan unreachable when the two decisions are made separately.',
  headlineResults: "Headline results",
  result1: "<b>~3×</b> fewer tuples transmitted vs the sequential baseline (median).",
  result2: "<b>14%</b> lower median transmission latency.",
  result3: "<b>7×</b> faster planning time.",
  aboutScoring: "About the scoring",
  scoringFine:
    'Your instant score uses the exact all-push cost model (computed in-browser via Rust/WASM). When a scoring service is available, it is refined with the real push-pull optimiser for an apples-to-apples number. The combined "Kraken score" normalises tuples and latency against this scenario\'s baselines (0 = as good as the best); Kraken co-optimises communication, which by-hand placement cannot.',
  linkPaper: "Paper (DEBS '26, DOI)",
  linkRepo: "Code repository",
};

const DE: Strings = {
  pageTitle: "Kraken — Teilabfrage-Platzierung Demo",
  metaDescription:
    "Interaktive Demo der Kraken-Engine zur Platzierung von Teilabfragen in Fog-Cloud-Netzwerken für verteilte komplexe Ereignisverarbeitung.",
  tagline: "platziere die Teilabfragen · schlägst du die Engine?",
  aboutBtn: "Über diese Demo",
  langToggleLabel: "EN",
  langToggleAria: "Auf Englisch umschalten",
  networkRegionAria: "Fog-Cloud-Netzwerk",

  loading: "Wird geladen …",
  loadScenariosFailed: (detail) => `Szenarien konnten nicht geladen werden: ${detail}`,
  loadScenarioFailed: (id, detail) => `Szenario ${id} konnte nicht geladen werden: ${detail}`,

  topologyTitle: (label, nodes) => `${label} — ${nodes} Knoten`,
  queryTitle: (title, subqueries) => `${title} — ${subqueries}`,
  subqueries: (n) => `${n} Teilabfrage${n === 1 ? "" : "n"}`,

  subqueriesToPlace: "Teilabfragen zum Platzieren",
  tapSubqueryThenNode: "Tippe auf eine Teilabfrage, dann auf einen Knoten.",
  selectedNowTapNode: (name) => `${name} ausgewählt — jetzt auf einen Knoten tippen.`,
  stillNeedPushPull: (names) => `Für ${names} fehlt noch eine Push/Pull-Entscheidung.`,
  allSubqueriesPlaced: "Alle Teilabfragen platziert.",
  autoBadge: "auto",
  needs: "braucht",

  ppLabel: "push",
  roleHere: "hier",
  rolePush: "PUSH",
  rolePull: "pull",
  alreadyHere: "ist bereits an diesem Knoten",
  rateUnknown: "Rate unbekannt",
  pushAllTitle: "Alles pushen, nichts pullen",
  pullAllTitle: "Alles pullen, nichts pushen",
  pushAllLabel: "alles pushen",
  pullAllLabel: "alles pullen",

  stageTitleFor: (stage) => `Kraken optimiert für ${stage}`,
  stageRowTitle: "Wie Kraken Kosten (weniger Nachrichten) gegen Latenz (Geschwindigkeit) abwägt",
  stageLabel: (enLabel) => STAGE_LABEL_DE[enLabel.toLowerCase()] ?? enLabel,

  choosePushPullFor: (n) =>
    `Wähle Push oder Pull für ${n} weitere Teilabfrage${n > 1 ? "n" : ""}, um deinen Plan zu bewerten`,
  placeAllToScore: (subqueries) => `Platziere alle ${subqueries}, um deinen Plan zu bewerten`,
  scEmptySub:
    "Du entscheidest, wo jede Teilabfrage läuft und — für die Push-Pull-Bewertung — welchen Stream sie pusht. Wir berechnen die Netzwerkkosten und die Latenz und vergleichen sie mit Kraken und vier weiteren Baselines.",
  scoringTitle: "Kraken knackt die Zahlen …",
  scoringSub: "Optimiert Push/Pull für deine Platzierung.",

  verdictMatched: "Du hast mit Kraken gleichgezogen.",
  verdictMid: (n) => `Du schlägst ${n} von 4 Baselines — Kraken gewinnt noch.`,
  modePushPull: "Push-Pull-optimiert",
  modeEstimate: "All-Push-Schätzung — keine Live-Bewertung verfügbar",
  tupleLabel: "Übertragene Tupel",
  latencyLabel: "Latenz (Hops)",
  krakenScoreLabel: "Kraken-Wert",
  youLabel: "Du",
  sameAsKraken: "wie Kraken",
  vsKraken: (sign, v) => `${sign}${v} ggü. Kraken`,
  leaderboardTitle: "Rangliste",
  leaderboardHint: "niedriger ist besser — Kosten & Latenz, ausgewogen",
  legendHint: "Kantenfarbe = Ereignistyp ·",
  legendPush: "push",
  legendPull: "pull",
  revealPlan: "Kraken-Plan anzeigen",
  hidePlan: "Kraken-Plan verbergen",
  tryAgain: "Nochmal versuchen",

  cloudSink: "König Cloud, das Ziel",
  watchtower: (id) => `Wachturm ${id}`,
  sourceNode: (id) => `Riff-Quellknoten ${id}`,
  holdsSubqueries: (n) => `, enthält ${n} Teilabfrage${n === 1 ? "" : "n"}`,
  producesEvents: (letters) => `, erzeugt ${letters}`,
  topologyAria: "Fog-Cloud-Topologie; auf einen Knoten tippen, um die ausgewählte Teilabfrage zu platzieren",
  subqueryChipAria: (tag, node) => `Teilabfrage ${tag} auf Knoten ${node}, klicken zum Verschieben`,

  unknownNode: (node) => `Unbekannter Knoten n${node}.`,
  unreachableSource: (node, dep) =>
    `n${node} erreicht nicht jede Quelle von ${dep} — eine Teilabfrage braucht den vollständigen Stream, und Ereignisse fließen nur aufwärts von ihrem Ursprung. Prüfe, welche Knoten unterhalb von n${node} liegen.`,
  noPathFrom: (node, dep) =>
    `n${node} hat keinen Pfad von ${dep} — eine Teilabfrage muss über (oder auf) all ihren Eingaben im Netzwerk sitzen.`,
  autoPlacedAtCloud: (dep) =>
    `Automatisch an König Cloud platziert — ihre Eingabe ${dep} ist bereits dort, und kein anderer Knoten kann sie erreichen.`,

  modalTitle: "Kraken — Platzierung von Teilabfragen",
  modalLede:
    'Ein praktischer Einblick in <b>Kraken</b>, eine Platzierungs-Engine für verteilte komplexe Ereignisverarbeitung in <b>Fog-Cloud</b>-Netzwerken. Kontinuierliche Anfragen über geo-verteilte Ereignisströme laufen als Teilabfragen, die auf Knoten platziert werden müssen, und jede Teilabfrage muss ihre Eingaben beschaffen — entweder <b>All-Push</b> (jedes Tupel aufwärts weiterleiten) oder <b>Push-Pull</b> (den ratenarmen Stream pushen, dann nur die Treffer pullen). Platzierung und Kommunikation sind eng gekoppelt.',
  yourTask: "Deine Aufgabe",
  taskStep1: "Wähle eine Anfrage (die Tier-Symbole).",
  taskStep2: "Platziere <b>jede</b> Teilabfrage auf einem Knoten — Cloud, Fog oder eine Quelle.",
  taskStep3:
    "Wir berechnen die <b>übertragenen Tupel</b> und die <b>Latenz</b> deines Plans und vergleichen ihn mit vier Baselines und Kraken anhand eines ausgewogenen (Kosten + Latenz) Werts.",
  taskStep4:
    "Teilabfragen nahe ihren Quellen bewegen weniger Tupel; Teilabfragen nahe der Cloud verkürzen den Weg zur Senke. Finde die Balance, die Kraken findet.",
  whyJoint: "Warum gemeinsame Optimierung gewinnt",
  jointBody:
    'Bestehende Planer entscheiden Platzierung und Kommunikation <i>in Stufen</i> — zuerst die Platzierung festlegen, dann die Eingabebeschaffung optimieren. Eine frühe Festlegung schließt global bessere Pläne aus. Kraken sucht stattdessen über <b>atomare Einsatzentscheidungen</b> und wägt <i>beide</i> Kommunikationsschemata ab, während es jede Teilabfrage platziert. Im Fabrikbeispiel des Papers (ein Fenster-Join <span class="mono">[A ∘ B]</span>) bewegt All-Push <b>3010</b> Tupel, ein gestufter Planer <b>2120</b>, und Kraken <b>360</b> — ein Plan, der unerreichbar ist, wenn beide Entscheidungen getrennt getroffen werden.',
  headlineResults: "Kernergebnisse",
  result1: "<b>~3×</b> weniger übertragene Tupel ggü. der sequentiellen Baseline (Median).",
  result2: "<b>14%</b> niedrigere mediane Übertragungslatenz.",
  result3: "<b>7×</b> schnellere Planungszeit.",
  aboutScoring: "Über die Bewertung",
  scoringFine:
    'Dein Sofort-Wert nutzt das exakte All-Push-Kostenmodell (im Browser via Rust/WASM berechnet). Sobald ein Bewertungsdienst verfügbar ist, wird er mit dem echten Push-Pull-Optimierer für einen fairen Vergleich verfeinert. Der kombinierte "Kraken-Wert" normalisiert Tupel und Latenz gegen die Baselines dieses Szenarios (0 = so gut wie die beste); Kraken optimiert Kommunikation mit, was eine manuelle Platzierung nicht kann.',
  linkPaper: "Paper (DEBS '26, DOI)",
  linkRepo: "Code-Repository",
};

// Stage labels come from exported scenario data ("Fast"/"Balanced"/"Cheap",
// baked in at export time by export_scenario.py) -- translate by English
// label rather than hardcoding stage identity here, same pattern as
// panel.ts's own STAGE_ICON map.
const STAGE_LABEL_DE: Record<string, string> = {
  fast: "Schnell",
  balanced: "Ausgewogen",
  cheap: "Günstig",
};

export function t(): Strings {
  return current === "de" ? DE : EN;
}
