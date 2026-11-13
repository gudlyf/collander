// Recipe scaling: multiplies the leading quantity of an ingredient line and
// formats the result as a kitchen-friendly fraction. Lines without a leading
// quantity ("salt to taste", "juice of 1 lemon") are left unchanged.

const UNICODE_FRACTIONS: Record<string, number> = {
  "½": 1 / 2, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 1 / 4, "¾": 3 / 4, "⅕": 1 / 5, "⅖": 2 / 5,
  "⅗": 3 / 5, "⅘": 4 / 5, "⅙": 1 / 6, "⅚": 5 / 6, "⅛": 1 / 8, "⅜": 3 / 8, "⅝": 5 / 8,
  "⅞": 7 / 8,
};
const UF = Object.keys(UNICODE_FRACTIONS).join("");

// One number: "1 1/2", "1-1/2", "1½", "1/2", "½", "1.5", "2", "1 ½"
const NUM = `(?:\\d+(?:[.,]\\d+)?\\s*[${UF}]|\\d+-\\d+/\\d+|\\d+\\s+\\d+\\s*/\\s*\\d+|\\d+\\s*/\\s*\\d+|\\d+(?:[.,]\\d+)?|[${UF}])`;
// Optional range: "2-3", "2 – 3", "2 to 3", "2 or 3"
const LEADING = new RegExp(`^(\\s*)(${NUM})(?:(\\s*(?:-|–|—|to|or)\\s*)(${NUM}))?`, "i");

export function parseNumber(s: string): number | null {
  s = s.trim().replace(",", ".");
  let m = s.match(new RegExp(`^(\\d+(?:\\.\\d+)?)\\s*([${UF}])$`));
  if (m) return parseFloat(m[1]) + UNICODE_FRACTIONS[m[2]];
  m = s.match(/^(\d+)(?:\s+|-)(\d+)\s*\/\s*(\d+)$/);
  if (m) return +m[1] + +m[2] / +m[3];
  m = s.match(/^(\d+)\s*\/\s*(\d+)$/);
  if (m) return +m[2] === 0 ? null : +m[1] / +m[2];
  if (s in UNICODE_FRACTIONS) return UNICODE_FRACTIONS[s];
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : null;
}

const NICE: [number, string][] = [
  [1 / 8, "⅛"], [1 / 4, "¼"], [1 / 3, "⅓"], [3 / 8, "⅜"], [1 / 2, "½"], [5 / 8, "⅝"],
  [2 / 3, "⅔"], [3 / 4, "¾"], [7 / 8, "⅞"],
];

export function formatNumber(n: number): string {
  if (n <= 0) return "0";
  const whole = Math.floor(n + 1e-9);
  const frac = n - whole;
  if (frac < 0.04) return String(whole);
  if (frac > 0.96) return String(whole + 1);
  for (const [v, glyph] of NICE) {
    if (Math.abs(frac - v) < 0.015) return whole ? `${whole}${glyph}` : glyph;
  }
  // Not a common fraction: one decimal for big numbers, two for small.
  const rounded = n >= 10 ? Math.round(n * 10) / 10 : Math.round(n * 100) / 100;
  return String(rounded);
}

export interface Scaled {
  text: string;
  scaled: boolean; // a quantity was found and changed
  qtyEnd: number; // index where the (scaled) quantity ends; 0 when not scaled
}

export function scaleLine(text: string, factor: number): Scaled {
  const same = { text, scaled: false, qtyEnd: 0 };
  if (factor === 1 || !text) return same;
  const m = text.match(LEADING);
  if (!m) return same;
  const [whole, lead, a, sep, b] = m;
  const na = parseNumber(a);
  if (na === null) return same;
  let out = lead + formatNumber(na * factor);
  if (b !== undefined) {
    const nb = parseNumber(b);
    if (nb === null) return same;
    out += sep + formatNumber(nb * factor);
  }
  const rest = text.slice(whole.length);
  return { text: out + rest, scaled: true, qtyEnd: out.length };
}

/** Scale the first number in a servings string, e.g. "Serves 4" -> "Serves 8". */
export function scaleServings(servings: string | null, factor: number): string | null {
  if (!servings || factor === 1) return servings;
  const m = servings.match(/(\d+(?:\.\d+)?)(\s*(?:-|–|to)\s*(\d+(?:\.\d+)?))?/);
  if (!m) return servings;
  let rep = formatNumber(parseFloat(m[1]) * factor);
  if (m[3]) rep += m[2].replace(m[3], "") + formatNumber(parseFloat(m[3]) * factor);
  return servings.slice(0, m.index) + rep + servings.slice((m.index ?? 0) + m[0].length);
}

export const PRESET_FACTORS = [0.5, 1, 2, 3];

export function factorLabel(f: number): string {
  if (f === 0.5) return "½×";
  if (f === 0.25) return "¼×";
  return `${formatNumber(f)}×`;
}
