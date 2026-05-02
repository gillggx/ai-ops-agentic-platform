/**
 * Wafer-domain helpers — IDW spatial interpolation + wafer outline drawing.
 *
 * Used by WaferHeatmap, SpatialPareto, and TrendWaferMaps. Coordinates are
 * in millimeters (centered on the wafer; +x right, +y up). The `notch`
 * marks the standard alignment notch position (standard SEMI 200/300mm
 * convention is bottom).
 */

import { el } from './svg-utils';

export type Notch = 'top' | 'bottom' | 'left' | 'right';

export interface WaferPoint {
  x: number;
  y: number;
  v: number;
}

/**
 * Inverse-distance-weighted interpolation onto a square grid.
 * Returns gridN×gridN matrix; cells outside wafer radius are null.
 */
export function idwGrid(
  points: ReadonlyArray<WaferPoint>,
  R: number,
  gridN: number,
  power = 2,
): Array<Array<number | null>> {
  const cell = (2 * R) / gridN;
  const grid: Array<Array<number | null>> = [];
  for (let i = 0; i < gridN; i++) {
    const row: Array<number | null> = [];
    for (let j = 0; j < gridN; j++) {
      const gx = -R + (j + 0.5) * cell;
      const gy = -R + (i + 0.5) * cell;
      if (gx * gx + gy * gy > R * R) {
        row.push(null);
        continue;
      }
      let num = 0;
      let den = 0;
      let exact = false;
      for (const p of points) {
        const dx = gx - p.x;
        const dy = gy - p.y;
        const d2 = dx * dx + dy * dy;
        if (d2 < 0.001) {
          num = p.v;
          den = 1;
          exact = true;
          break;
        }
        const w = 1 / Math.pow(d2, power / 2);
        num += w * p.v;
        den += w;
      }
      row.push(exact ? num : den > 0 ? num / den : null);
    }
    grid.push(row);
  }
  return grid;
}

/**
 * Draw a circular wafer outline + notch flag onto an SVG.
 * Coordinates are pixel space (cx, cy = wafer center on screen, R = pixel radius).
 */
export function drawWaferOutline(
  svg: SVGElement,
  cx: number,
  cy: number,
  R: number,
  notch: Notch = 'bottom',
  strokeColor = '#1a1a17',
): void {
  el('circle', { cx, cy, r: R, fill: 'none', stroke: strokeColor, 'stroke-width': 1.4 }, svg);
  let nx = cx;
  let ny = cy;
  if (notch === 'bottom') ny = cy + R;
  else if (notch === 'top') ny = cy - R;
  else if (notch === 'left') nx = cx - R;
  else nx = cx + R;
  const horizontal = notch === 'bottom' || notch === 'top';
  const nLen = R * 0.06;
  if (horizontal) {
    const yIn = notch === 'bottom' ? -nLen : nLen;
    el('path', {
      d: `M${nx - nLen},${ny} L${nx},${ny + yIn} L${nx + nLen},${ny} Z`,
      fill: '#fff',
      stroke: strokeColor,
      'stroke-width': 1.2,
    }, svg);
  } else {
    const xIn = notch === 'left' ? nLen : -nLen;
    el('path', {
      d: `M${nx},${ny - nLen} L${nx + xIn},${ny} L${nx},${ny + nLen} Z`,
      fill: '#fff',
      stroke: strokeColor,
      'stroke-width': 1.2,
    }, svg);
  }
}
