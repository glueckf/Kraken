// Optional push-pull refinement client. The core demo never depends on this:
// if no backend is configured or a call fails/times out, we return null and the
// UI keeps the instant client-side all-push estimate (graceful degradation).

import type { Placement } from "./types";

export interface PushPullResult {
  cost: number;
  latency: number;
  per_placement?: Record<string, { node: number; strategy: string; cost: number }>;
}

// Configure via window.KRAKEN_BACKEND (set in index.html or injected at deploy).
// Empty/undefined => client-only mode.
function backendBase(): string | null {
  const w = window as unknown as { KRAKEN_BACKEND?: string };
  const b = (w.KRAKEN_BACKEND || "").trim();
  return b ? b.replace(/\/$/, "") : null;
}

export function backendConfigured(): boolean {
  return backendBase() !== null;
}

export async function refinePushPull(
  scenarioId: string,
  placement: Placement,
  pushChoice: Record<string, string> = {},
  timeoutMs = 4000,
): Promise<PushPullResult | null> {
  const base = backendBase();
  if (!base) return null;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${base}/score`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario_id: scenarioId, placement, push_choice: pushChoice }),
      signal: ctrl.signal,
    });
    if (!res.ok) return null;
    const data = (await res.json()) as PushPullResult;
    if (typeof data.cost !== "number" || typeof data.latency !== "number") return null;
    return data;
  } catch {
    return null; // network error, timeout, CORS, backend down -> degrade gracefully
  } finally {
    clearTimeout(t);
  }
}
