/**
 * HeatmapDendro — clustered heatmap with optional dendrograms.
 *
 * Two input modes:
 *   1. Pre-computed correlation matrix:
 *        spec.matrix: number[][]  N×N values in [-1, 1]
 *        spec.params: string[]    row/col labels
 *   2. Long-form data with x/y/value:
 *        spec.data: rows
 *        spec.x_column / spec.x : col label
 *        spec.y_column / spec.y[0] : row label
 *        spec.value_column      : cell value
 *
 * `spec.cluster` toggles single-linkage agglomerative clustering on
 * (1 - |value|) distance; rows + cols are reordered to put similar
 * variables next to each other.
 */

'use client';

import * as React from 'react';
import {
  clear, diverging, el, readTheme, size, tooltip, useSvgChart,
} from './lib';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

const M = { t: 64, r: 14, b: 18, l: 70 };
const DENDRO_W = 60;

interface Matrix {
  labels: string[];
  values: number[][];
}

interface DendroNode {
  id: number;
  members: number[];
  h: number;
  left?: DendroNode;
  right?: DendroNode;
}

function readMatrix(spec: ChartSpec): Matrix | null {
  if (Array.isArray(spec.matrix) && Array.isArray(spec.params)) {
    const m = spec.matrix as number[][];
    const labels = spec.params as string[];
    if (m.length === labels.length && m.every((row) => row.length === labels.length)) {
      return { labels, values: m };
    }
  }
  // Long-form aggregation
  const data = Array.isArray(spec.data) ? spec.data : [];
  const xCol = (spec.x_column as string | undefined) ?? spec.x;
  const yCol = (spec.y_column as string | undefined)
    ?? (Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : null);
  const valCol = (spec.value_column as string | undefined) ?? null;
  if (!xCol || !yCol || !valCol || data.length === 0) return null;

  const cols: string[] = [];
  const rows: string[] = [];
  const colSeen = new Set<string>();
  const rowSeen = new Set<string>();
  for (const r of data) {
    const xv = String(r[xCol] ?? '');
    const yv = String(r[yCol] ?? '');
    if (!colSeen.has(xv)) {
      colSeen.add(xv);
      cols.push(xv);
    }
    if (!rowSeen.has(yv)) {
      rowSeen.add(yv);
      rows.push(yv);
    }
  }
  const xIdx = new Map(cols.map((c, i) => [c, i]));
  const yIdx = new Map(rows.map((c, i) => [c, i]));
  const matrix: number[][] = rows.map(() => cols.map(() => NaN));
  for (const r of data) {
    const xv = xIdx.get(String(r[xCol] ?? ''));
    const yv = yIdx.get(String(r[yCol] ?? ''));
    const vv = Number(r[valCol]);
    if (xv === undefined || yv === undefined || !Number.isFinite(vv)) continue;
    matrix[yv][xv] = vv;
  }
  // For long-form mode, labels come from rows (we render square only when
  // rows == cols; otherwise reuse row labels for both axes which won't make
  // sense — but better to render than crash).
  return { labels: rows.length === cols.length ? rows : rows, values: matrix };
}

