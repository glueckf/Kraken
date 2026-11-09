// One color per event type (A, B, C, …). Assignment is by letter position
// (A=0, B=1, …) so a given letter always has the same color across every
// scenario. The letter itself is always shown next to or on the color.

interface Glyph {
  color: string;
}

const GLYPHS: Glyph[] = [
  { color: "#d9542f" }, // A
  // B: darkened/pushed toward violet from the original #6f5bd1 -- simulated
  // against protanopia/deuteranopia/tritanopia, that color sat within
  // ~0.07-0.10 (normalized RGB) of D's blue, closer than any pair in the
  // reference Okabe-Ito colorblind-safe palette ever gets. This value keeps
  // >=0.28 separation from every other color under all three simulated
  // types -- see BACKLOG.md for the full before/after check.
  { color: "#3d2c96" },
  { color: "#2f9e8f" }, // C
  { color: "#2d7fd2" }, // D (paired change with B above)
  // E: darkened from the original #d9a41e for WCAG contrast -- white text
  // sits directly on this color (badges, chips), and the original gold only
  // cleared 2.26:1 against white, under the 3:1 floor for graphical
  // objects. This clears 3.58:1 and keeps its colorblind separation.
  { color: "#a58312" },
  { color: "#c0497e" }, // F
];

function indexFor(letter: string): number {
  const code = letter.toUpperCase().charCodeAt(0) - 65; // 'A' -> 0
  return ((code % GLYPHS.length) + GLYPHS.length) % GLYPHS.length;
}

export function glyphFor(letter: string): Glyph {
  return GLYPHS[indexFor(letter)];
}

/** Colored letter badge for plain HTML strings (panel chips, query text). */
export function eventBadge(letter: string): string {
  return `<span class="evt-badge-html" style="background:${glyphFor(letter).color}">${letter}</span>`;
}
