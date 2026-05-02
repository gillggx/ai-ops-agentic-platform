/**
 * WaferHeatmap — circular wafer plot with IDW spatial interpolation.
 *
 * Renders an interpolated value field over a wafer outline, with optional
 * measurement-point overlays and a vertical color legend. Returns
 * uniformity stats (μ, σ, range, half-range / μ %).
 *
 * Spec shape:
 *   spec.data: rows
 *   spec.x_column        x in millimeters, centered
 *   spec.y_column        y in millimeters, centered
 *   spec.value_column    measurement value
 *   spec.wafer_radius_mm default 150
 *   spec.notch?          'bottom' | 'top' | 'left' | 'right'
 *   spec.unit?           'nm' | 'Å' | …
 *   spec.color_mode?     'viridis' | 'diverging' (default viridis)
 *   spec.show_points?    true
 *   spec.grid_n?         interpolation grid resolution (default 60)
 */

'use client';

import * as React from 'react';
import {
  clear, diverging, el, mean, readTheme, size, std, tooltip, useSvgChart, viridis,
} from './lib';
import { drawWaferOutline, idwGrid, type Notch, type WaferPoint } from './lib/wafer';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

function readPoints(spec: ChartSpec): WaferPoint[] {
  const data = Array.isArray(spec.data) ? spec.data : [];
  const xCol = (spec.x_column as string | undefined) ?? 'x';
  const yCol = (spec.y_column as string | undefined) ?? 'y';
  const vCol = (spec.value_column as string | undefined)
    ?? (Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : null);
  if (!vCol) return [];
  const pts: WaferPoint[] = [];
  for (const r of data) {
    const x = Number(r[xCol]);
    const y = Number(r[yCol]);
    const v = Number(r[vCol]);
    if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(v)) {
      pts.push({ x, y, v });
    }
  }
  return pts;
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const points = readPoints(spec);
  if (points.length === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
    return;
  }

  const radius = (spec.wafer_radius_mm as number | undefined) ?? 150;
  const notch = ((spec.notch as Notch | undefined) ?? 'bottom') as Notch;
  const unit = (spec.unit as string | undefined) ?? '';
  const colorMode = (spec.color_mode as 'viridis' | 'diverging' | undefined) ?? 'viridis';
  const showPoints = spec.show_points !== false;
  const gridN = (spec.grid_n as number | undefined) ?? 60;
  const colorFn = colorMode === 'diverging' ? diverging : viridis;

  const legendW = 22;
  const padding = 16;
  const usable = Math.min(W - legendW - padding * 2, H - padding * 2);
  const R = usable / 2;
  const cx = padding + R;
  const cy = H / 2;

  const vals = points.map((p) => p.v);
  const vMin = Math.min(...vals);
  const vMax = Math.max(...vals);

  // Interpolate
  const grid = idwGrid(points, radius, gridN, 2);
  const cell = (2 * radius) / gridN;
  const px = (gx: number) => cx + (gx / radius) * R;
  const py = (gy: number) => cy + (gy / radius) * R;

  const cellWPx = (R / radius) * cell + 0.5;
  for (let i = 0; i < gridN; i += 1) {
    for (let j = 0; j < gridN; j += 1) {
      const v = grid[i][j];
      if (v == null) continue;
      const gx = -radius + j * cell;
      const gy = -radius + i * cell;
      const t = vMax === vMin ? 0.5 : (v - vMin) / (vMax - vMin);
      el('rect', {
        x: px(gx), y: py(gy),
        width: cellWPx, height: cellWPx,
        fill: colorFn(t),
      }, svg);
    }
  }

  // Wafer outline + notch
  drawWaferOutline(svg, cx, cy, R, notch);

  // Measurement points
  if (showPoints) {
    const tt = tooltip();
    for (const p of points) {
      const ppx = px(p.x);
      const ppy = py(p.y);
      const c = el('circle', {
        cx: ppx, cy: ppy, r: 2.4,
        fill: T.bg, stroke: T.gridStrong, 'stroke-width': 1,
      }, svg);
      (c as SVGElement).style.cursor = 'pointer';
      c.addEventListener('mouseenter', (e) => {
        const me = e as MouseEvent;
        tt.show(
          `<b>(${p.x.toFixed(0)}, ${p.y.toFixed(0)}) mm</b><br/>value: ${p.v.toFixed(2)} ${unit}`,
          me.clientX, me.clientY,
        );
      });
      c.addEventListener('mouseleave', () => tt.hide());
    }
  }

  // Color legend (right)
  const lgX = W - legendW - 4;
  const lgY0 = cy - R;
  const lgY1 = cy + R;
  const lgH = lgY1 - lgY0;
  const steps = 32;
  for (let k = 0; k < steps; k += 1) {
    el('rect', {
      x: lgX,
      y: lgY1 - ((k + 1) / steps) * lgH,
      width: 14,
      height: lgH / steps + 0.5,
      fill: colorFn(k / (steps - 1)),
    }, svg);
  }
  el('rect', { x: lgX, y: lgY0, width: 14, height: lgH, fill: 'none', stroke: T.gridStrong, 'stroke-width': 1 }, svg);
  [vMin, (vMin + vMax) / 2, vMax].forEach((v, i) => {
    const yy = lgY1 - (i / 2) * lgH;
    el('text', { x: lgX - 3, y: yy + 3, 'text-anchor': 'end', class: 'axis-label', text: v.toFixed(1) }, svg);
  });

  // Stats annotation (bottom-left)
  const mu = mean(vals);
  const sigma = std(vals);
  const range = vMax - vMin;
  const uniformity = mu !== 0 ? (range / 2 / mu) * 100 : NaN;
  const text =
    `n=${vals.length}   μ=${mu.toFixed(2)}   σ=${sigma.toFixed(3)}   range=${range.toFixed(2)}` +
    (Number.isFinite(uniformity) ? `   ±${uniformity.toFixed(2)}%` : '');
  el('text', {
    x: padding, y: H - 6,
    'text-anchor': 'start',
    class: 'axis-label',
    'font-family': 'var(--chart-font-mono)',
    fill: T.ink,
    text,
  }, svg);

  if (spec.title) {
    el('text', { x: padding, y: 14, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }
}

export default function WaferHeatmap({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  return (
    <div className="pb-chart-card" style={{ height: height ?? 380 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Wafer heatmap'} />
    </div>
  );
}

export { render as renderWaferHeatmap };