function cluster(matrix: number[][]): { order: number[]; tree: DendroNode | null } {
  const n = matrix.length;
  if (n === 0) return { order: [], tree: null };
  if (n === 1) return { order: [0], tree: { id: 0, members: [0], h: 0 } };

  const dist: number[][] = [];
  for (let i = 0; i < n; i += 1) {
    const row: number[] = [];
    for (let j = 0; j < n; j += 1) {
      const v = Number(matrix[i][j]);
      row.push(Number.isFinite(v) ? 1 - Math.abs(v) : 1);
    }
    dist.push(row);
  }
  let clusters: DendroNode[] = Array.from({ length: n }, (_, i) => ({ id: i, members: [i], h: 0 }));
  let nextId = n;
  while (clusters.length > 1) {
    let bestI = 0;
    let bestJ = 1;
    let bestD = Infinity;
    for (let i = 0; i < clusters.length; i += 1) {
      for (let j = i + 1; j < clusters.length; j += 1) {
        let d = Infinity;
        for (const a of clusters[i].members) {
          for (const b of clusters[j].members) {
            if (dist[a][b] < d) d = dist[a][b];
          }
        }
        if (d < bestD) {
          bestD = d;
          bestI = i;
          bestJ = j;
        }
      }
    }
    const left = clusters[bestI];
    const right = clusters[bestJ];
    const merged: DendroNode = {
      id: nextId,
      members: [...left.members, ...right.members],
      h: bestD,
      left,
      right,
    };
    nextId += 1;
    clusters = clusters.filter((_, k) => k !== bestI && k !== bestJ).concat(merged);
  }
  const tree = clusters[0];
  const order: number[] = [];
  function trav(node: DendroNode) {
    if (!node.left || !node.right) {
      order.push(node.members[0]);
      return;
    }
    trav(node.left);
    trav(node.right);
  }
  trav(tree);
  return { order, tree };
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const mtx = readMatrix(spec);
  if (!mtx || mtx.values.length === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
    return;
  }

  const useCluster = spec.cluster !== false; // default on
  const innerLeft = M.l;
  const innerTop = M.t;
  const innerRight = W - M.r - DENDRO_W;
  const innerBottom = H - M.b - DENDRO_W;
  const iw = innerRight - innerLeft;
  const ih = innerBottom - innerTop;

  let order: number[];
  let tree: DendroNode | null = null;
  if (useCluster) {
    const c = cluster(mtx.values);
    order = c.order;
    tree = c.tree;
  } else {
    order = mtx.labels.map((_, i) => i);
  }

  const nLabels = order.length;
  const cellW = iw / nLabels;
  const cellH = ih / nLabels;

  // Axis labels (top rotated, left horizontal)
  order.forEach((p, i) => {
    el('text', {
      x: innerLeft + i * cellW + cellW / 2,
      y: innerTop - 6,
      'text-anchor': 'middle',
      class: 'axis-label',
      transform: `rotate(-45 ${innerLeft + i * cellW + cellW / 2} ${innerTop - 6})`,
      text: mtx.labels[p],
    }, svg);
    el('text', {
      x: innerLeft - 6,
      y: innerTop + i * cellH + cellH / 2 + 3,
      'text-anchor': 'end',
      class: 'axis-label',
      text: mtx.labels[p],
    }, svg);
  });

  // Cells
  const tt = tooltip();
  for (let i = 0; i < order.length; i += 1) {
    for (let j = 0; j < order.length; j += 1) {
      const v = mtx.values[order[i]][order[j]];
      if (!Number.isFinite(v)) continue;
      const t = (v + 1) / 2; // map [-1, 1] → [0, 1] for diverging palette
      const fill = diverging(t);
      const r = el('rect', {
        x: innerLeft + j * cellW,
        y: innerTop + i * cellH,
        width: cellW,
        height: cellH,
        fill,
        stroke: '#fff',
        'stroke-width': 0.5,
      }, svg);
      (r as SVGElement).style.cursor = 'pointer';
      r.addEventListener('mouseenter', (e) => {
        const me = e as MouseEvent;
        tt.show(
          `<b>${mtx.labels[order[i]]} × ${mtx.labels[order[j]]}</b><br/>value: ${v.toFixed(3)}`,
          me.clientX, me.clientY,
        );
      });
      r.addEventListener('mouseleave', () => tt.hide());
    }
  }

  // Dendrograms (top + right)
  if (useCluster && tree && tree.left) {
    const topY0 = 6;
    const topY1 = innerTop - 12;
    const colX = (i: number) => innerLeft + i * cellW + cellW / 2;
    const indexOf = (memberLeaf: number) => order.indexOf(memberLeaf);
    function midX(node: DendroNode): number {
      if (!node.left || !node.right) return colX(indexOf(node.members[0]));
      return (midX(node.left) + midX(node.right)) / 2;
    }
    const maxH = Math.max(tree.h, 1e-6);
    function drawTop(node: DendroNode) {
      if (!node.left || !node.right) return;
      const yh = topY1 - (node.h / maxH) * (topY1 - topY0);
      const lx = midX(node.left);
      const rx = midX(node.right);
      const lyChild = node.left.left ? topY1 - (node.left.h / maxH) * (topY1 - topY0) : topY1;
      const ryChild = node.right.left ? topY1 - (node.right.h / maxH) * (topY1 - topY0) : topY1;
      el('path', {
        d: `M${lx},${lyChild} L${lx},${yh} L${rx},${yh} L${rx},${ryChild}`,
        fill: 'none',
        stroke: T.secondary,
        'stroke-width': 1,
      }, svg);
      drawTop(node.left);
      drawTop(node.right);
    }
    drawTop(tree);

    // Right (mirror)
    const leftX0 = innerRight + 8;
    const leftX1 = innerRight + DENDRO_W - 4;
    const rowY = (i: number) => innerTop + i * cellH + cellH / 2;
    function midY(node: DendroNode): number {
      if (!node.left || !node.right) return rowY(indexOf(node.members[0]));
      return (midY(node.left) + midY(node.right)) / 2;
    }
    function drawSide(node: DendroNode) {
      if (!node.left || !node.right) return;
      const xh = leftX0 + (node.h / maxH) * (leftX1 - leftX0);
      const ly = midY(node.left);
      const ry = midY(node.right);
      const lxChild = node.left.left ? leftX0 + (node.left.h / maxH) * (leftX1 - leftX0) : leftX0;
      const rxChild = node.right.left ? leftX0 + (node.right.h / maxH) * (leftX1 - leftX0) : leftX0;
      el('path', {
        d: `M${lxChild},${ly} L${xh},${ly} L${xh},${ry} L${rxChild},${ry}`,
        fill: 'none',
        stroke: T.secondary,
        'stroke-width': 1,
      }, svg);
      drawSide(node.left);
      drawSide(node.right);
    }
    drawSide(tree);
  }

  // Color legend (bottom)
  const lgX = innerLeft;
  const lgY = H - 10;
  const lgW = 100;
  const lgH = 6;
  for (let i = 0; i < lgW; i += 1) {
    el('rect', {
      x: lgX + i, y: lgY - lgH, width: 1, height: lgH,
      fill: diverging(i / lgW),
    }, svg);
  }
  el('text', { x: lgX, y: lgY + 8, class: 'axis-label', text: '-1' }, svg);
  el('text', { x: lgX + lgW, y: lgY + 8, 'text-anchor': 'end', class: 'axis-label', text: '+1' }, svg);
  el('text', { x: lgX + lgW + 8, y: lgY - 1, class: 'axis-label', text: 'value' }, svg);

  if (spec.title) {
    el('text', { x: innerLeft, y: 14, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }
}

export default function HeatmapDendro({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  return (
    <div className="pb-chart-card" style={{ height: height ?? 380 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Heatmap with dendrogram'} />
    </div>
  );
}

export { render as renderHeatmapDendro };
