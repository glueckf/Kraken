// Bootstrap + DOM wiring. Framework-free: on every state change we re-render the
// panel sections and the reef; interactions use event delegation on stable
// container elements (which persist across innerHTML updates).

import { AppState } from "./state";
import { computeLayout, renderReef, type Layout, type ReefView } from "./reef";
import { renderQueryBar, renderTray, renderScorecard } from "./panel";
import { modalHtml } from "./modal";

const $ = (id: string) => document.getElementById(id)!;

const state = new AppState();
let layout: Layout | null = null;
let layoutFor: string | null = null;

function reefView(): ReefView {
  return {
    placement: state.placement,
    activeSubquery: state.activeSubquery,
    sourceNodes: state.activeSourceNodes,
    reveal: state.reveal && state.scenario ? state.scenario.strategies.kraken.placement : null,
  };
}

function render(): void {
  const status = $("status");
  if (state.error) {
    $("reef").innerHTML = `<div class="fatal">${state.error}</div>`;
    return;
  }
  if (!state.scenario) {
    $("reef").innerHTML = `<div class="loading">Loading…</div>`;
    return;
  }
  if (layoutFor !== state.scenario.scenario_id) {
    layout = computeLayout(state.scenario);
    layoutFor = state.scenario.scenario_id;
  }
  $("reef").innerHTML = renderReef(state.scenario, layout!, state.subMeta, reefView());
  $("queryBar").innerHTML = renderQueryBar(state);
  $("tray").innerHTML = renderTray(state);
  $("scorecard").innerHTML = renderScorecard(state);
  status.textContent = state.scenario.title;
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
  });

  // modal
  $("infoBtn").addEventListener("click", openModal);
  $("modal").addEventListener("click", (e) => {
    if (e.target === $("modal") || closestAttr(e.target, "data-action") === "close-modal") closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if ((e as KeyboardEvent).key === "Escape") closeModal();
  });
}

function trayActivate(target: EventTarget | null): void {
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
wire();
render();
state.init();
