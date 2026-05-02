/**
 * DefectStack — wafer outline + defect points colored by defect_code,
 * with a clickable legend that toggles each code on/off.
 *
 * Spec shape:
 *   spec.data: rows
 *   spec.x_column           x in millimeters (default 'x')
 *   spec.y_column           y in millimeters (default 'y')
 *   spec.defect_column      e.g. 'defect_code' (default)
 *   spec.codes?             ordered code list; auto-detected if missing
 *   spec.wafer_radius_mm    default 150
 *   spec.notch?
 */

'use client';

import * as React from 'react';
import {
  clear, DEFECT_COLORS, el, readTheme, size, useSvgChart,
} from './lib';
import { drawWaferOutline, type Notch } from './lib/wafer';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

interface DefectPoint {
  x: number;
  y: number;
  code: string;
}

function readPoints(spec: ChartSpec): DefectPoint[] {
  const data = Array.isArray(spec.data) ? spec.data : [];
  const xCol = (spec.x_column as string | undefined) ?? 'x';
  const yCol = (spec.y_column as string | undefined) ?? 'y';
  const codeCol = (spec.defect_column as string | undefined) ?? 'defect_code';
  const out: DefectPoint[] = [];
  for (const r of data) {
    const x = Number(r[xCol]);
    const y = Number(r[yCol]);
    const c = r[codeCol];
    if (!Number.isFinite(x) || !Number.isFinite(y) || c == null) continue;
    out.push({ x, y, code: String(c) });
  }
  return out;
}

function colorFor(code: string): string {
  if (DEFECT_COLORS[code]) return DEFECT_COLORS[code];
  return DEFECT_COLORS.Other;
}

interface RenderOpts {
  visible: Set<string>;
  onToggle: (code: string) => void;
}

function render(svg: SVGSVGElement, spec: ChartSpec, opts: RenderOpts) {
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

  // Code list
  let codes: string[];
  if (Array.isArray(spec.codes)) {
    codes = (spec.codes as string[]).map(String);
  } else {
    const seen = new Set<string>();
    codes = [];
    for (const p of points) {
      if (!seen.has(p.code)) {
        seen.add(p.code);
        codes.push(p.code);
      }
    }
  }

  const legendW = 110;
  const padding = 12;
  const usable = Math.min(W - legendW - padding * 2, H - padding * 2);
  const R = usable / 2;
  const cx = padding + R;
  const cy = H / 2;

  // Wafer outline + crosshair + grid radii
  drawWaferOutline(svg, cx, cy, R, notch);
  el('line', { x1: cx - R, x2: cx + R, y1: cy, y2: cy, stroke: T.grid, 'stroke-width': 1 }, svg);
  el('line', { x1: cx, x2: cx, y1: cy - R, y2: cy + R, stroke: T.grid, 'stroke-width': 1 }, svg);
  [0.33, 0.66].forEach((f) => {
    el('circle', { cx, cy, r: R * f, fill: 'none', stroke: T.grid, 'stroke-width': 1 }, svg);
  });

  const px = (gx: number) => cx + (gx / radius) * R;
  const py = (gy: number) => cy + (gy / radius) * R;

  // Defect points
  for (const p of points) {
    if (!opts.visible.has(p.code)) continue;
    el('circle', {
      cx: px(p.x), cy: py(p.y), r: 1.8,
      fill: colorFor(p.code), opacity: '0.7',
    }, svg);
  }

  // Counts by code
  const counts: Record<string, number> = {};
  for (const c of codes) counts[c] = 0;
  for (const p of points) counts[p.code] = (counts[p.code] ?? 0) + 1;

  // Legend (clickable)
  const lgX = W - legendW + 4;
  let lgY = padding + 8;
  el('text', {
    x: lgX, y: lgY,
    'font-family': 'var(--chart-font-mono)', 'font-size': 9.5,
    fill: T.secondary, text: 'DEFECT TYPE',
  }, svg);
  lgY += 12;
  for (const code of codes) {
    const isOn = opts.visible.has(code);
    const grp = el('g', { opacity: isOn ? '1' : '0.35' }, svg);
    (grp as SVGElement).style.cursor = 'pointer';
    el('rect', { x: lgX, y: lgY - 8, width: 8, height: 8, fill: colorFor(code), rx: 1 }, grp);
    el('text', {
      x: lgX + 12, y: lgY,
      'font-family': 'var(--chart-font-mono)', 'font-size': 10,
      fill: T.ink, text: code,
    }, grp);
    el('text', {
      x: lgX + legendW - 10, y: lgY,
      'text-anchor': 'end',
      'font-family': 'var(--chart-font-mono)', 'font-size': 10,
      fill: T.ink, text: `${counts[code] ?? 0}`,
    }, grp);
    grp.addEventListener('click', () => opts.onToggle(code));
    lgY += 14;
  }

  if (spec.title) {
    el('text', { x: padding, y: 14, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }
}

export default function DefectStack({ spec, height }: Props) {
  // Initial visible = all codes detected from data (or codes in spec).
  const initialVisible = React.useMemo(() => {
    if (Array.isArray(spec.codes)) return new Set((spec.codes as string[]).map(String));
    const data = Array.isArray(spec.data) ? spec.data : [];
    const codeCol = (spec.defect_column as string | undefined) ?? 'defect_code';
    const s = new Set<string>();
    for (const r of data) {
      const c = r[codeCol];
      if (c != null) s.add(String(c));
    }
    return s;
  }, [spec]);

  const [visible, setVisible] = React.useState<Set<string>>(initialVisible);
  // Reset visibility when spec changes (new data)
  React.useEffect(() => setVisible(initialVisible), [initialVisible]);
  const onToggle = React.useCallback((code: string) => {
    setVisible((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }, []);

  const ref = useSvgChart(
    (svg) => render(svg, spec, { visible, onToggle }),
    [spec, visible, onToggle],
  );
  return (
    <div className="pb-chart-card" style={{ height: height ?? 380 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Defect stack map'} />
    </div>
  );
}

export { render as renderDefectStack };
