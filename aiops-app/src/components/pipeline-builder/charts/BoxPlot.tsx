/**
 * BoxPlot — IQR + whiskers + outliers, with optional nested grouping bracket.
 *
 * Two input shapes:
 *   1. **Raw rows** (legacy ChartDSL):
 *      `data: [{step:"S1", value:1.2}, ...]`, spec.x="step", spec.y=["value"]
 *      → groups by spec.x, computes quartiles per group inline.
 *
 *   2. **Pre-aggregated** (preferred when block emits already-bucketed data):
 *      `data: [{group:"Tool/Chamber", values:[1.2,3.4,...]}, ...]`,
 *      spec.values_field = "values", spec.group_field = "group".
 *
 * Optional `group_by_secondary` adds a parent bracket below the inner label —
 * e.g. inner=Chamber, outer=Tool produces "[A B C D] [A B C D] Tool-1 Tool-2".
 * Click the outer label to collapse to outer-only (state managed by React).
 */

'use client';

import * as React from 'react';
import {
  clear, el, quartiles, readTheme, size, tooltip, useSvgChart,
  type BoxStats,
} from './lib';
import { scale, ticks } from './lib/primitives';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

interface BoxGroup {
  key: string;
  label: string;     // inner label (Chamber)
  parent: string | null; // outer label (Tool)
  stats: BoxStats;
}

const M = { t: 16, r: 16, b: 60, l: 56 };

