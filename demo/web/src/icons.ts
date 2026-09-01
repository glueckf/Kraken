// Small ocean-themed glyphs standing in for raw message letters (A, B, C, …).
// Assignment is by letter position (A=0, B=1, …) so a given letter always
// reads as the same creature/shape across every scenario.

interface Glyph {
  name: string;
  color: string;
  // path/shape markup, viewBox 0 0 24 24, drawn with fill="currentColor"
  shape: string;
}

const GLYPHS: Glyph[] = [
  // A — fin (a shape breaking the surface)
  {
    name: "fin",
    color: "#d9542f",
    shape: `<path d="M12 2c1.2 4.6 1.1 8-2.6 11.4C7 15.6 4.6 16.4 2 16.6c2.4-3 3.6-6.4 3.4-10C7.6 4.4 9.8 2.8 12 2z"/>`,
  },
  // B — shadow (an unidentified shape underwater)
  {
    name: "shadow",
    color: "#6f5bd1",
    shape: `<ellipse cx="12" cy="15.5" rx="8.4" ry="4"/><circle cx="12" cy="8.4" r="3.2"/>`,
  },
  // C — fleeing fish
  {
    name: "fish",
    color: "#2f9e8f",
    shape: `<path d="M2.5 12c3.2-4.6 9-6.6 13.6-4-0.9 2-0.9 6 0 8-4.6 2.6-10.4 0.6-13.6-4z"/><circle cx="14.6" cy="9.8" r="1.1"/><path d="M16 12l5.5-3v6z"/>`,
  },
  // D — bubble trail
  {
    name: "bubbles",
    color: "#3b9fd8",
    shape: `<circle cx="7.5" cy="17" r="2.6"/><circle cx="14" cy="10.5" r="3.4"/><circle cx="18.2" cy="6.2" r="1.7"/>`,
  },
  // E — starfish
  {
    name: "starfish",
    color: "#d9a41e",
    shape: `<path d="M12 1.5l2.4 6.6 6.6 0.9-5 4.6 1.4 6.9-5.4-3.7-5.4 3.7 1.4-6.9-5-4.6 6.6-0.9z"/>`,
  },
  // F — spiral shell
  {
    name: "shell",
    color: "#c0497e",
    shape: `<path d="M12 21c-5 0-9-3.6-9-8.4C3 8.4 6.1 5 10.4 5c3.3 0 6 2.4 6 5.6 0 2.6-2.1 4.6-4.6 4.6-2 0-3.6-1.5-3.6-3.5 0-1.5 1.2-2.7 2.7-2.7"/>`,
  },
];

function indexFor(letter: string): number {
  const code = letter.toUpperCase().charCodeAt(0) - 65; // 'A' -> 0
  return ((code % GLYPHS.length) + GLYPHS.length) % GLYPHS.length;
}

export function glyphFor(letter: string): Glyph {
  return GLYPHS[indexFor(letter)];
}

/** Standalone <svg> for use inside plain HTML strings (panel chips/pills). */
export function eventIconSvg(letter: string, size = 13): string {
  const g = glyphFor(letter);
  return `<svg class="evt-icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">${g.shape}</svg>`;
}

/** A <g> fragment for use directly inside the reef's master <svg> (no nested <svg>). */
export function eventIconGroup(letter: string, cx: number, cy: number, size: number): string {
  const g = glyphFor(letter);
  const s = size / 24;
  return `<g class="evt-icon" transform="translate(${cx - size / 2} ${cy - size / 2}) scale(${s})" fill="${g.color}">${g.shape}</g>`;
}
