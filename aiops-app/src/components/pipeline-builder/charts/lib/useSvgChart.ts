/**
 * useSvgChart — React hook that wires an SVG element to an imperative renderer
 * and re-runs it on (a) resize and (b) theme changes.
 *
 * Why imperative inside React: the chart code came from
 * `/Users/gill/AIOps - Charting design` which manipulates SVG by hand for
 * visual fidelity. We host that imperative core in a useEffect, but let the
 * rest of the React tree treat each chart as a regular component.
 *
 * Usage in a chart component:
 *   const ref = useSvgChart(svg => myRenderFn(svg, data, opts), [data, opts]);
 *   return <svg ref={ref} className="pb-chart" />;
 *
 * Resize: ResizeObserver on the SVG itself.
 * Theme:  MutationObserver on the closest ancestor with class `pb-chart-card`,
 *         re-rendering when its `style` attribute changes (i.e. CSS variables
 *         flipped). For most pages this never fires; it's a no-op observer.
 */

import { DependencyList, useEffect, useRef } from 'react';

export type SvgRenderer = (svg: SVGSVGElement) => void;

const PARENT_CARD_SELECTOR = '.pb-chart-card';

export function useSvgChart(
  render: SvgRenderer,
  deps: DependencyList,
): React.RefObject<SVGSVGElement | null> {
  const ref = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    const svg = ref.current;
    if (!svg) return;

    const run = () => {
      try {
        render(svg);
      } catch (err) {
        // Don't kill the page if a single chart errors during a resize burst.
        // eslint-disable-next-line no-console
        console.error('[useSvgChart] render failed', err);
      }
    };

    run();

    const ro = new ResizeObserver(run);
    ro.observe(svg);

    let mo: MutationObserver | null = null;
    const card = svg.closest(PARENT_CARD_SELECTOR);
    if (card) {
      mo = new MutationObserver(run);
      mo.observe(card, { attributes: true, attributeFilter: ['style', 'class'] });
    }

    return () => {
      ro.disconnect();
      mo?.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return ref;
}
