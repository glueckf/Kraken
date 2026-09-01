# Kraken Demo — Backlog

Internal working list, not a public issue tracker. Functional pieces first —
gamification is a polish pass once the demo actually demonstrates what Kraken
does.

## Functional (current priority)

1. **Extend communication.** The demo only scores the client-side all-push
   estimate today (`window.KRAKEN_BACKEND` is empty in
   [index.html](web/index.html), see `backendConfigured()` in
   [state.ts](web/src/state.ts)). No push-pull backend is wired up, so the
   demo can't show Kraken's actual communication-strategy co-optimization —
   only placement.
2. **Simplify the query representation** for a non-technical audience.
   Currently queries are shown as raw expressions (`SEQ(A, B, C)`), which
   reads as programming syntax rather than "spot the shark alarm."
3. **Let the user choose the network size** instead of picking from fixed
   pre-generated scenarios.
4. **Test the visualization at different network sizes** — confirm the
   layout (island, watchtowers, coral pods) still reads cleanly as node count
   and layer depth grow, not just at the current fixed topology.

## Gamification (later — once the above works)

- Weave the "Hai-Alarm" fairy-tale framing into the actual UI copy (query
  picker, task description, info modal), not just the spoken talk — e.g.
  frame query selection as "which alarm are you hunting" rather than an
  abstract `SEQ(...)` expression.
- Add a tangible reward moment (short animation/sound) for beating Kraken —
  a bare score delta (0.342 vs 0.298) doesn't land emotionally for a lay
  audience.
- Open question: accessibility for a diverse audience — German vs English UI
  copy, colorblind-safe palette check, mobile usability for a slam/QR-code
  crowd.
