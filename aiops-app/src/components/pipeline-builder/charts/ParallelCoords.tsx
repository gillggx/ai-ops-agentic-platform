/**
 * ParallelCoords — N parallel axes, one polyline per row.
 *
 * Each dimension gets its own axis with auto domain. A `color_by` column
 * (numeric or categorical) selects per-line color; below-threshold rows
 * highlighted in alert color. Brushing (drag on axis) filters rows;
 * double-click clears the brush. Brush state lives in React, no callbacks
 * required from the host.
 *
 * Spec shape:
 *   spec.data: rows
 *   spec.dimensions: string[]
 *   spec.color_by?: string         numeric column → primary/alert thresholding
 *   spec.alert_below?: number      threshold for alert color (default null)
 */

'use client';

import * as React from 'react';
import {
  clear, el, readTheme, size, useSvgChart,
} from './lib';
import { scale, ticks } from './lib/primitives';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

const M = { t: 30, r: 28, b: 30, l: 28 };

interface DimMeta {
  name: string;
  min: number;
  max: number;
  values: number[];
}

function hexToRgba(hex: string, opacity: number): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${opacity})`;
}

interface RenderOpts {
  brushes: Record<string, [number, number] | null>;
  setBrush: (dim: string, range: [number, number] | null) => void;
}

function render(svg: SVGSVGElement, spec: ChartSpec, opts: RenderOpts) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const data = Array.isArray(spec.data) ? spec.data : [];
  const dims = Array.isArray(spec.dimensions) ? (spec.dimensions as string[]) : [];
  if (data.length === 0 || dims.length < 2) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '需要至少 2 個 dimensions' }, svg);
    return;
  }

  const colorBy = typeof spec.color_by === 'string' ? (spec.color_by as string) : null;
  const alertBelow = typeof spec.alert_below === 'number' ? (spec.alert_below as number) : null;

  const innerLeft = M.l;
  const innerRight = W - M.r;
  const innerTop = M.t;
  const innerBottom = H - M.b;

  if (spec.title) {
    el('text', { x: innerLeft, y: 14, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }

  // Per-dim metadata + scale
  const meta: DimMeta[] = dims.map((d) => {
    const arr = data.map((r) => Number(r[d])).filter((v) => Number.isFinite(v));
    const mn = arr.length ? Math.min(...arr) : 0;
    const mx = arr.length ? Math.max(...arr) : 1;
    const pad = (mx - mn) * 0.05 || 0.5;
    return { name: d, min: mn - pad, max: mx + pad, values: arr };
  });
  const yScales = meta.map((m) => scale(m.min, m.max, innerBottom, innerTop));
  const xPos = (i: number) => innerLeft + i * ((innerRight - innerLeft) / (dims.length - 1));

  // Axes
  dims.forEach((d, i) => {
    const xx = xPos(i);
    el('line', { x1: xx, x2: xx, y1: innerTop, y2: innerBottom, stroke: T.ink, 'stroke-width': 1 }, svg);
    el('text', { x: xx, y: innerTop - 8, 'text-anchor': 'middle', class: 'axis-title', text: d }, svg);
    ticks(meta[i].min, meta[i].max, 4).forEach((v) => {
      const yy = yScales[i](v);
      el('line', { x1: xx - 3, x2: xx + 3, y1: yy, y2: yy, stroke: T.ink, 'stroke-width': 1 }, svg);
      el('text', { x: xx - 6, y: yy + 3, 'text-anchor': 'end', class: 'axis-label', text: v.toFixed(0) }, svg);
    });
    // Brush highlight
    const b = opts.brushes[d];
    if (b) {
      const [bLo, bHi] = [Math.min(b[0], b[1]), Math.max(b[0], b[1])];
      const y0 = yScales[i](bHi);
      const y1 = yScales[i](bLo);
      el('rect', {
        x: xx - 7, y: y0, width: 14, height: Math.abs(y1 - y0),
        fill: hexToRgba(T.data, T.fillOp), stroke: T.data, 'stroke-width': T.stroke,
      }, svg);
    }
  });

  // Lines
  data.forEach((row) => {
    let active = true;
    for (let i = 0; i < dims.length; i += 1) {
      const b = opts.brushes[dims[i]];
      if (!b) continue;
      const v = Number(row[dims[i]]);
      const lo = Math.min(b[0], b[1]);
      const hi = Math.max(b[0], b[1]);
      if (!Number.isFinite(v) || v < lo || v > hi) {
        active = false;
        break;
      }
    }
    const path = dims.map((d, i) => {
      const v = Number(row[d]);
      if (!Number.isFinite(v)) return null;
      return `${i === 0 ? 'M' : 'L'}${xPos(i).toFixed(2)},${yScales[i](v).toFixed(2)}`;
    }).filter(Boolean).join('');
    if (!path) return;

    let stroke = T.data;
    if (active && colorBy && alertBelow !== null) {
      const cv = Number(row[colorBy]);
      if (Number.isFinite(cv) && cv < alertBelow) stroke = T.alert;
    }
    if (!active) stroke = T.gridStrong;
    el('path', {
      d: path,
      fill: 'none',
      stroke,
      'stroke-width': active ? 1.1 : 0.8,
      opacity: active ? '0.55' : '0.05',
    }, svg);
  });

  // Brush hit zones — drag to set range, double-click to clear.
  dims.forEach((d, i) => {
    const xx = xPos(i);
    const hit = el('rect', {
      x: xx - 12, y: innerTop, width: 24, height: innerBottom - innerTop,
      fill: 'transparent',
    }, svg);
    (hit as SVGElement).style.cursor = 'ns-resize';
    let startV: number | null = null;
    hit.addEventListener('mousedown', (e) => {
      const me = e as MouseEvent;
      const rect = svg.getBoundingClientRect();
      const cy = me.clientY - rect.top;
      startV = yScales[i].invert(cy);
      e.preventDefault();
    });
    const onMove = (e: MouseEvent) => {
      if (startV === null) return;
      const rect = svg.getBoundingClientRect();
      const cy = e.clientY - rect.top;
      const v1 = yScales[i].invert(cy);
      opts.setBrush(d, [startV, v1]);
    };
    const onUp = () => {
      startV = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    hit.addEventListener('mousedown', () => {
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    });
    hit.addEventListener('dblclick', () => opts.setBrush(d, null));
  });
}

export default function ParallelCoords({ spec, height }: Props) {
  const [brushes, setBrushes] = React.useState<Record<string, [number, number] | null>>({});
  const setBrush = React.useCallback((dim: string, range: [number, number] | null) => {
    setBrushes((prev) => ({ ...prev, [dim]: range }));
  }, []);

  const ref = useSvgChart(
    (svg) => render(svg, spec, { brushes, setBrush }),
    [spec, brushes, setBrush],
  );

  return (
    <div className="pb-chart-card" style={{ height: height ?? 320 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Parallel coordinates'} />
    </div>
  );
}

export { render as renderParallelCoords };
