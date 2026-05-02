/**
 * dualControlPanel — shared two-panel control-chart renderer used by both
 * XbarR and IMR. Top panel + bottom panel share the X axis (subgroup index).
 *
 * Each panel takes `{values, CL, UCL, LCL, violations}` so the caller owns
 * the statistical model (σ estimation, WECO checks). The renderer just
 * draws.
 */

import { clear, el, size, type SVGAttrs } from './svg-utils';
import { readTheme, type ChartTheme } from './theme';
import { scale, ticks } from './primitives';
import { tooltip } from './tooltip';

export interface ControlPanelData {
  values: number[];
  CL: number;
  UCL: number;
  LCL: number;
  /** Per-point violation reason (null = OK). */
  violations: Array<string | null>;
  /** Estimated σ used for in-tooltip annotation. Optional. */
  sigma?: number;
}

export interface DualPanelOpts {
  topLabel?: string;
  botLabel?: string;
  /** Top-panel height ratio (0.5..0.7). Default 0.58 matches the reference. */
  ratio?: number;
  /** Optional subgroup-id formatter (default "1", "2", …). */
  formatX?: (idx: number) => string;
  /** Title rendered top-left. */
  title?: string;
}

const M = { t: 22, r: 56, b: 32, l: 60 };

function hexToRgba(hex: string, opacity: number): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${opacity})`;
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

function drawPanel(
  svg: SVGSVGElement,
  T: ChartTheme,
  panel: ControlPanelData,
  label: string,
  yTop: number,
  panelH: number,
  innerLeft: number,
  innerRight: number,
  xs: (i: number) => number,
) {
  const { values, CL, UCL, LCL, violations } = panel;
  if (values.length === 0) return;

  const allV = [...values.filter((v) => Number.isFinite(v)), UCL, LCL].filter((v) => Number.isFinite(v));
  if (allV.length === 0) return;
  const vMin = Math.min(...allV);
  const vMax = Math.max(...allV);
  const pad = (vMax - vMin) * 0.08 || 0.5;
  const y = scale(vMin - pad, vMax + pad, yTop + panelH, yTop);

  // Out-of-spec band (faint alert tint between LCL and UCL is the "good" zone;
  // we tint OUTSIDE the limits to draw the eye to violations.)
  // Below LCL
  if (Number.isFinite(LCL)) {
    const yLcl = y(LCL);
    el('rect', {
      x: innerLeft,
      y: yLcl,
      width: innerRight - innerLeft,
      height: Math.max(0, yTop + panelH - yLcl),
      fill: hexToRgba(T.alert, 0.04),
    }, svg);
  }
  // Above UCL
  if (Number.isFinite(UCL)) {
    const yUcl = y(UCL);
    el('rect', {
      x: innerLeft,
      y: yTop,
      width: innerRight - innerLeft,
      height: Math.max(0, yUcl - yTop),
      fill: hexToRgba(T.alert, 0.04),
    }, svg);
  }

  // Y-axis grid + tick labels
  ticks(vMin - pad, vMax + pad, 4).forEach((v) => {
    const yy = y(v);
    el('line', { x1: innerLeft, x2: innerRight, y1: yy, y2: yy, class: 'grid-line' }, svg);
    el('text', { x: innerLeft - 6, y: yy + 3, 'text-anchor': 'end', class: 'axis-label', text: v.toFixed(2) }, svg);
  });

  // Control + center lines
  const yCL = y(CL);
  const yUCL = y(UCL);
  const yLCL = y(LCL);
  el('line', {
    x1: innerLeft, x2: innerRight, y1: yCL, y2: yCL,
    stroke: T.ink, 'stroke-width': 1, 'stroke-dasharray': '2 4',
  }, svg);
  if (Number.isFinite(UCL)) {
    el('line', {
      x1: innerLeft, x2: innerRight, y1: yUCL, y2: yUCL,
      stroke: T.alert, 'stroke-width': 1.2, 'stroke-dasharray': '6 4',
    }, svg);
  }
  if (Number.isFinite(LCL)) {
    el('line', {
      x1: innerLeft, x2: innerRight, y1: yLCL, y2: yLCL,
      stroke: T.alert, 'stroke-width': 1.2, 'stroke-dasharray': '6 4',
    }, svg);
  }

  // Right-edge labels (UCL / CL / LCL)
  const monoAttr: SVGAttrs = { 'font-family': 'var(--chart-font-mono)', 'font-size': 9.5 };
  if (Number.isFinite(UCL)) {
    el('text', { x: innerRight + 4, y: yUCL + 3, ...monoAttr, fill: T.alert, text: `UCL ${UCL.toFixed(2)}` }, svg);
  }
  el('text', { x: innerRight + 4, y: yCL + 3, ...monoAttr, fill: T.ink, text: `CL ${CL.toFixed(2)}` }, svg);
  if (Number.isFinite(LCL)) {
    el('text', { x: innerRight + 4, y: yLCL + 3, ...monoAttr, fill: T.alert, text: `LCL ${LCL.toFixed(2)}` }, svg);
  }

  // Series line
  const points: Array<[number, number]> = values.map((v, i) => [
    xs(i + 1),
    Number.isFinite(v) ? y(v) : NaN,
  ]);
  el('path', {
    d: buildPath(points),
    fill: 'none',
    stroke: T.data,
    'stroke-width': T.stroke,
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
  }, svg);

  // Points + violation markers
  const tt = tooltip();
  values.forEach((v, i) => {
    if (!Number.isFinite(v)) return;
    const cx = xs(i + 1);
    const cy = y(v);
    const viol = violations[i] ?? null;
    const dot = el('circle', {
      cx,
      cy,
      r: viol ? T.pointR + 1.8 : T.pointR,
      fill: viol ? T.alert : T.bg,
      stroke: viol ? T.alert : T.data,
      'stroke-width': 1.5,
    }, svg);
    (dot as SVGElement).style.cursor = 'pointer';
    dot.addEventListener('mouseenter', (e) => {
      const me = e as MouseEvent;
      tt.show(
        `<b>Subgroup ${i + 1}</b><br/>${label}: ${v.toFixed(3)}` +
        (viol ? `<br/><span style="color:${T.alert}">⚠ ${viol}</span>` : ''),
        me.clientX,
        me.clientY,
      );
    });
    dot.addEventListener('mouseleave', () => tt.hide());
  });

  // Panel label (top-left of panel)
  el('text', {
    x: innerLeft,
    y: yTop - 6,
    'font-family': 'var(--chart-font-sans)',
    'font-size': 11,
    'font-weight': 600,
    fill: T.ink,
    text: label,
  }, svg);
}

export function renderDualPanel(
  svg: SVGSVGElement,
  top: ControlPanelData,
  bot: ControlPanelData,
  opts: DualPanelOpts = {},
) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const innerLeft = M.l;
  const innerRight = W - M.r;
  const innerTop = M.t;
  const innerBottom = H - M.b;
  const gap = 18;
  const totalH = innerBottom - innerTop - gap;
  const ratio = Math.min(0.7, Math.max(0.4, opts.ratio ?? 0.58));
  const h1 = totalH * ratio;
  const h2 = totalH * (1 - ratio);
  const y1Top = innerTop;
  const y2Top = innerTop + h1 + gap;

  const xs = scale(0.5, top.values.length + 0.5, innerLeft, innerRight);

  if (opts.title) {
    el('text', { x: innerLeft, y: 14, 'text-anchor': 'start', class: 'axis-title', text: opts.title }, svg);
  }

  drawPanel(svg, T, top, opts.topLabel ?? 'X̄', y1Top, h1, innerLeft, innerRight, xs);
  drawPanel(svg, T, bot, opts.botLabel ?? 'R', y2Top, h2, innerLeft, innerRight, xs);

  // Shared X axis (bottom of bottom panel)
  el('line', {
    x1: innerLeft,
    x2: innerRight,
    y1: y2Top + h2,
    y2: y2Top + h2,
    class: 'axis-line',
  }, svg);
  const stepCount = Math.min(top.values.length, 10);
  const fmt = opts.formatX ?? ((i: number) => String(i));
  for (let k = 0; k <= stepCount; k++) {
    const i = Math.round((k / stepCount) * (top.values.length - 1)) + 1;
    el('text', {
      x: xs(i),
      y: y2Top + h2 + 14,
      'text-anchor': 'middle',
      class: 'axis-label',
      text: fmt(i),
    }, svg);
  }
  el('text', {
    x: innerLeft + (innerRight - innerLeft) / 2,
    y: H - 4,
    'text-anchor': 'middle',
    class: 'axis-title',
    text: 'Subgroup #',
  }, svg);
}
