/**
 * SVG DOM helpers — keeps every chart file from re-declaring the same el/clear
 * boilerplate that the reference's charts-p1..p4.js had inline.
 *
 * All functions imperatively mutate the SVG element passed in. Callers (chart
 * components) are responsible for re-running the render whenever inputs or
 * theme change — that's what `useSvgChart` (lib/useSvgChart.ts) is for.
 */

export const SVG_NS = 'http://www.w3.org/2000/svg';

export type SVGAttrValue = string | number;
export type SVGAttrs = Record<string, SVGAttrValue> & { text?: string };

/** Create an SVG element with attributes. `attrs.text` becomes `textContent`. */
export function el<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: SVGAttrs = {},
  parent?: SVGElement | null,
): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG_NS, tag) as SVGElementTagNameMap[K];
  for (const k of Object.keys(attrs)) {
    if (k === 'text') {
      node.textContent = String(attrs[k]);
    } else {
      node.setAttribute(k, String(attrs[k]));
    }
  }
  if (parent) parent.appendChild(node);
  return node;
}

/** Remove all children from an SVG (safe for re-render). */
export function clear(svg: SVGElement | null): void {
  if (!svg) return;
  while (svg.firstChild) svg.removeChild(svg.firstChild);
}

/** Current rendered size of an SVG (after CSS layout). */
export function size(svg: SVGElement | null): [number, number] {
  if (!svg) return [0, 0];
  const r = svg.getBoundingClientRect();
  return [r.width, r.height];
}
