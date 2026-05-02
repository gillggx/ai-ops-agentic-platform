/**
 * TrendWaferMaps — small-multiples grid of wafer heatmaps over time. Each
 * cell is a mini wafer with the same color domain so you can scan for
 * spatial drift / PM-related shifts at a glance. PM days flagged with a
 * dashed alert outline.
 *
 * Two input shapes:
 *   1. Pre-aggregated:
 *        spec.maps: [{ date: string, points: [{x,y,v}], is_pm?: bool }, …]
 *   2. Raw rows:
 *        spec.data: rows
 *        spec.x_column / spec.y_column / spec.value_column
 *        spec.time_column            grouping key per wafer/snapshot
 *        spec.pm_column?             optional boolean column (true = PM day)
 *
 * Spec extras:
 *   spec.wafer_radius_mm   default 150
 *   spec.notch?
 *   spec.cols?             grid columns (default = N maps in single row)
 *   spec.grid_n?           IDW resolution per mini-map (default 28)
 */

'use client';

import * as React from 'react';
import {
  clear, diverging, el, readTheme, size, useSvgChart,
} from './lib';
import { drawWaferOutline, idwGrid, type Notch, type WaferPoint } from './lib/wafer';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

interface MiniMap {
  date: string;
  points: WaferPoint[];
  is_pm?: boolean;
}

function readMaps(spec: ChartSpec): MiniMap[] {
  if (Array.isArray(spec.maps)) {
    return (spec.maps as MiniMap[]).filter(
      (m) => m && Array.isArray(m.points) && typeof m.date === 'string',
    );
  }
  const data = Array.isArray(spec.data) ? spec.data : [];
  const xCol = (spec.x_column as string | undefined) ?? 'x';
  const yCol = (spec.y_column as string | undefined) ?? 'y';
  const vCol = (spec.value_column as string | undefined)
    ?? (Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : null);
  const timeCol = (spec.time_column as string | undefined) ?? null;
  const pmCol = (spec.pm_column as string | undefined) ?? null;
  if (!vCol || !timeCol || data.length === 0) return [];

  const groups = new Map<string, MiniMap>();
  for (const r of data) {
    const date = String(r[timeCol] ?? '');
    const x = Number(r[xCol]);
    const y = Number(r[yCol]);
    const v = Number(r[vCol]);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(v)) continue;
    let g = groups.get(date);
    if (!g) {
      g = { date, points: [], is_pm: pmCol ? Boolean(r[pmCol]) : false };
      groups.set(date, g);
    }
    g.points.push({ x, y, v });
    if (pmCol && Boolean(r[pmCol])) g.is_pm = true;
  }
  return Array.from(groups.values());
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const maps = readMaps(spec);
  if (maps.length === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
    return;
  }

  const radius = (spec.wafer_radius_mm as number | undefined) ?? 150;
  const notch = ((spec.notch as Notch | undefined) ?? 'bottom') as Notch;
  const cols = (spec.cols as number | undefined) ?? maps.length;
  const rows = Math.ceil(maps.length / cols);
  const gridN = (spec.grid_n as number | undefined) ?? 28;

  const padding = 6;
  const cellW = (W - padding * 2) / cols;
  const cellH = (H - padding * 2 - 18) / rows; // 18 reserved for timeline arrow

  // Shared color domain across all mini-maps so visual comparison is meaningful.
  const allV = maps.flatMap((m) => m.points.map((p) => p.v));
  const vMin = Math.min(...allV);
  const vMax = Math.max(...allV);

  if (spec.title) {
    el('text', { x: padding, y: 12, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }

  maps.forEach((m, k) => {
    const ci = k % cols;
    const ri = Math.floor(k / cols);
    const x0 = padding + ci * cellW;
    const y0 = padding + ri * cellH + (spec.title ? 14 : 0);
    const usable = Math.min(cellW, cellH - 22);
    const R = usable / 2 - 4;
    const cx = x0 + cellW / 2;
    const cy = y0 + 16 + R;

    // Date label
    el('text', {
      x: cx, y: y0 + 10,
      'text-anchor': 'middle',
      'font-family': 'var(--chart-font-mono)', 'font-size': 10,
      fill: m.is_pm ? T.alert : T.ink,
      'font-weight': m.is_pm ? '700' : '500',
      text: m.date,
    }, svg);

    // PM-day alert outline
    if (m.is_pm) {
      el('rect', {
        x: x0 + 2, y: y0 + 1,
        width: cellW - 4, height: cellH - 2,
        fill: 'rgba(220,38,38,0.04)',
        stroke: 'rgba(220,38,38,0.3)',
        'stroke-width': 1, 'stroke-dasharray': '3 2',
        rx: 3,
      }, svg);
    }

    // IDW interpolation
    const grid = idwGrid(m.points, radius, gridN, 2);
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
          fill: diverging(t),
        }, svg);
      }
    }
    drawWaferOutline(svg, cx, cy, R, notch);
  });

  // Bottom timeline arrow
  const ay = H - 4;
  el('line', { x1: padding, x2: W - padding, y1: ay, y2: ay, stroke: T.ink, 'stroke-width': 1 }, svg);
  el('path', {
    d: `M${W - padding - 4},${ay - 3} L${W - padding},${ay} L${W - padding - 4},${ay + 3}`,
    fill: 'none', stroke: T.ink, 'stroke-width': 1,
  }, svg);
}

export default function TrendWaferMaps({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  return (
    <div className="pb-chart-card" style={{ width: '100%', height: height ?? 240 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Trend wafer maps'} />
    </div>
  );
}

export { render as renderTrendWaferMaps };
