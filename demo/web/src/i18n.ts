// Minimal, dependency-free i18n for a booth audience expected to be both
// German- and English-speaking (the presenter bridges gaps live, so this
// doesn't need to be exhaustive -- just cover the UI chrome a visitor reads
// unassisted). No build-time extraction tooling: this is a ~50-string app,
// not worth the overhead. Defaults to the browser's own language, sticks to
// whatever the visitor last picked (so switching topology/query doesn't
// reset it), and every consumer re-renders on change via onLangChange.

import type { CommScheme } from "./types";

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

  // ---- paper-example round ----
  paperCommTitle: (scheme: CommScheme) => string;
  /** Shown once per visit to the paper round, above its push/pull chips --
   * explains, in the same vocabulary the rate chips themselves use, why
   * pushing the rare stream and pulling the common one on demand is the one
   * combination worth trying. */
  paperRatesHint: string;
  dtTitle: (n: number, alpha: number) => string;
  dtNode: string;
  dtComm: string;
  dtOptTitle: string;
  dtKrakenMatches: string;
  dtKrakenDiffers: string;
  dtNote: string;

  // ---- stage picker ----
  stageTitleFor: (stage: string) => string;
  stageRowTitle: string;
  stageLabel: (enLabel: string) => string;

  // ---- scorecard: empty / scoring ----
  choosePushPullFor: (n: number) => string;
  placeAllToScore: (subqueries: string) => string;
  scEmptySub: string;
  confirmTitle: string;
  confirmSub: string;
  confirmBtn: string;
  scoringTitle: string;
  scoringSub: string;
  timerAria: string;
  /** `kraken`: the current stage's measured search time (KrakenStage.solve_seconds). */
  timerYouVsKraken: (time: string, kraken: number | undefined) => string;

  // ---- scorecard: results ----
  verdictMatched: string;
  verdictMid: (n: number, total: number) => string;
  modePushPull: string;
  modeTable: string;
  modeAllPushLocal: string;
  unscorableTitle: string;
  unscorableBody: string;
  svcTable: string;
  svcUp: string;
  svcUnknown: string;
  svcOff: string;
  svcDown: string;
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
  cloudName: string;
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

