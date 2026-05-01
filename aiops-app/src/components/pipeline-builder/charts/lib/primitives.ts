/**
 * Chart primitives — pure math + color helpers.
 *
 * Ported from `/Users/gill/AIOps - Charting design/chartlib.js`. Self-contained,
 * no D3 / Plotly / Vega dependency. Every function is a pure function (no React,
 * no DOM) — the React layer (useSvgChart hook + SVG helpers) lives elsewhere.
 *
 * Used by every chart in `charts/*.tsx` so the visual output stays consistent
 * across the 18-block engine.
 */

// ── Linear scale ────────────────────────────────────────────────────────────

export type LinearScale = ((value: number) => number) & {
  invert: (range: number) => number;
  domain: [number, number];
  range: [number, number];
};

export function scale(d0: number, d1: number, r0: number, r1: number): LinearScale {
  const m = (r1 - r0) / ((d1 - d0) || 1);
  const f = ((v: number) => r0 + (v - d0) * m) as LinearScale;
  f.invert = (r: number) => d0 + (r - r0) / m;
  f.domain = [d0, d1];
  f.range = [r0, r1];
  return f;
}

// ── "Nice" tick generator (1 / 2 / 5 × 10^n) ────────────────────────────────

export function ticks(d0: number, d1: number, count = 6): number[] {
  const span = d1 - d0;
  if (span <= 0) return [d0];
  const step0 = span / count;
  const pow10 = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / pow10;
  let step: number;
  if (norm < 1.5) step = pow10;
  else if (norm < 3) step = 2 * pow10;
  else if (norm < 7) step = 5 * pow10;
  else step = 10 * pow10;
  const start = Math.ceil(d0 / step) * step;
  const out: number[] = [];
  for (let v = start; v <= d1 + step * 0.0001; v += step) {
    out.push(+v.toFixed(12));
  }
  return out;
}

// ── Statistics ──────────────────────────────────────────────────────────────

export function mean(arr: ArrayLike<number>): number {
  let s = 0;
  for (let i = 0; i < arr.length; i++) s += arr[i];
  return s / arr.length;
}

export function std(arr: ArrayLike<number>): number {
  const m = mean(arr);
  let s = 0;
  for (let i = 0; i < arr.length; i++) {
    const d = arr[i] - m;
    s += d * d;
  }
  return Math.sqrt(s / (arr.length - 1 || 1));
}

export function quantile(sorted: ArrayLike<number>, q: number): number {
  const i = (sorted.length - 1) * q;
  const lo = Math.floor(i);
  const hi = Math.ceil(i);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
}

export interface BoxStats {
  min: number;
  max: number;
  q1: number;
  med: number;
  q3: number;
  /** Lower / upper whisker (inner-fence-clipped). */
  lw: number;
  uw: number;
  outliers: number[];
  n: number;
  mean: number;
  std: number;
}

export function quartiles(arr: ArrayLike<number>): BoxStats {
  const s = Array.from(arr).sort((a, b) => a - b);
  const q1 = quantile(s, 0.25);
  const med = quantile(s, 0.5);
  const q3 = quantile(s, 0.75);
  const iqr = q3 - q1;
  const lf = q1 - 1.5 * iqr;
  const uf = q3 + 1.5 * iqr;
  const inner = s.filter((v) => v >= lf && v <= uf);
  const lw = inner.length ? inner[0] : s[0];
  const uw = inner.length ? inner[inner.length - 1] : s[s.length - 1];
  const outliers = s.filter((v) => v < lf || v > uf);
  return {
    min: s[0],
    max: s[s.length - 1],
    q1,
    med,
    q3,
    lw,
    uw,
    outliers,
    n: s.length,
    mean: mean(s),
    std: std(s),
  };
}

export function pearson(a: ArrayLike<number>, b: ArrayLike<number>): number {
  const ma = mean(a);
  const mb = mean(b);
  let num = 0;
  let da = 0;
  let db = 0;
  for (let i = 0; i < a.length; i++) {
    const xa = a[i] - ma;
    const xb = b[i] - mb;
    num += xa * xb;
    da += xa * xa;
    db += xb * xb;
  }
  return num / Math.sqrt(da * db);
}

// ── Normal distribution ─────────────────────────────────────────────────────

export function normPdf(x: number, mu: number, sigma: number): number {
  const d = x - mu;
  return Math.exp(-(d * d) / (2 * sigma * sigma)) / (sigma * Math.sqrt(2 * Math.PI));
}

/** Inverse normal CDF (Beasley–Springer–Moro). */
export function normInv(p: number): number {
  const a = [
    -3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
    1.38357751867269e2, -3.066479806614716e1, 2.506628277459239,
  ];
  const b = [
    -5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
    6.680131188771972e1, -1.328068155288572e1,
  ];
  const c = [
    -7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838,
    -2.549732539343734, 4.374664141464968, 2.938163982698783,
  ];
  const d = [
    7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996,
    3.754408661907416,
  ];
  const plow = 0.02425;
  const phigh = 1 - plow;
  let q: number;
  let r: number;
  if (p < plow) {
    q = Math.sqrt(-2 * Math.log(p));
    return (
      (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    );
  }
  if (p <= phigh) {
    q = p - 0.5;
    r = q * q;
    return (
      ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) /
      (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    );
  }
  q = Math.sqrt(-2 * Math.log(1 - p));
  return (
    -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
    ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
  );
}

// ── Color scales ────────────────────────────────────────────────────────────

const VIRIDIS = ['#440154', '#404387', '#29788E', '#22A784', '#79D151', '#FDE724'];
const DIVERGING = ['#1e3a8a', '#2563eb', '#93c5fd', '#f5f5f0', '#fca5a5', '#dc2626', '#7f1d1d'];

function hex2rgb(h: string): [number, number, number] {
  const s = h.replace('#', '');
  return [
    parseInt(s.slice(0, 2), 16),
    parseInt(s.slice(2, 4), 16),
    parseInt(s.slice(4, 6), 16),
  ];
}

function rgb2hex(r: number, g: number, b: number): string {
  return (
    '#' +
    [r, g, b]
      .map((v) => Math.round(v).toString(16).padStart(2, '0'))
      .join('')
  );
}

export function mix(a: string, b: string, t: number): string {
  const A = hex2rgb(a);
  const B = hex2rgb(b);
  return rgb2hex(
    A[0] + (B[0] - A[0]) * t,
    A[1] + (B[1] - A[1]) * t,
    A[2] + (B[2] - A[2]) * t,
  );
}

function paletteAt(palette: string[], t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  const n = palette.length - 1;
  const i = Math.floor(clamped * n);
  const f = clamped * n - i;
  if (i >= n) return palette[n];
  return mix(palette[i], palette[i + 1], f);
}

/** Sequential color-blind-safe palette (purple → green → yellow). */
export function viridis(t: number): string {
  return paletteAt(VIRIDIS, t);
}

/** Diverging blue-white-red, centered at t=0.5. */
export function diverging(t: number): string {
  return paletteAt(DIVERGING, t);
}

// ── Defect code colors (semiconductor convention) ──────────────────────────

export const DEFECT_COLORS: Record<string, string> = {
  Particle: '#2563EB',
  Scratch: '#DC2626',
  Residue: '#059669',
  Pattern: '#d97706',
  Bridge: '#7c3aed',
  Open: '#0891b2',
  Void: '#be185d',
  Other: '#64748B',
};
