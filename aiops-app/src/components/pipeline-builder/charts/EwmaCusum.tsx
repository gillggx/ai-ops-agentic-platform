/**
 * EwmaCusum — exponentially-weighted moving average + tabular CUSUM, sharing
 * one component with a `mode` toggle. EWMA is great for detecting small mean
 * shifts (λ ≈ 0.1–0.3); CUSUM is even more sensitive but harder to interpret.
 *
 * Spec shape:
 *   spec.value_column / spec.y[0]      numeric column to chart
 *   spec.values?: number[]             alternative pre-aggregated path
 *   spec.mode?: 'ewma' | 'cusum'       default 'ewma'
 *   spec.lambda?                       EWMA smoothing (default 0.2)
 *   spec.k?                            CUSUM reference (in σ units, default 0.5)
 *   spec.h?                            CUSUM decision interval (in σ units, default 4)
 *   spec.target?                       Override μ used for EWMA / CUSUM math
 */

'use client';

import * as React from 'react';
import {
  clear, el, mean, readTheme, size, std, tooltip, useSvgChart,
} from './lib';
import { scale, ticks } from './lib/primitives';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

const M = { t: 22, r: 56, b: 36, l: 60 };

function hexToRgba(hex: string, opacity: number): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${opacity})`;
}

function readValues(spec: ChartSpec): number[] {
  if (Array.isArray(spec.values)) {
    return (spec.values as unknown[])
      .map((v) => Number(v))
      .filter((v): v is number => Number.isFinite(v));
  }
  const data = Array.isArray(spec.data) ? spec.data : [];
  const valueCol = (spec.value_column as string | undefined)
    ?? (Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : null);
  if (!valueCol) return [];
  return data
    .map((r) => Number(r[valueCol]))
    .filter((v): v is number => Number.isFinite(v));
}

function buildPath(points: Array<[number, number]>): string {
  if (points.length === 0) return '';
  const parts: string[] = [];
  let inSeg = false;
  for (const [x, y] of points) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      inSeg = false;
      continue;
    }
    parts.push(`${inSeg ? 'L' : 'M'} ${x.toFixed(2)} ${y.toFixed(2)}`);
    inSeg = true;
  }
  return parts.join(' ');
}

function renderEwma(svg: SVGSVGElement, raw: number[], spec: ChartSpec) {
  const T = readTheme(svg);
  const [W, H] = size(svg);
  const innerLeft = M.l;
  const innerRight = W - M.r;
  const innerTop = M.t;
  const innerBottom = H - M.b;

  const lambda = typeof spec.lambda === 'number' && spec.lambda > 0 && spec.lambda <= 1
    ? (spec.lambda as number)
    : 0.2;
  const target = typeof spec.target === 'number' ? (spec.target as number) : null;
  const mu = target ?? mean(raw);
  const sigma = std(raw);

  const xs = scale(0.5, raw.length + 0.5, innerLeft, innerRight);

  // Compute EWMA series + time-varying control limits
  const z: number[] = [];
  let prev = mu;
  for (const v of raw) {
    prev = lambda * v + (1 - lambda) * prev;
    z.push(prev);
  }
  const limits = z.map((_, i) => {
    if (sigma <= 0) return { ucl: mu, lcl: mu };
    const sigZ = sigma * Math.sqrt((lambda / (2 - lambda)) * (1 - Math.pow(1 - lambda, 2 * (i + 1))));
    return { ucl: mu + 3 * sigZ, lcl: mu - 3 * sigZ };
  });

  const violations = z.map((v, i) =>
    v > limits[i].ucl || v < limits[i].lcl ? 'EWMA outside time-varying limits' : null,
  );

  // Y domain
  const allY = [
    ...z,
    ...limits.map((l) => l.ucl),
    ...limits.map((l) => l.lcl),
    ...raw,
  ].filter((v) => Number.isFinite(v));
  const vMin = Math.min(...allY);
  const vMax = Math.max(...allY);
  const pad = (vMax - vMin) * 0.1 || 0.5;
  const y = scale(vMin - pad, vMax + pad, innerBottom, innerTop);

  // Time-varying envelope (UCL/LCL)
  if (sigma > 0) {
    const upPoints: Array<[number, number]> = limits.map((l, i) => [xs(i + 1), y(l.ucl)]);
    const downPoints: Array<[number, number]> = limits.map((l, i) => [xs(raw.length - i), y(limits[raw.length - 1 - i].lcl)]);
    const path = buildPath([...upPoints, ...downPoints]) + 'Z';
    el('path', {
      d: path,
      fill: hexToRgba(T.alert, 0.05),
      stroke: hexToRgba(T.alert, 0.5),
      'stroke-width': 1,
      'stroke-dasharray': '3 2',
    }, svg);
  }

  // Center line
  el('line', {
    x1: innerLeft, x2: innerRight, y1: y(mu), y2: y(mu),
    stroke: T.ink, 'stroke-width': 1, 'stroke-dasharray': '2 4',
  }, svg);

  // Y grid + labels
  ticks(vMin - pad, vMax + pad, 5).forEach((v) => {
    const yy = y(v);
    el('line', { x1: innerLeft, x2: innerRight, y1: yy, y2: yy, class: 'grid-line' }, svg);
    el('text', { x: innerLeft - 6, y: yy + 3, 'text-anchor': 'end', class: 'axis-label', text: v.toFixed(2) }, svg);
  });

  // Raw values (faint)
  el('path', {
    d: buildPath(raw.map((v, i) => [xs(i + 1), y(v)])),
    fill: 'none',
    stroke: T.gridStrong,
    'stroke-width': 1,
  }, svg);

  // EWMA path (heavier)
  el('path', {
    d: buildPath(z.map((v, i) => [xs(i + 1), y(v)])),
    fill: 'none',
    stroke: T.data,
    'stroke-width': T.stroke + 0.4,
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
  }, svg);

  // Points + tooltip
  const tt = tooltip();
  z.forEach((v, i) => {
    const cx = xs(i + 1);
    const cy = y(v);
    const viol = violations[i];
    const dot = el('circle', {
      cx,
      cy,
      r: viol ? T.pointR + 1.6 : T.pointR,
      fill: viol ? T.alert : T.bg,
      stroke: viol ? T.alert : T.data,
      'stroke-width': 1.5,
    }, svg);
    (dot as SVGElement).style.cursor = 'pointer';
    dot.addEventListener('mouseenter', (e) => {
      const me = e as MouseEvent;
      tt.show(
        `<b>t = ${i + 1}</b><br/>raw: ${raw[i].toFixed(3)}<br/>EWMA: ${v.toFixed(3)}<br/>λ: ${lambda}` +
        (viol ? `<br/><span style="color:${T.alert}">⚠ ${viol}</span>` : ''),
        me.clientX,
        me.clientY,
      );
    });
    dot.addEventListener('mouseleave', () => tt.hide());
  });

  return violations;
}

function renderCusum(svg: SVGSVGElement, raw: number[], spec: ChartSpec) {
  const T = readTheme(svg);
  const [W, H] = size(svg);
  const innerLeft = M.l;
  const innerRight = W - M.r;
  const innerTop = M.t;
  const innerBottom = H - M.b;

  const k = typeof spec.k === 'number' && spec.k >= 0 ? (spec.k as number) : 0.5;
  const hCusum = typeof spec.h === 'number' && spec.h > 0 ? (spec.h as number) : 4;
  const target = typeof spec.target === 'number' ? (spec.target as number) : null;
  const mu = target ?? mean(raw);
  const sigma = std(raw);

  const xs = scale(0.5, raw.length + 0.5, innerLeft, innerRight);

  // Tabular CUSUM (one-sided each)
  const SH: number[] = [];
  const SL: number[] = [];
  let sh = 0;
  let sl = 0;
  for (const v of raw) {
    sh = Math.max(0, sh + (v - mu) - k * sigma);
    sl = Math.max(0, sl - (v - mu) - k * sigma);
    SH.push(sh);
    SL.push(-sl);
  }
  const limit = hCusum * sigma;
  const allY = [...SH, ...SL, limit, -limit].filter((v) => Number.isFinite(v));
  const vMin = Math.min(...allY);
  const vMax = Math.max(...allY);
  const pad = (vMax - vMin) * 0.1 || 0.5;
  const y = scale(vMin - pad, vMax + pad, innerBottom, innerTop);

  // Out-of-limit band
  el('rect', {
    x: innerLeft,
    y: innerTop,
    width: innerRight - innerLeft,
    height: y(limit) - innerTop,
    fill: hexToRgba(T.alert, 0.04),
  }, svg);
  el('rect', {
    x: innerLeft,
    y: y(-limit),
    width: innerRight - innerLeft,
    height: innerBottom - y(-limit),
    fill: hexToRgba(T.alert, 0.04),
  }, svg);

  // Y grid + labels
  ticks(vMin - pad, vMax + pad, 5).forEach((v) => {
    const yy = y(v);
    el('line', { x1: innerLeft, x2: innerRight, y1: yy, y2: yy, class: 'grid-line' }, svg);
    el('text', { x: innerLeft - 6, y: yy + 3, 'text-anchor': 'end', class: 'axis-label', text: v.toFixed(2) }, svg);
  });

  // Center + control lines
  el('line', { x1: innerLeft, x2: innerRight, y1: y(0), y2: y(0), stroke: T.ink, 'stroke-width': 1, 'stroke-dasharray': '2 4' }, svg);
  el('line', { x1: innerLeft, x2: innerRight, y1: y(limit), y2: y(limit), stroke: T.alert, 'stroke-width': 1.2, 'stroke-dasharray': '6 4' }, svg);
  el('line', { x1: innerLeft, x2: innerRight, y1: y(-limit), y2: y(-limit), stroke: T.alert, 'stroke-width': 1.2, 'stroke-dasharray': '6 4' }, svg);

  // SH / SL series
  el('path', {
    d: buildPath(SH.map((v, i) => [xs(i + 1), y(v)])),
    fill: 'none',
    stroke: T.data,
    'stroke-width': T.stroke + 0.2,
  }, svg);
  el('path', {
    d: buildPath(SL.map((v, i) => [xs(i + 1), y(v)])),
    fill: 'none',
    stroke: T.secondary,
    'stroke-width': T.stroke + 0.2,
  }, svg);

  // Points (showing violations distinctly)
  const violations = SH.map((v, i) => (v > limit || SL[i] < -limit ? 'CUSUM exceeded h·σ' : null));
  SH.forEach((v, i) => {
    const viol = v > limit;
    el('circle', {
      cx: xs(i + 1),
      cy: y(v),
      r: viol ? T.pointR + 1.6 : T.pointR - 0.4,
      fill: viol ? T.alert : T.bg,
      stroke: T.data,
      'stroke-width': T.stroke,
    }, svg);
  });
  SL.forEach((v, i) => {
    const viol = v < -limit;
    el('circle', {
      cx: xs(i + 1),
      cy: y(v),
      r: viol ? T.pointR + 1.6 : T.pointR - 0.4,
      fill: viol ? T.alert : T.bg,
      stroke: T.secondary,
      'stroke-width': T.stroke,
    }, svg);
  });

  // Right-edge labels
  const monoAttr = { 'font-family': 'var(--chart-font-mono)', 'font-size': 9.5 };
  el('text', { x: innerRight + 4, y: y(limit) + 3, ...monoAttr, fill: T.alert, text: `H+ ${limit.toFixed(2)}` }, svg);
  el('text', { x: innerRight + 4, y: y(-limit) + 3, ...monoAttr, fill: T.alert, text: `H− ${(-limit).toFixed(2)}` }, svg);

  return violations;
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const raw = readValues(spec);
  if (raw.length === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
    return;
  }

  const mode = (spec.mode === 'cusum') ? 'cusum' : 'ewma';

  if (spec.title) {
    el('text', { x: M.l, y: 14, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }

  if (mode === 'cusum') {
    renderCusum(svg, raw, spec);
  } else {
    renderEwma(svg, raw, spec);
  }

  // Shared X axis
  const innerLeft = M.l;
  const innerRight = W - M.r;
  const innerBottom = H - M.b;
  const xs = scale(0.5, raw.length + 0.5, innerLeft, innerRight);
  el('line', { x1: innerLeft, x2: innerRight, y1: innerBottom, y2: innerBottom, class: 'axis-line' }, svg);
  const stepCount = Math.min(raw.length, 10);
  for (let kk = 0; kk <= stepCount; kk++) {
    const i = Math.round((kk / stepCount) * (raw.length - 1)) + 1;
    el('text', {
      x: xs(i),
      y: innerBottom + 14,
      'text-anchor': 'middle',
      class: 'axis-label',
      text: String(i),
    }, svg);
  }
  el('text', {
    x: innerLeft + (innerRight - innerLeft) / 2,
    y: H - 4,
    'text-anchor': 'middle',
    class: 'axis-title',
    text: 'Sample #',
  }, svg);
}

export default function EwmaCusum({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  return (
    <div className="pb-chart-card" style={{ height: height ?? 320 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'EWMA / CUSUM chart'} />
    </div>
  );
}

export { render as renderEwmaCusum };
