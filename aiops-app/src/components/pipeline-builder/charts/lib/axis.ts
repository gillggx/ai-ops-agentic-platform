/**
 * X-axis type detection + axis-rendering helpers.
 *
 * Pipeline data flows in three flavours:
 *   - numeric  (process index, count, etc.)
 *   - time     (ISO8601 strings or Date objects)
 *   - category (step IDs, tool IDs, lot IDs)
 *
 * Plotly auto-detects this; for SVG we sniff explicitly. The result drives
 * scale construction (linear vs band) and tick formatting.
 */

import { LinearScale, scale, ticks } from './primitives';

export type AxisKind = 'numeric' | 'time' | 'category';

export interface NumericAxis {
  kind: 'numeric';
  scale: LinearScale;
  ticks: number[];
  format(v: number): string;
}

export interface TimeAxis {
  kind: 'time';
  /** Maps ms-since-epoch to pixel position. */
  scale: LinearScale;
  ticks: number[];
  /** Original string for each tick (when input came as ISO strings). */
  format(ms: number): string;
}

export interface CategoryAxis {
  kind: 'category';
  /** Domain: ordered category labels in first-seen order. */
  domain: string[];
  /** Pixel center for category[i]. */
  positionOf(label: string): number;
  /** Inverse — pixel → category index (for hover zones). */
  indexAt(px: number): number;
  /** Band width (each category occupies). */
  bandWidth: number;
  format(label: string): string;
}

export type Axis = NumericAxis | TimeAxis | CategoryAxis;

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/;

function isIsoString(v: unknown): v is string {
  return typeof v === 'string' && ISO_DATE_RE.test(v.trim());
}

function toMs(v: unknown): number | null {
  if (v instanceof Date) return v.getTime();
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string') {
    const t = Date.parse(v);
    return Number.isFinite(t) ? t : null;
  }
  return null;
}

/** Sniff the column type by scanning the values. */
export function detectAxisKind(values: ReadonlyArray<unknown>): AxisKind {
  if (values.length === 0) return 'category';
  let nNumeric = 0;
  let nTime = 0;
  let nString = 0;
  for (const v of values) {
    if (v instanceof Date) {
      nTime++;
      continue;
    }
    if (typeof v === 'number' && Number.isFinite(v)) {
      nNumeric++;
      continue;
    }
    if (isIsoString(v)) {
      nTime++;
      continue;
    }
    nString++;
  }
  if (nTime > 0 && nTime + nString === values.length) return 'time';
  if (nNumeric === values.length) return 'numeric';
  return 'category';
}

// ── Time tick formatting ──────────────────────────────────────────────────

function formatTimeRange(spanMs: number): (ms: number) => string {
  const day = 86400000;
  const minute = 60000;
  if (spanMs > 90 * day) {
    return (ms) => {
      const d = new Date(ms);
      return `${d.getMonth() + 1}/${d.getDate()}`;
    };
  }
  if (spanMs > day) {
    return (ms) => {
      const d = new Date(ms);
      return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    };
  }
  if (spanMs > minute) {
    return (ms) => {
      const d = new Date(ms);
      return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    };
  }
  return (ms) => {
    const d = new Date(ms);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
  };
}

// ── Public builder ────────────────────────────────────────────────────────

interface BuildOpts {
  /** Pixel range start (left edge for x, top for y). */
  rangeStart: number;
  /** Pixel range end. */
  rangeEnd: number;
  /** Pre-detected kind (skip sniff). */
  kind?: AxisKind;
  /** Pre-computed numeric domain (skip min/max scan). */
  domain?: [number, number];
  /** Tick count (advisory). */
  tickCount?: number;
  /** Padding fraction added to numeric domain (default 0). */
  pad?: number;
}

/**
 * Build an axis from raw values + a pixel range. Caller decides which kind
 * pre-detection wins; useful when an upstream pipeline already declared
 * the type (e.g. block always emits time on x).
 */
export function buildAxis(values: ReadonlyArray<unknown>, opts: BuildOpts): Axis {
  const kind = opts.kind ?? detectAxisKind(values);
  const tickCount = opts.tickCount ?? 6;
  if (kind === 'numeric') {
    const nums = values.map((v) => Number(v)).filter((v) => Number.isFinite(v));
    let mn = nums.length ? Math.min(...nums) : 0;
    let mx = nums.length ? Math.max(...nums) : 1;
    if (opts.domain) [mn, mx] = opts.domain;
    if (opts.pad && opts.pad > 0) {
      const span = mx - mn;
      mn -= span * opts.pad;
      mx += span * opts.pad;
    }
    if (mn === mx) {
      mn -= 0.5;
      mx += 0.5;
    }
    const sc = scale(mn, mx, opts.rangeStart, opts.rangeEnd);
    const tk = ticks(mn, mx, tickCount);
    return {
      kind: 'numeric',
      scale: sc,
      ticks: tk,
      format: (v) => (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(2)),
    };
  }
  if (kind === 'time') {
    const ms = values.map(toMs).filter((v): v is number => v !== null);
    let mn = ms.length ? Math.min(...ms) : 0;
    let mx = ms.length ? Math.max(...ms) : 1;
    if (opts.domain) [mn, mx] = opts.domain;
    if (mn === mx) {
      mn -= 60000;
      mx += 60000;
    }
    const sc = scale(mn, mx, opts.rangeStart, opts.rangeEnd);
    const tk = ticks(mn, mx, tickCount);
    const fmt = formatTimeRange(mx - mn);
    return { kind: 'time', scale: sc, ticks: tk, format: fmt };
  }
  // Category
  const seen = new Set<string>();
  const domain: string[] = [];
  for (const v of values) {
    const s = String(v);
    if (!seen.has(s)) {
      seen.add(s);
      domain.push(s);
    }
  }
  const span = opts.rangeEnd - opts.rangeStart;
  const bw = domain.length > 0 ? span / domain.length : span;
  const indexByLabel = new Map<string, number>();
  domain.forEach((d, i) => indexByLabel.set(d, i));
  return {
    kind: 'category',
    domain,
    bandWidth: bw,
    positionOf(label: string) {
      const i = indexByLabel.get(label) ?? -1;
      if (i < 0) return opts.rangeStart;
      return opts.rangeStart + (i + 0.5) * bw;
    },
    indexAt(px: number) {
      return Math.max(0, Math.min(domain.length - 1, Math.floor((px - opts.rangeStart) / bw)));
    },
    format: (label) => label,
  };
}

/**
 * Project an x-value onto the axis pixel position regardless of kind.
 * Returns null when the value can't be mapped (e.g. unknown category).
 */
export function projectX(axis: Axis, value: unknown): number | null {
  if (axis.kind === 'numeric') {
    const n = Number(value);
    return Number.isFinite(n) ? axis.scale(n) : null;
  }
  if (axis.kind === 'time') {
    const ms = toMs(value);
    return ms === null ? null : axis.scale(ms);
  }
  return axis.positionOf(String(value));
}
