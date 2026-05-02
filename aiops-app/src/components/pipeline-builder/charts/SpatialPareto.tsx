/**
 * SpatialPareto — yield (or any value) heatmap binned onto a square grid
 * over a wafer. The worst cell is highlighted with a black outline so the
 * eye snaps to "where on the wafer is the problem?".
 *
 * Spec shape:
 *   spec.data: rows
 *   spec.x_column            x in mm (default 'x')
 *   spec.y_column            y in mm (default 'y')
 *   spec.value_column / spec.y[0]   value to aggregate (e.g. yield_pct)
 *   spec.wafer_radius_mm     default 150
 *   spec.notch?
 *   spec.grid_n?             cell-count along each axis (default 12)
 *   spec.unit?               '%' for yield, etc.
 */

'use client';

import * as React from 'react';
import {
  clear, diverging, el, mean, readTheme, size, tooltip, useSvgChart,
} from './lib';
import { drawWaferOutline, type Notch } from './lib/wafer';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

interface Cell {
  i: number;
  j: number;
  cx: number;
  cy: number;
  value: number;
}

function buildCells(
  spec: ChartSpec,
  radius: number,
  gridN: number,
): Cell[] {
  const data = Array.isArray(spec.data) ? spec.data : [];
  const xCol = (spec.x_column as string | undefined) ?? 'x';
  const yCol = (spec.y_column as string | undefined) ?? 'y';
  const vCol = (spec.value_column as string | undefined)
    ?? (Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : null);
  if (!vCol) return [];

  const bin: Record<string, { i: number; j: number; cx: number; cy: number; vals: number[] }> = {};
  for (const r of data) {
    const x = Number(r[xCol]);
    const y = Number(r[yCol]);
    const v = Number(r[vCol]);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(v)) continue;
    if (x * x + y * y > radius * radius) continue;
    const i = Math.min(gridN - 1, Math.max(0, Math.floor(((x + radius) / (2 * radius)) * gridN)));
    const j = Math.min(gridN - 1, Math.max(0, Math.floor(((y + radius) / (2 * radius)) * gridN)));
    const key = `${i},${j}`;
    if (!bin[key]) {
      const ncx = -radius + (i + 0.5) * (2 * radius) / gridN;
      const ncy = -radius + (j + 0.5) * (2 * radius) / gridN;
      bin[key] = { i, j, cx: ncx, cy: ncy, vals: [] };
    }
    bin[key].vals.push(v);
  }
  return Object.values(bin).map((b) => ({
    i: b.i,
    j: b.j,
    cx: b.cx,
    cy: b.cy,
    value: mean(b.vals),
  }));
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const radius = (spec.wafer_radius_mm as number | undefined) ?? 150;
  const notch = ((spec.notch as Notch | undefined) ?? 'bottom') as Notch;
  const gridN = (spec.grid_n as number | undefined) ?? 12;
  const unit = (spec.unit as string | undefined) ?? '';

  const cells = buildCells(spec, radius, gridN);
  if (cells.length === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
    return;
  }

  const legendW = 22;
  const padding = 16;
  const usable = Math.min(W - legendW - padding * 2, H - padding * 2);
  const R = usable / 2;
  const cx = padding + R;
  const cy = H / 2;

  const vals = cells.map((c) => c.value);
  const vMin = Math.min(...vals);
  const vMax = Math.max(...vals);
  const cellSizePx = (R * 2) / gridN;
  const px = (gx: number) => cx + (gx / radius) * R;
  const py = (gy: number) => cy + (gy / radius) * R;

  const tt = tooltip();
  for (const c of cells) {
    const t = vMax === vMin ? 0.5 : 1 - (c.value - vMin) / (vMax - vMin);
    const fill = diverging(0.5 + t * 0.45);
    const r = el('rect', {
      x: px(c.cx) - cellSizePx / 2,
      y: py(c.cy) - cellSizePx / 2,
      width: cellSizePx + 0.5,
      height: cellSizePx + 0.5,
      fill,
      opacity: '0.9',
    }, svg);
    (r as SVGElement).style.cursor = 'pointer';
    r.addEventListener('mouseenter', (e) => {
      const me = e as MouseEvent;
      tt.show(
        `<b>cell (${c.i}, ${c.j})</b><br/>` +
        `value: ${c.value.toFixed(2)}${unit}<br/>` +
        `(${c.cx.toFixed(0)}, ${c.cy.toFixed(0)}) mm`,
        me.clientX, me.clientY,
      );
    });
    r.addEventListener('mouseleave', () => tt.hide());
  }

  drawWaferOutline(svg, cx, cy, R, notch);

  // Legend (right)
  const lgX = W - legendW - 4;
  const lgY0 = cy - R;
  const lgY1 = cy + R;
  const lgH = lgY1 - lgY0;
  const steps = 32;
  for (let k = 0; k < steps; k += 1) {
    const t = 1 - k / (steps - 1);
    el('rect', {
      x: lgX, y: lgY1 - ((k + 1) / steps) * lgH,
      width: 14, height: lgH / steps + 0.5,
      fill: diverging(0.5 + t * 0.45),
    }, svg);
  }
  [vMax, (vMin + vMax) / 2, vMin].forEach((v, i) => {
    const yy = lgY0 + (i / 2) * lgH;
    el('text', {
      x: lgX - 3, y: yy + 3,
      'text-anchor': 'end', class: 'axis-label',
      text: `${v.toFixed(0)}${unit}`,
    }, svg);
  });

  // Worst cell highlight
  const worst = cells.reduce((a, b) => (a.value < b.value ? a : b));
  el('rect', {
    x: px(worst.cx) - cellSizePx / 2,
    y: py(worst.cy) - cellSizePx / 2,
    width: cellSizePx,
    height: cellSizePx,
    fill: 'none',
    stroke: T.ink,
    'stroke-width': 1.6,
  }, svg);

  if (spec.title) {
    el('text', { x: padding, y: 14, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }
}

export default function SpatialPareto({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  return (
    <div className="pb-chart-card" style={{ width: '100%', height: height ?? 380 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Spatial Pareto'} />
    </div>
  );
}

export { render as renderSpatialPareto };
