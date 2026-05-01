/**
 * Tooltip singleton — one floating div pinned to document.body, shared across
 * every chart on the page. Position-clamped to the viewport so it never falls
 * off the right or bottom edge.
 *
 * Why singleton: every chart file in the reference's charts-p1..p4.js attaches
 * mouseenter listeners that need a tooltip. Creating one per chart produced
 * dozens of stacked divs; sharing one keeps DOM small and z-index consistent.
 *
 * Caller pattern:
 *   const t = tooltip();
 *   el.addEventListener('mouseenter', e => t.show('<b>label</b>', e.clientX, e.clientY));
 *   el.addEventListener('mouseleave', () => t.hide());
 */

let _el: HTMLDivElement | null = null;

interface TooltipApi {
  show(html: string, clientX: number, clientY: number): void;
  hide(): void;
}

function ensureEl(): HTMLDivElement {
  if (_el && document.body.contains(_el)) return _el;
  const node = document.createElement('div');
  node.className = 'pb-chart-tt';
  node.setAttribute('role', 'tooltip');
  // Inline styles — chart-tokens.css governs colors / fonts via CSS variables.
  Object.assign(node.style, {
    position: 'fixed',
    pointerEvents: 'none',
    zIndex: '9999',
    background: 'var(--chart-bg, #fff)',
    color: 'var(--chart-ink, #1a1a17)',
    border: '1px solid var(--chart-grid-strong, #c8c6c0)',
    borderRadius: '4px',
    padding: '6px 10px',
    fontSize: '11px',
    fontFamily: 'var(--chart-font-mono, ui-monospace, "SF Mono", Menlo, monospace)',
    boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
    display: 'none',
    maxWidth: '280px',
    lineHeight: '1.5',
  } as Partial<CSSStyleDeclaration>);
  document.body.appendChild(node);
  _el = node;
  return node;
}

export function tooltip(): TooltipApi {
  return {
    show(html: string, x: number, y: number) {
      const node = ensureEl();
      node.innerHTML = html;
      node.style.display = 'block';
      // Measure after content set, then clamp to viewport.
      const r = node.getBoundingClientRect();
      const px = Math.min(x + 12, window.innerWidth - r.width - 4);
      const py = Math.min(y + 12, window.innerHeight - r.height - 4);
      node.style.left = `${px}px`;
      node.style.top = `${py}px`;
    },
    hide() {
      if (_el) _el.style.display = 'none';
    },
  };
}

/** Tear down the singleton — called by tests; not needed in production. */
export function destroyTooltip(): void {
  if (_el && _el.parentNode) _el.parentNode.removeChild(_el);
  _el = null;
}
