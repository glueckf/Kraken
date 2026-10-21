// Bootstrap + DOM wiring. Framework-free: on every state change we re-render the
// panel sections and the reef; interactions use event delegation on stable
// container elements (which persist across innerHTML updates).

import { AppState, type OfficialScore } from "./state";
import { computeLayout, renderReef, type Layout, type ReefView } from "./reef";
import { renderTopologyBar, renderQueryBar, renderTray, renderScorecard, playerBeatsKraken } from "./panel";
import { modalHtml } from "./modal";
import { getLang, setLang, onLangChange, t } from "./i18n";
import type { Scenario } from "./types";

const $ = (id: string) => document.getElementById(id)!;

const state = new AppState();
let layout: Layout | null = null;
let layoutFor: Scenario | null = null;
// Identity of the last `state.official` we rendered, so the win-celebration
// bubble burst fires exactly once per freshly-arrived win — not again on an
// unrelated re-render (e.g. toggling reveal) while the same win is still on
// screen. `rescore()` always creates a brand-new object when a result
// resolves, so identity alone is a reliable "this is new" signal.
let lastOfficial: OfficialScore | null = null;

function reefView(): ReefView {
  return {
    placement: state.placement,
    activeSubquery: state.activeSubquery,
    sourceNodes: state.activeSourceNodes,
    reveal: state.reveal ? state.currentStage?.per_placement ?? null : null,
  };
}

/** Chrome that only depends on the current language, not app state (page
 * title, tagline, button labels) -- applied once at startup and again on
 * every language switch, not on every render (nothing here changes with
 * placement/scoring). */
function applyStaticI18n(): void {
  document.title = t().pageTitle;
  document.querySelector('meta[name="description"]')?.setAttribute("content", t().metaDescription);
  document.querySelector(".tag")!.textContent = t().tagline;
  const langBtn = $("langBtn");
  langBtn.textContent = t().langToggleLabel;
  langBtn.setAttribute("aria-label", t().langToggleAria);
  $("infoBtn").setAttribute("aria-label", t().aboutBtn);
  $("reefWrap").setAttribute("aria-label", t().networkRegionAria);
}

function render(): void {
  const status = $("status");
  if (state.error) {
    $("reef").innerHTML = `<div class="fatal">${state.error}</div>`;
    return;
  }
  if (!state.scenario) {
    $("reef").innerHTML = `<div class="loading">${t().loading}</div>`;
    return;
  }
  // Keyed on object identity, not scenario_id (not unique across topologies —
  // every size has its own "seq_abc") or a derived string (racy: loadScenario
  // emits once while still loading, before state.scenario has actually
  // swapped to the new data). A fresh scenario object only ever appears once
  // its fetch has fully resolved, so identity is exactly the right key.
  if (layoutFor !== state.scenario) {
    layout = computeLayout(state.scenario);
    layoutFor = state.scenario;
  }
  $("reef").innerHTML = renderReef(state.scenario, layout!, state.subMeta, reefView());
  $("topologyBar").innerHTML = renderTopologyBar(state);
  $("queryBar").innerHTML = renderQueryBar(state);
  $("tray").innerHTML = renderTray(state);
  $("scorecard").innerHTML = renderScorecard(state);
  status.textContent = state.scenario.title;

  if (state.official !== lastOfficial) {
    lastOfficial = state.official;
    if (state.official && playerBeatsKraken(state)) burstBubbles();
  }
}

const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)");

/** Win celebration: a short burst of bubbles rising from the Kraken-score
 * tile. Self-cleaning (removes its own overlay after the animation), and a
 * no-op under reduced motion rather than spawning motionless elements. */
function burstBubbles(): void {
  if (REDUCED_MOTION.matches) return;
  const tile = document.getElementById("krakenScoreTile");
  if (!tile) return;
  const burst = document.createElement("div");
  burst.className = "bubble-burst";
  const n = 12;
  for (let i = 0; i < n; i++) {
    const b = document.createElement("span");
    b.className = "bubble";
    b.style.setProperty("--bx", `${10 + Math.random() * 80}%`);
    b.style.setProperty("--bs", `${5 + Math.random() * 7}px`);
    b.style.setProperty("--dx", `${(Math.random() - 0.5) * 36}px`);
    b.style.setProperty("--bd", `${Math.random() * 0.35}s`);
    burst.appendChild(b);
  }
  tile.appendChild(burst);
  setTimeout(() => burst.remove(), 1500);
}