function hexToRgba(hex: string, opacity: number): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${opacity})`;
}

/**
 * Coerce ChartSpec.data + grouping fields into [{label, parent, values}] form
 * so the renderer just deals with already-grouped data.
 */
function buildGroups(spec: ChartSpec, expanded: boolean): BoxGroup[] {
  const data = Array.isArray(spec.data) ? spec.data : [];
  if (data.length === 0) return [];

  const innerKey = (spec.group_field as string | undefined) ?? spec.x;
  const outerKey = (spec.group_by_secondary as string | undefined) ?? null;
  const valuesField = (spec.values_field as string | undefined) ?? 'values';
  const yk = Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : null;

  // Detect pre-aggregated mode: any row has an array under valuesField OR `values`.
  const sample = data[0] ?? {};
  const isPreAgg = Array.isArray((sample as Record<string, unknown>)[valuesField]);

  // Build a map keyed by (outer/inner) → numeric values.
  const map = new Map<string, { inner: string; outer: string | null; values: number[] }>();
  for (const row of data) {
    const inner = String(row[innerKey] ?? '');
    const outer = outerKey ? String(row[outerKey] ?? '') : null;
    const k = outer ? `${outer}/${inner}` : inner;
    let bucket = map.get(k);
    if (!bucket) {
      bucket = { inner, outer, values: [] };
      map.set(k, bucket);
    }
    if (isPreAgg) {
      const arr = (row as Record<string, unknown>)[valuesField];
      if (Array.isArray(arr)) {
        for (const v of arr) {
          const n = Number(v);
          if (Number.isFinite(n)) bucket.values.push(n);
        }
      }
    } else if (yk) {
      const n = Number(row[yk]);
      if (Number.isFinite(n)) bucket.values.push(n);
    }
  }

  let groups: BoxGroup[] = Array.from(map.entries()).map(([k, b]) => ({
    key: k,
    label: b.inner,
    parent: b.outer,
    stats: quartiles(b.values),
  }));

  // When collapsed, fold by outer key (one box per outer).
  if (!expanded && outerKey) {
    const folded = new Map<string, number[]>();
    for (const [, b] of map) {
      if (!b.outer) continue;
      let arr = folded.get(b.outer);
      if (!arr) {
        arr = [];
        folded.set(b.outer, arr);
      }
      arr.push(...b.values);
    }
    groups = Array.from(folded.entries()).map(([outer, values]) => ({
      key: outer,
      label: outer,
      parent: null,
      stats: quartiles(values),
    }));
  }

  return groups;
}

interface RenderOpts {
  expanded: boolean;
  showOutliers: boolean;
  onToggleExpand?: () => void;
}

function render(svg: SVGSVGElement, spec: ChartSpec, opts: RenderOpts) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const yLabel = (spec.y_label as string | undefined)
    ?? (Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : 'value');
  const groups = buildGroups(spec, opts.expanded);

  if (groups.length === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
    return;
  }

  const innerLeft = M.l;
  const innerRight = W - M.r;
  const innerTop = M.t;
  const innerBottom = H - M.b;

  const allVals: number[] = [];
  for (const g of groups) {
    allVals.push(g.stats.lw, g.stats.uw, ...g.stats.outliers);
  }
  const yMin = Math.min(...allVals);
  const yMax = Math.max(...allVals);
  const pad = (yMax - yMin) * 0.05 || 0.5;
  const y = scale(yMin - pad, yMax + pad, innerBottom, innerTop);

  // X — categorical band
  const bw = (innerRight - innerLeft) / groups.length;
  const xCenter = (i: number) => innerLeft + (i + 0.5) * bw;

  // Y axis grid
  ticks(yMin - pad, yMax + pad, 6).forEach((v) => {
    const yy = y(v);
    el('line', { x1: innerLeft, x2: innerRight, y1: yy, y2: yy, class: 'grid-line' }, svg);
    el('text', { x: innerLeft - 6, y: yy + 3, 'text-anchor': 'end', class: 'axis-label', text: v.toFixed(1) }, svg);
  });
  el('line', { x1: innerLeft, x2: innerLeft, y1: innerTop, y2: innerBottom, class: 'axis-line' }, svg);

  // Y axis title (rotated)
  el('text', {
    x: 12,
    y: innerTop + (innerBottom - innerTop) / 2,
    'text-anchor': 'middle',
    class: 'axis-title',
    transform: `rotate(-90 12 ${innerTop + (innerBottom - innerTop) / 2})`,
    text: yLabel,
  }, svg);

  // Title
  if (spec.title) {
    el('text', { x: innerLeft, y: 12, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }

  // Boxes
  const tt = tooltip();
  groups.forEach((g0, i) => {
    const cx = xCenter(i);
    const bw0 = Math.min(bw * 0.6, 36);
    const s = g0.stats;
    const yQ1 = y(s.q1);
    const yQ3 = y(s.q3);
    const yMed = y(s.med);
    const yLW = y(s.lw);
    const yUW = y(s.uw);

    // Whiskers
    el('line', { x1: cx, x2: cx, y1: yLW, y2: yQ1, stroke: T.data, 'stroke-width': 1 }, svg);
    el('line', { x1: cx, x2: cx, y1: yQ3, y2: yUW, stroke: T.data, 'stroke-width': 1 }, svg);
    el('line', { x1: cx - bw0 / 3, x2: cx + bw0 / 3, y1: yLW, y2: yLW, stroke: T.data, 'stroke-width': 1 }, svg);
    el('line', { x1: cx - bw0 / 3, x2: cx + bw0 / 3, y1: yUW, y2: yUW, stroke: T.data, 'stroke-width': 1 }, svg);

    // Box
    el('rect', {
      x: cx - bw0 / 2,
      y: yQ3,
      width: bw0,
      height: Math.max(2, yQ1 - yQ3),
      fill: hexToRgba(T.data, T.fillOp),
      stroke: T.data,
      'stroke-width': 1,
    }, svg);

    // Median bold
    el('line', {
      x1: cx - bw0 / 2,
      x2: cx + bw0 / 2,
      y1: yMed,
      y2: yMed,
      stroke: '#0f172a',
      'stroke-width': Math.max(1.6, T.stroke * 1.5),
    }, svg);

    // Outliers
    if (opts.showOutliers) {
      s.outliers.forEach((o) => {
        const oc = el('circle', {
          cx,
          cy: y(o),
          r: 2.6,
          fill: T.alert,
          stroke: T.bg,
          'stroke-width': 0.5,
        }, svg);
        (oc as SVGElement).style.cursor = 'pointer';
        oc.addEventListener('mouseenter', (e) => {
          const me = e as MouseEvent;
          const where = g0.parent ? `${g0.parent} / ${g0.label}` : g0.label;
          tt.show(`<b>Outlier · ${where}</b><br/>value: ${o.toFixed(2)}`, me.clientX, me.clientY);
        });
        oc.addEventListener('mouseleave', () => tt.hide());
      });
    }

    // Hit zone (tooltip with stats)
    const hit = el('rect', {
      x: cx - bw / 2,
      y: innerTop,
      width: bw,
      height: innerBottom - innerTop,
      fill: 'transparent',
    }, svg);
    (hit as SVGElement).style.cursor = 'pointer';
    hit.addEventListener('mouseenter', (e) => {
      const me = e as MouseEvent;
      const where = g0.parent ? `${g0.parent} / ${g0.label}` : g0.label;
      tt.show(
        `<b>${where}</b><br/>` +
        `n: ${s.n}<br/>` +
        `median: ${s.med.toFixed(2)}<br/>` +
        `Q1–Q3: ${s.q1.toFixed(2)} – ${s.q3.toFixed(2)}<br/>` +
        `σ: ${s.std.toFixed(2)}<br/>` +
        `outliers: ${s.outliers.length}`,
        me.clientX,
        me.clientY,
      );
    });
    hit.addEventListener('mouseleave', () => tt.hide());

    // Inner label
    el('text', {
      x: cx,
      y: innerBottom + 14,
      'text-anchor': 'middle',
      class: 'axis-label',
      text: g0.label,
    }, svg);
  });

  // Outer bracket (only when expanded + parent exists)
  if (opts.expanded && groups.some((g) => g.parent)) {
    const byParent = new Map<string, number[]>();
    groups.forEach((g0, i) => {
      const p = g0.parent ?? '';
      let arr = byParent.get(p);
      if (!arr) {
        arr = [];
        byParent.set(p, arr);
      }
      arr.push(i);
    });
    byParent.forEach((idxs, parent) => {
      if (!parent) return;
      const x0 = xCenter(idxs[0]) - bw * 0.45;
      const x1 = xCenter(idxs[idxs.length - 1]) + bw * 0.45;
      const yy = innerBottom + 28;
      el('line', { x1: x0, x2: x1, y1: yy, y2: yy, stroke: T.ink, 'stroke-width': 1 }, svg);
      el('line', { x1: x0, x2: x0, y1: yy, y2: yy + 4, stroke: T.ink, 'stroke-width': 1 }, svg);
      el('line', { x1: x1, x2: x1, y1: yy, y2: yy + 4, stroke: T.ink, 'stroke-width': 1 }, svg);
      const txt = el('text', {
        x: (x0 + x1) / 2,
        y: yy + 16,
        'text-anchor': 'middle',
        class: 'axis-title',
        text: parent,
      }, svg);
      if (opts.onToggleExpand) {
        (txt as SVGElement).style.cursor = 'pointer';
        txt.addEventListener('click', () => opts.onToggleExpand!());
      }
    });
  }
}

export default function BoxPlot({ spec, height }: Props) {
  const hasNested = typeof spec.group_by_secondary === 'string';
  const [expanded, setExpanded] = React.useState<boolean>(
    typeof spec.expanded === 'boolean' ? spec.expanded : true,
  );
  const showOutliers =
    typeof spec.show_outliers === 'boolean' ? spec.show_outliers : true;

  const ref = useSvgChart(
    (svg) => render(svg, spec, {
      expanded,
      showOutliers,
      onToggleExpand: hasNested ? () => setExpanded((v) => !v) : undefined,
    }),
    [spec, expanded, showOutliers],
  );

  return (
    <div className="pb-chart-card" style={{ width: '100%', height: height ?? 300 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Box plot'} />
    </div>
  );
}

export { render as renderBoxPlot };
