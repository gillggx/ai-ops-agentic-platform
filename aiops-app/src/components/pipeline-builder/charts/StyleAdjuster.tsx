/**
 * StyleAdjuster — per-chart popover for live theme tweaking.
 *
 * Ported from /Users/gill/AIOps - Charting design/style-adjuster.jsx.
 * Sets CSS custom properties on the chart-card wrapper; the chart's
 * `useSvgChart` MutationObserver picks up the style change and re-renders
 * via `readTheme(svg)` reading the new values. No chart code is touched.
 *
 * Usage in a card host:
 *   const [theme, setTheme] = useState<ChartCardTheme>({...DEFAULT_THEME});
 *   <div className="pb-chart-card" style={themeStyle(theme)}>
 *     <StyleAdjuster theme={theme} setTheme={setTheme} />
 *     <ChartComponent spec={...} />
 *   </div>
 */

'use client';

import * as React from 'react';

export interface ChartCardTheme {
  palette: keyof typeof PALETTES;
  data: string;
  secondary: string;
  alert: string;
  grid: string;
  bg: string;
  stroke: number;
  pointR: number;
  fillOp: number;
  axisFs: number;
  titleFs: number;
  showGrid: boolean;
}

export const PALETTES = {
  Default: { data: '#2563EB', secondary: '#64748B', alert: '#DC2626', grid: '#e8e7e3', bg: '#ffffff' },
  Mono: { data: '#1a1a17', secondary: '#75736d', alert: '#DC2626', grid: '#e8e7e3', bg: '#ffffff' },
  Teal: { data: '#0d9488', secondary: '#475569', alert: '#dc2626', grid: '#e8e7e3', bg: '#ffffff' },
  Indigo: { data: '#4f46e5', secondary: '#6b7280', alert: '#e11d48', grid: '#e8e7e3', bg: '#ffffff' },
  Forest: { data: '#15803d', secondary: '#57534e', alert: '#b91c1c', grid: '#e8e7e3', bg: '#ffffff' },
  Dark: { data: '#60a5fa', secondary: '#94a3b8', alert: '#fca5a5', grid: '#262624', bg: '#1a1a17' },
  HighContrast: { data: '#000000', secondary: '#525252', alert: '#dc2626', grid: '#cccccc', bg: '#ffffff' },
} as const;

export const DEFAULT_THEME: ChartCardTheme = {
  palette: 'Default',
  data: '#2563EB',
  secondary: '#64748B',
  alert: '#DC2626',
  grid: '#e8e7e3',
  bg: '#ffffff',
  stroke: 1.4,
  pointR: 2.6,
  fillOp: 0.18,
  axisFs: 9.5,
  titleFs: 11,
  showGrid: true,
};

/** CSS custom properties to apply on the chart-card wrapper. */
export function themeStyle(theme: ChartCardTheme): React.CSSProperties {
  const isDark = theme.bg.toLowerCase() === '#1a1a17';
  return {
    // CSS vars (TS doesn't know these are kebab-case CSS variables, hence the
    // `as React.CSSProperties` cast at the end).
    '--chart-data': theme.data,
    '--chart-secondary': theme.secondary,
    '--chart-alert': theme.alert,
    '--chart-grid': theme.showGrid ? theme.grid : 'transparent',
    '--chart-grid-strong': theme.grid,
    '--chart-bg': theme.bg,
    '--chart-stroke': String(theme.stroke),
    '--chart-fill-op': String(theme.fillOp),
    '--chart-point-r': String(theme.pointR),
    '--chart-axis-fs': `${theme.axisFs}px`,
    '--chart-title-fs': `${theme.titleFs}px`,
    color: isDark ? '#f8f8f5' : 'inherit',
    background: theme.bg,
  } as React.CSSProperties;
}

interface Props {
  theme: ChartCardTheme;
  setTheme: React.Dispatch<React.SetStateAction<ChartCardTheme>>;
}

export default function StyleAdjuster({ theme, setTheme }: Props) {
  const [open, setOpen] = React.useState(false);
  const popRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (popRef.current && !popRef.current.contains(target)) setOpen(false);
    };
    // defer so the click that opened doesn't immediately close us
    const t = window.setTimeout(() => document.addEventListener('mousedown', onDoc), 0);
    return () => {
      window.clearTimeout(t);
      document.removeEventListener('mousedown', onDoc);
    };
  }, [open]);

  const setK = <K extends keyof ChartCardTheme>(k: K, v: ChartCardTheme[K]) =>
    setTheme((t) => ({ ...t, [k]: v }));

  const applyPalette = (name: keyof typeof PALETTES) => {
    const p = PALETTES[name];
    setTheme((t) => ({ ...t, palette: name, ...p }));
  };

  const reset = () => setTheme({ ...DEFAULT_THEME });

  return (
    <>
      <button
        type="button"
        className={`pb-style-btn${open ? ' on' : ''}`}
        onClick={() => setOpen((o) => !o)}
        title="Style adjuster"
      >
        ✦
      </button>
      {open && (
        <div
          className="pb-style-pop"
          ref={popRef}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="pb-style-h">
            <span>Style</span>
            <button type="button" onClick={reset}>
              Reset
            </button>
          </div>

          <div className="pb-style-row">
            <label>Palette</label>
            <select
              value={theme.palette}
              onChange={(e) => applyPalette(e.target.value as keyof typeof PALETTES)}
            >
              {Object.keys(PALETTES).map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          {(['data', 'alert', 'secondary', 'bg', 'grid'] as const).map((k) => (
            <div key={k} className="pb-style-row">
              <label>{k === 'bg' ? 'Background' : k.charAt(0).toUpperCase() + k.slice(1)}</label>
              <input
                type="color"
                value={theme[k]}
                onChange={(e) => setK(k, e.target.value)}
              />
              <span className="pb-style-val">{theme[k]}</span>
            </div>
          ))}

          <div className="pb-style-h">Sizing</div>
          <div className="pb-style-row">
            <label>Stroke</label>
            <input type="range" min={0.5} max={4} step={0.1} value={theme.stroke}
              onChange={(e) => setK('stroke', +e.target.value)} />
            <span className="pb-style-val">{theme.stroke.toFixed(1)}</span>
          </div>
          <div className="pb-style-row">
            <label>Point r</label>
            <input type="range" min={1} max={6} step={0.2} value={theme.pointR}
              onChange={(e) => setK('pointR', +e.target.value)} />
            <span className="pb-style-val">{theme.pointR.toFixed(1)}</span>
          </div>
          <div className="pb-style-row">
            <label>Fill α</label>
            <input type="range" min={0} max={0.9} step={0.05} value={theme.fillOp}
              onChange={(e) => setK('fillOp', +e.target.value)} />
            <span className="pb-style-val">{theme.fillOp.toFixed(2)}</span>
          </div>
          <div className="pb-style-row">
            <label>Axis fs</label>
            <input type="range" min={8} max={14} step={0.5} value={theme.axisFs}
              onChange={(e) => setK('axisFs', +e.target.value)} />
            <span className="pb-style-val">{theme.axisFs}</span>
          </div>
          <div className="pb-style-row">
            <label>Show grid</label>
            <button
              type="button"
              className={`pb-style-toggle${theme.showGrid ? ' on' : ''}`}
              onClick={() => setK('showGrid', !theme.showGrid)}
            >
              {theme.showGrid ? 'ON' : 'OFF'}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