// Kraken's search time: whole milliseconds below a second, else seconds
// with one decimal.
function solveTime(seconds: number, decimal: "." | ","): string {
  if (seconds < 0.0005) return "< 1 ms";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  return `${seconds.toFixed(1).replace(".", decimal)} s`;
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

  paperCommTitle: (scheme) =>
    scheme === "all_push" ? "All-push"
    : scheme === "push_pull" ? "Push B, pull A"
    : "Push A, pull B",
  paperRatesHint: "B is 100x rarer than A — still worth pushing A fully, instead of just letting it be pulled when needed?",
  dtTitle: (n, alpha) => `All ${n} options, checked one by one (weight α = ${alpha})`,
  dtNode: "Node",
  dtComm: "Communication",
  dtOptTitle: "Best of all options (full enumeration)",
  dtKrakenMatches: "Kraken's plan (K) is the best option (★).",
  dtKrakenDiffers: "Kraken's greedy plan (K) is not the best option (★) here.",
  dtNote:
    "S = sequential planner: first picks the node that is best under all-push, then optimises communication there. F = α·(tuples, scaled 0–1) + (1−α)·(latency, scaled 0–1) over these options; lower is better.",

  stageTitleFor: (stage) => `Kraken optimised for ${stage}`,
  stageRowTitle: "How Kraken balances cost (fewer messages) vs. latency (speed)",
  stageLabel: (enLabel) => enLabel,

  choosePushPullFor: (n) => `Choose push or pull for ${n} more subquer${n > 1 ? "ies" : "y"} to score your plan`,
  placeAllToScore: (subqueries) => `Place all ${subqueries} to score your plan`,
  scEmptySub:
    "You choose where each subquery runs, and — for push-pull scoring — which stream it pushes. We compute the network cost and latency, then pit it against Kraken and the baselines.",
  confirmTitle: "Your plan is ready",
  confirmSub: "Confirm to lock in your placement and push/pull choices and see how you scored. You can still change anything until you confirm.",
  confirmBtn: "Confirm plan",
  scoringTitle: "Kraken is crunching the numbers…",
  scoringSub: "Optimising push/pull for your placement.",
  timerAria: "Your decision time, running from your first placement to Confirm plan",
  timerYouVsKraken: (time, kraken) =>
    kraken == null ? `You: ${time}` : `You: ${time} · Kraken: ${solveTime(kraken, ".")}`,

  verdictMatched: "You matched Kraken.",
  verdictMid: (n, total) => `You beat ${n} of ${total} baselines — Kraken still wins.`,
  modePushPull: "push-pull scored by the engine",
  modeTable: "exact — engine's precomputed table",
  modeAllPushLocal: "all-push model (in browser) — push-pull service offline",
  unscorableTitle: "Can't score this plan right now",
  unscorableBody:
    "Your plan pulls some inputs, and the push-pull scoring service is not reachable. An all-push number would ignore your pull choices, so we show none. Choose “push all” everywhere for an exact all-push score, or ask the booth team to start the service — the score appears by itself once it is back.",
  svcTable: "Scoring: exact values for every option, computed in advance — no service needed",
  svcUp: "Scoring: push-pull service connected",
  svcUnknown: "Scoring: checking push-pull service…",
  svcOff: "Scoring: no push-pull service configured — only all-push plans can be scored",
  svcDown: "Scoring: push-pull service not reachable — only all-push plans can be scored",
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

  cloudName: "King Cloud",
  cloudSink: "King Cloud, the sink",
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
    `Placed at King Cloud automatically — its input ${dep} is already there, and no other node can reach it.`,

  modalTitle: "Kraken — subquery placement",
  modalLede:
    'A hands-on view of <b>Kraken</b>, a placement engine for distributed Complex Event Processing on <b>fog-cloud</b> networks. Continuous queries over geo-distributed event streams run as subqueries that must be placed on nodes, and each subquery must acquire its inputs — either <b>all-push</b> (forward every tuple upward) or <b>push-pull</b> (push the low-rate stream, then pull only the matches). Placement and communication are tightly coupled.',
  yourTask: "Your task",
  taskStep1: "Pick a query (the animal tokens).",
  taskStep2: "Place <b>every</b> subquery onto a node — cloud, fog, or a source.",
  taskStep3:
    "We compute the <b>tuples transmitted</b> and the <b>latency</b> of your plan, and rank it against the baselines and Kraken on a balanced (cost + latency) score.",
  taskStep4:
    "Subqueries near their sources move fewer tuples; subqueries near the cloud shorten the path to the sink. Find the balance the Kraken finds.",
  whyJoint: "Why joint optimisation wins",
  jointBody:
    'Existing planners decide placement and communication <i>in stages</i> — fix the placement first, then optimise input acquisition. Committing to a placement early rules out globally better plans. Kraken instead searches over <b>atomic deploy decisions</b>, weighing <i>both</i> communication schemes as it places each subquery. In the paper\'s factory example (a windowed join <span class="mono">[A ∘ B]</span>), all-push moves <b>3010</b> tuples, a staged planner <b>2120</b>, and Kraken <b>360</b> — a plan unreachable when the two decisions are made separately. Play it yourself on <b>Kraken\'s Forge</b>.',
  headlineResults: "Headline results",
  result1: "<b>~3×</b> fewer tuples transmitted vs the sequential baseline (median).",
  result2: "<b>14%</b> lower median transmission latency.",
  result3: "<b>7×</b> faster planning time.",
  aboutScoring: "About the scoring",
  scoringFine:
    'Your plan is scored by Kraken\'s own cost model through the local push-pull scoring service, including your push/pull choices. Without that service only pure all-push plans are scored (by the same all-push model, in the browser); plans that pull are not scored at all rather than mis-scored. Kraken\'s Forge needs no service: every one of its options was computed in advance. The combined "Kraken score" normalises tuples and latency against this scenario\'s range (0 = as good as the best).',
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

  paperCommTitle: (scheme) =>
    scheme === "all_push" ? "All-Push"
    : scheme === "push_pull" ? "B pushen, A pullen"
    : "A pushen, B pullen",
  paperRatesHint: "B ist 100x seltener als A — lohnt es sich trotzdem, A komplett zu pushen, statt es nur bei Bedarf zu pullen?",
  dtTitle: (n, alpha) => `Alle ${n} Optionen einzeln geprüft (Gewicht α = ${alpha})`,
  dtNode: "Knoten",
  dtComm: "Kommunikation",
  dtOptTitle: "Beste aller Optionen (vollständige Enumeration)",
  dtKrakenMatches: "Krakens Plan (K) ist die beste Option (★).",
  dtKrakenDiffers: "Krakens Greedy-Plan (K) ist hier nicht die beste Option (★).",
  dtNote:
    "S = sequentieller Planer: wählt erst den unter All-Push besten Knoten und optimiert dann dort die Kommunikation. F = α·(Tupel, auf 0–1 skaliert) + (1−α)·(Latenz, auf 0–1 skaliert) über diese Optionen; niedriger ist besser.",

  stageTitleFor: (stage) => `Kraken optimiert für ${stage}`,
  stageRowTitle: "Wie Kraken Kosten (weniger Nachrichten) gegen Latenz (Geschwindigkeit) abwägt",
  stageLabel: (enLabel) => STAGE_LABEL_DE[enLabel.toLowerCase()] ?? enLabel,

  choosePushPullFor: (n) =>
    `Wähle Push oder Pull für ${n} weitere Teilabfrage${n > 1 ? "n" : ""}, um deinen Plan zu bewerten`,
  placeAllToScore: (subqueries) => `Platziere alle ${subqueries}, um deinen Plan zu bewerten`,
  scEmptySub:
    "Du entscheidest, wo jede Teilabfrage läuft und — für die Push-Pull-Bewertung — welchen Stream sie pusht. Wir berechnen die Netzwerkkosten und die Latenz und vergleichen sie mit Kraken und den Baselines.",
  confirmTitle: "Dein Plan ist fertig",
  confirmSub: "Bestätige, um Platzierung und Push/Pull-Wahl festzulegen und dein Ergebnis zu sehen. Bis dahin kannst du noch alles ändern.",
  confirmBtn: "Plan bestätigen",
  scoringTitle: "Kraken knackt die Zahlen …",
  scoringSub: "Optimiert Push/Pull für deine Platzierung.",
  timerAria: "Deine Entscheidungszeit, läuft von deiner ersten Platzierung bis Plan bestätigen",
  timerYouVsKraken: (time, kraken) =>
    kraken == null ? `Du: ${time}` : `Du: ${time} · Kraken: ${solveTime(kraken, ",")}`,

  verdictMatched: "Du hast mit Kraken gleichgezogen.",
  verdictMid: (n, total) => `Du schlägst ${n} von ${total} Baselines — Kraken gewinnt noch.`,
  modePushPull: "Push-Pull, von der Engine bewertet",
  modeTable: "exakt — vorberechnete Tabelle der Engine",
  modeAllPushLocal: "All-Push-Modell (im Browser) — Push-Pull-Dienst offline",
  unscorableTitle: "Dieser Plan kann gerade nicht bewertet werden",
  unscorableBody:
    "Dein Plan pullt Eingaben, und der Push-Pull-Bewertungsdienst ist nicht erreichbar. Eine All-Push-Zahl würde deine Pull-Wahl ignorieren, darum zeigen wir keine. Wähle überall „alles pushen“ für eine exakte All-Push-Bewertung, oder bitte das Standteam, den Dienst zu starten — die Bewertung erscheint dann von selbst.",
  svcTable: "Bewertung: exakte Werte für jede Option, vorab berechnet — kein Dienst nötig",
  svcUp: "Bewertung: Push-Pull-Dienst verbunden",
  svcUnknown: "Bewertung: Push-Pull-Dienst wird geprüft …",
  svcOff: "Bewertung: kein Push-Pull-Dienst konfiguriert — nur All-Push-Pläne bewertbar",
  svcDown: "Bewertung: Push-Pull-Dienst nicht erreichbar — nur All-Push-Pläne bewertbar",
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

  cloudName: "König Cloud",
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
    "Wir berechnen die <b>übertragenen Tupel</b> und die <b>Latenz</b> deines Plans und vergleichen ihn mit den Baselines und Kraken anhand eines ausgewogenen (Kosten + Latenz) Werts.",
  taskStep4:
    "Teilabfragen nahe ihren Quellen bewegen weniger Tupel; Teilabfragen nahe der Cloud verkürzen den Weg zur Senke. Finde die Balance, die Kraken findet.",
  whyJoint: "Warum gemeinsame Optimierung gewinnt",
  jointBody:
    'Bestehende Planer entscheiden Platzierung und Kommunikation <i>in Stufen</i> — zuerst die Platzierung festlegen, dann die Eingabebeschaffung optimieren. Eine frühe Festlegung schließt global bessere Pläne aus. Kraken sucht stattdessen über <b>atomare Einsatzentscheidungen</b> und wägt <i>beide</i> Kommunikationsschemata ab, während es jede Teilabfrage platziert. Im Fabrikbeispiel des Papers (ein Fenster-Join <span class="mono">[A ∘ B]</span>) bewegt All-Push <b>3010</b> Tupel, ein gestufter Planer <b>2120</b>, und Kraken <b>360</b> — ein Plan, der unerreichbar ist, wenn beide Entscheidungen getrennt getroffen werden. Spiel es selbst nach in <b>Krakens Schmiede</b>.',
  headlineResults: "Kernergebnisse",
  result1: "<b>~3×</b> weniger übertragene Tupel ggü. der sequentiellen Baseline (Median).",
  result2: "<b>14%</b> niedrigere mediane Übertragungslatenz.",
  result3: "<b>7×</b> schnellere Planungszeit.",
  aboutScoring: "Über die Bewertung",
  scoringFine:
    'Dein Plan wird über den lokalen Push-Pull-Bewertungsdienst mit Krakens eigenem Kostenmodell bewertet, inklusive deiner Push/Pull-Wahl. Ohne diesen Dienst werden nur reine All-Push-Pläne bewertet (mit demselben All-Push-Modell, im Browser); Pläne mit Pull werden dann gar nicht bewertet statt falsch. Krakens Schmiede braucht keinen Dienst: alle ihre Optionen sind vorab berechnet. Der kombinierte "Kraken-Wert" normalisiert Tupel und Latenz auf die Spannweite dieses Szenarios (0 = so gut wie die beste).',
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