// ---- delegated interaction helpers ----
function closestAttr(target: EventTarget | null, attr: string): string | null {
  let el = target as HTMLElement | null;
  while (el && el !== document.body) {
    if (el.hasAttribute?.(attr)) return el.getAttribute(attr);
    el = el.parentElement;
  }
  return null;
}

function onReefActivate(target: EventTarget | null): void {
  const sub = closestAttr(target, "data-sub"); // a placed chip -> pick it up
  if (sub) {
    state.pickUp(decodeURIComponent(sub));
    return;
  }
  const node = closestAttr(target, "data-node");
  if (node != null) state.placeActiveAt(Number(node));
}

function wire(): void {
  $("topologyBar").addEventListener("click", (e) => {
    const id = closestAttr(e.target, "data-topology");
    if (id) state.selectTopology(id);
  });

  $("queryBar").addEventListener("click", (e) => {
    const id = closestAttr(e.target, "data-scenario");
    if (id) state.loadScenario(id);
  });

  $("tray").addEventListener("click", (e) => trayActivate(e.target));
  $("tray").addEventListener("keydown", (e) => {
    if ((e as KeyboardEvent).key === "Enter" || (e as KeyboardEvent).key === " ") {
      e.preventDefault();
      trayActivate(e.target);
    }
  });

  $("reef").addEventListener("click", (e) => onReefActivate(e.target));
  $("reef").addEventListener("keydown", (e) => {
    const k = (e as KeyboardEvent).key;
    if (k === "Enter" || k === " ") {
      e.preventDefault();
      onReefActivate(e.target);
    }
  });

  $("scorecard").addEventListener("click", (e) => {
    const action = closestAttr(e.target, "data-action");
    if (action === "reveal") state.toggleReveal();
    else if (action === "clear") state.clear();
    else if (action === "stage") {
      const idx = closestAttr(e.target, "data-stage");
      if (idx != null) state.setStage(Number(idx));
    }
  });

  // modal
  $("infoBtn").addEventListener("click", openModal);
  $("modal").addEventListener("click", (e) => {
    if (e.target === $("modal") || closestAttr(e.target, "data-action") === "close-modal") closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if ((e as KeyboardEvent).key === "Escape") closeModal();
  });

  $("langBtn").addEventListener("click", () => setLang(getLang() === "en" ? "de" : "en"));
}

function trayActivate(target: EventTarget | null): void {
  if (closestAttr(target, "data-pp-inert") != null) return; // "already here" badge, nothing to do
  const pushAll = closestAttr(target, "data-pushall");
  if (pushAll != null) {
    state.setAllPushChoice(decodeURIComponent(pushAll), true);
    return;
  }
  const pullAll = closestAttr(target, "data-pullall");
  if (pullAll != null) {
    state.setAllPushChoice(decodeURIComponent(pullAll), false);
    return;
  }
  const pp = closestAttr(target, "data-pp");
  if (pp) {
    const [subEnc, depEnc] = pp.split("::");
    state.setPushChoice(decodeURIComponent(subEnc), decodeURIComponent(depEnc));
    return;
  }
  const sub = closestAttr(target, "data-sub");
  if (!sub) return;
  const name = decodeURIComponent(sub);
  if (name in state.placement) state.pickUp(name);
  else state.selectSubquery(name);
}

function openModal(): void {
  const m = $("modal");
  m.innerHTML = modalHtml();
  m.hidden = false;
  (m.querySelector(".modal-close") as HTMLElement | null)?.focus();
}
function closeModal(): void {
  const m = $("modal");
  if (!m.hidden) {
    m.hidden = true;
    m.innerHTML = "";
  }
}

state.subscribe(render);
onLangChange(() => {
  applyStaticI18n();
  render();
  if (!$("modal").hidden) openModal(); // re-render its content in the new language
});
wire();
applyStaticI18n();
render();
state.init();
