/**
 * Splom — Scatter Plot Matrix.
 *
 * For N dimensions, draws an N×N grid:
 *   - Diagonal: filled normal-fit density curve (PDF) for that param
 *   - Lower triangle: scatter (param[j] vs param[i])
 *   - Upper triangle: |Pearson r| as a colored cell with text
 *
 * Useful for FDC param exploration: "do RF Power and Pressure correlate?"
 *
 * Spec shape:
 *   {
 *     type: 'splom',
 *     data: rows (each row has the dimension columns),
 *     dimensions: string[],   // which columns to include in the matrix
 *     outlier_field?: string  // boolean column → mark outliers in red
 *   }
 */

'use client';

import * as React from 'react';
import {
  clear, el, mean, normPdf, pearson, readTheme, size, std, useSvgChart,
} from './lib';
import { scale } from './lib/primitives';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

const M = { t: 28, r: 14, b: 18, l: 56 };

function hexToRgba(hex: string, opacity: number): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${opacity})`;
}

interface DimStats {
  min: number;
  max: number;
  mu: number;
  sigma: number;
  arr: number[];
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const data = Array.isArray(spec.data) ? spec.data : [];
  const dims = Array.isArray(spec.dimensions) ? (spec.dimensions as string[]) : [];
  const outlierField = typeof spec.outlier_field === 'string' ? spec.outlier_field : null;
  const n = dims.length;

  if (data.length === 0 || n === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
    return;
  }

  if (spec.title) {
    el('text', { x: M.l, y: 14, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }

  const cellW = (W - M.l - M.r) / n;
  const cellH = (H - M.t - M.b) / n;

  // Pre-compute stats per dimension
  const stats: DimStats[] = dims.map((p) => {
    const arr = data
      .map((d) => Number(d[p]))
      .filter((v) => Number.isFinite(v));
    const mn = arr.length ? Math.min(...arr) : 0;
    const mx = arr.length ? Math.max(...arr) : 1;
    const pad = (mx - mn) * 0.04 || 0.5;
    return { min: mn - pad, max: mx + pad, mu: mean(arr), sigma: std(arr), arr };
  });

  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const x0 = M.l + j * cellW;
      const y0 = M.t + i * cellH;
      const innerPad = 6;
      const cx0 = x0 + innerPad;
      const cy0 = y0 + innerPad;
      const cw = cellW - innerPad * 2;
      const ch = cellH - innerPad * 2;

      // Cell border
      el('rect', { x: x0, y: y0, width: cellW, height: cellH, fill: 'none', stroke: T.grid, 'stroke-width': 1 }, svg);

      if (i === j) {
        // Diagonal: density
        el('text', {
          x: x0 + cellW / 2,
          y: y0 + 12,
          'text-anchor': 'middle',
          class: 'axis-title',
          text: dims[i],
        }, svg);
        const s = stats[i];
        if (s.sigma > 0 && Number.isFinite(s.mu)) {
          const xs = scale(s.min, s.max, cx0, cx0 + cw);
          const pts: Array<[number, number]> = [];
          const yTop = normPdf(s.mu, s.mu, s.sigma);
          if (yTop > 0) {
            for (let k = 0; k < 60; k++) {
              const v = s.min + ((s.max - s.min) * k) / 59;
              const py = cy0 + ch - (normPdf(v, s.mu, s.sigma) / yTop) * (ch * 0.85);
              pts.push([xs(v), py]);
            }
            const path =
              pts.map((p, k) => `${k === 0 ? 'M' : 'L'}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join('') +
              `L${cx0 + cw},${cy0 + ch}L${cx0},${cy0 + ch}Z`;
            el('path', {
              d: path,
              fill: hexToRgba(T.data, Math.max(0.08, T.fillOp * 0.7)),
              stroke: T.data,
              'stroke-width': T.stroke,
            }, svg);
          }
        }
      } else if (i < j) {
        // Upper triangle: correlation magnitude
        const r = pearson(stats[j].arr, stats[i].arr);
        const intensity = Math.abs(r);
        const fill = r > 0
          ? `rgba(37,99,235,${0.10 + intensity * 0.55})`
          : `rgba(220,38,38,${0.10 + intensity * 0.55})`;
        el('rect', { x: cx0, y: cy0, width: cw, height: ch, fill }, svg);
        el('text', {
          x: cx0 + cw / 2,
          y: cy0 + ch / 2 - 2,
          'text-anchor': 'middle',
          'font-family': 'var(--chart-font-mono)',
          'font-size': 14,
          fill: r > 0 ? '#1e3a8a' : '#7f1d1d',
          'font-weight': 600,
          text: `r = ${r.toFixed(2)}`,
        }, svg);
        el('text', {
          x: cx0 + cw / 2,
          y: cy0 + ch / 2 + 12,
          'text-anchor': 'middle',
          class: 'axis-label',
          text: intensity > 0.5 ? 'strong' : intensity > 0.2 ? 'moderate' : 'weak',
        }, svg);
      } else {
        // Lower triangle: scatter
        const xs = scale(stats[j].min, stats[j].max, cx0, cx0 + cw);
        const ys = scale(stats[i].min, stats[i].max, cy0 + ch, cy0);
        for (const d of data) {
          const vx = Number(d[dims[j]]);
          const vy = Number(d[dims[i]]);
          if (!Number.isFinite(vx) || !Number.isFinite(vy)) continue;
          const isOutlier = outlierField ? Boolean(d[outlierField]) : false;
          el('circle', {
            cx: xs(vx),
            cy: ys(vy),
            r: isOutlier ? T.pointR : T.pointR * 0.6,
            fill: isOutlier ? T.alert : T.data,
            'fill-opacity': isOutlier ? '0.85' : '0.6',
          }, svg);
        }
      }

      // Edge axis labels (left + bottom)
      if (j === 0) {
        const s = stats[i];
        const ys = scale(s.min, s.max, cy0 + ch, cy0);
        [s.min, (s.min + s.max) / 2, s.max].forEach((v) => {
          el('text', {
            x: M.l - 4,
            y: ys(v) + 3,
            'text-anchor': 'end',
            class: 'axis-label',
            text: Number.isFinite(v) ? v.toFixed(0) : '',
          }, svg);
        });
      }
      if (i === n - 1) {
        const s = stats[j];
        const xs = scale(s.min, s.max, cx0, cx0 + cw);
        [s.min, s.max].forEach((v) => {
          el('text', {
            x: xs(v),
            y: M.t + n * cellH + 12,
            'text-anchor': 'middle',
            class: 'axis-label',
            text: Number.isFinite(v) ? v.toFixed(0) : '',
          }, svg);
        });
      }
    }
  }
}

export default function Splom({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  // Square-ish: each cell ~ height/n; default 360 fits 5×5 reasonably.
  return (
    <div className="pb-chart-card" style={{ height: height ?? 360 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Scatter plot matrix'} />
    </div>
  );
}

export { render as renderSplom };
