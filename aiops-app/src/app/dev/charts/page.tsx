/**
 * Chart engine preview page (dev only).
 *
 * Renders all 18 chart components from the new SVG engine using mock data.
 * Sole purpose: visual sign-off on Stage 1 before we commit to wiring the
 * dispatcher in Stage 4 and migrating active pipelines in Stage 5.
 *
 * Route: /dev/charts  (no auth gating in dev mode; remove this folder before
 * Stage 6 cleanup)
 */

'use client';

import * as React from 'react';
import {
  LineChart, BarChart, ScatterChart,
  BoxPlot, Splom, Histogram,
  XbarR, IMR, EwmaCusum,
  Pareto, VariabilityGauge, ParallelCoords, ProbabilityPlot, HeatmapDendro,
  WaferHeatmap, DefectStack, SpatialPareto, TrendWaferMaps,
} from '@/components/pipeline-builder/charts';
import '@/styles/chart-tokens.css';
import {
  lineSpec, barSpec, scatterSpec,
  boxPlotSpec, splomSpec, histogramSpec,
  xbarRSpec, imrSpec, ewmaCusumSpec,
  paretoSpec, variabilityGaugeSpec, parallelCoordsSpec, probabilityPlotSpec, heatmapDendroSpec,
  waferHeatmapSpec, defectStackSpec, spatialParetoSpec, trendWaferMapsSpec,
} from './mock-data';

interface CardProps {
  idx: number;
  group: string;
  title: string;
  hint: string;
  children: React.ReactNode;
  /** Make the card span both columns (e.g. trend grid). */
  wide?: boolean;
  /** Override card height — default lets the chart's own height drive. */
  height?: number;
}

function Card({ idx, group, title, hint, children, wide, height }: CardProps) {
  return (
    <div
      style={{
        gridColumn: wide ? 'span 2' : undefined,
        background: '#fff',
        border: '1px solid #d8d6d0',
        borderRadius: 6,
        padding: '14px 16px',
        boxShadow: '0 1px 0 rgba(0,0,0,0.02)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 4 }}>
        <span
          style={{
            fontFamily: 'JetBrains Mono, ui-monospace, monospace',
            fontSize: 10,
            color: '#75736d',
            letterSpacing: '0.5px',
            textTransform: 'uppercase',
          }}
        >
          {String(idx).padStart(2, '0')} · {group}
        </span>
      </div>
      <div
        style={{
          fontFamily: 'Inter Tight, sans-serif',
          fontWeight: 600,
          fontSize: 14,
          color: '#1a1a17',
          marginBottom: 2,
        }}
      >
        {title}
      </div>
      <div style={{ fontSize: 11, color: '#75736d', marginBottom: 10 }}>{hint}</div>
      <div style={{ width: '100%', height: height ?? undefined, minHeight: 240 }}>
        {children}
      </div>
    </div>
  );
}

export default function ChartsPreviewPage() {
  const [cusumMode, setCusumMode] = React.useState<'ewma' | 'cusum'>('ewma');
  const [boxExpanded, setBoxExpanded] = React.useState(true);

  const boxSpec = React.useMemo(() => {
    const spec = boxPlotSpec();
    return { ...spec, expanded: boxExpanded };
  }, [boxExpanded]);

  return (
    <div
      style={{
        padding: '24px 28px',
        background: '#fafaf8',
        minHeight: '100vh',
        fontFamily: 'Inter Tight, sans-serif',
        color: '#1a1a17',
      }}
    >
      {/* Header */}
      <div style={{ marginBottom: 22 }}>
        <div
          style={{
            fontFamily: 'JetBrains Mono, ui-monospace, monospace',
            fontSize: 11,
            color: '#75736d',
            letterSpacing: '0.5px',
            textTransform: 'uppercase',
          }}
        >
          /dev/charts · stage 1 sign-off preview
        </div>
        <h1 style={{ fontSize: 24, margin: '4px 0 4px 0', fontWeight: 700 }}>
          Chart Engine — 18 charts
        </h1>
        <p style={{ fontSize: 13, color: '#4a4a45', margin: 0, maxWidth: 720 }}>
          Mock-data preview for the new SVG chart engine. None of these are
          wired to the live dispatcher yet — what you see here is exactly what
          Stage 4 will surface in Pipeline Builder + Alarm Detail. Click
          / hover / drag where it makes sense (BoxPlot bracket toggles
          collapse, ParallelCoords axes accept brushes, DefectStack legend
          toggles per-code visibility).
        </p>
      </div>

      {/* Grid: 2 columns on wide screens, 1 on narrow */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))',
          gap: 14,
        }}
      >
        {/* Primitives */}
        <Card
          idx={1}
          group="primitive"
          title="LineChart — SPC trend with rules + highlight + series_field"
          hint="Backward-compat path for current block_chart(line) usage."
          height={300}
        >
          <LineChart spec={lineSpec()} height={300} />
        </Card>

        <Card
          idx={2}
          group="primitive"
          title="BarChart — grouped bars with threshold line"
          hint="Highlight (red dashed border) marks rows where severity === 'high'."
          height={280}
        >
          <BarChart spec={barSpec()} height={280} />
        </Card>

        <Card
          idx={3}
          group="primitive"
          title="ScatterChart — RF Power vs Thickness"
          hint="series_field='tool' splits into one trace per tool."
          height={280}
        >
          <ScatterChart spec={scatterSpec()} height={280} />
        </Card>

        {/* EDA */}
        <Card
          idx={4}
          group="eda"
          title="BoxPlot — Tool / Chamber thickness"
          hint={`Click "ETCH-XX" outer label to ${boxExpanded ? 'collapse' : 'expand'}; outliers in red.`}
          height={320}
        >
          <BoxPlot spec={boxSpec} height={320} />
          <div style={{ marginTop: 8 }}>
            <button
              onClick={() => setBoxExpanded((v) => !v)}
              style={{
                padding: '4px 10px',
                fontSize: 11,
                fontFamily: 'JetBrains Mono, monospace',
                background: '#f4f4f1',
                border: '1px solid #c8c6c0',
                borderRadius: 3,
                cursor: 'pointer',
              }}
            >
              {boxExpanded ? 'Collapse to tool only' : 'Expand chambers'}
            </button>
          </div>
        </Card>

        <Card
          idx={5}
          group="eda"
          title="Splom — FDC parameter matrix"
          hint="Diagonal: density. Lower: scatter. Upper: |Pearson r| color."
          wide
          height={460}
        >
          <Splom spec={splomSpec()} height={460} />
        </Card>

        <Card
          idx={6}
          group="eda"
          title="Histogram — CD spec window"
          hint="USL/LSL/target lines + normal fit + Cpk annotation."
          height={300}
        >
          <Histogram spec={histogramSpec()} height={300} />
        </Card>

        {/* SPC */}
        <Card
          idx={7}
          group="spc"
          title="X̄-R Chart — drift injection (g18-g23)"
          hint="WECO R1-R8 highlights violations; subgroup σ via R̄/d2(n=5)."
          wide
          height={380}
        >
          <XbarR spec={xbarRSpec()} height={380} />
        </Card>

        <Card
          idx={8}
          group="spc"
          title="I-MR — single shot @ obs 32"
          hint="Individual + moving-range; M̄R/d2(2) σ estimation."
          wide
          height={380}
        >
          <IMR spec={imrSpec()} height={380} />
        </Card>

        <Card
          idx={9}
          group="spc"
          title={cusumMode === 'ewma' ? 'EWMA — small shift @ t=51' : 'CUSUM — cumulative drift'}
          hint="Toggle between EWMA (time-varying limits) and CUSUM (SH/SL) modes."
          wide
          height={340}
        >
          <EwmaCusum spec={ewmaCusumSpec(cusumMode)} height={340} />
          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
            {(['ewma', 'cusum'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setCusumMode(m)}
                style={{
                  padding: '4px 10px',
                  fontSize: 11,
                  fontFamily: 'JetBrains Mono, monospace',
                  background: cusumMode === m ? '#2563EB' : '#f4f4f1',
                  color: cusumMode === m ? '#fff' : '#1a1a17',
                  border: '1px solid #c8c6c0',
                  borderRadius: 3,
                  cursor: 'pointer',
                  textTransform: 'uppercase',
                }}
              >
                {m}
              </button>
            ))}
          </div>
        </Card>

        {/* Diagnostic */}
        <Card
          idx={10}
          group="diagnostic"
          title="Pareto — defect attribution"
          hint="Bars sort descending; cumulative line crosses 80% reference."
          height={340}
        >
          <Pareto spec={paretoSpec()} height={340} />
        </Card>

        <Card
          idx={11}
          group="diagnostic"
          title="Variability Gauge — Lot › Wafer › Tool"
          hint="Jittered points + per-group mean line + dashed step connecting means."
          wide
          height={360}
        >
          <VariabilityGauge spec={variabilityGaugeSpec()} height={360} />
        </Card>

        <Card
          idx={12}
          group="diagnostic"
          title="Parallel Coordinates — recipe profile"
          hint="Drag any axis to brush a range; double-click axis to clear. Yield<92 in red."
          wide
          height={340}
        >
          <ParallelCoords spec={parallelCoordsSpec()} height={340} />
        </Card>

        <Card
          idx={13}
          group="diagnostic"
          title="Probability Plot — Anderson-Darling"
          hint="Q-Q vs theoretical normal. AD p-value annotated top-right."
          height={340}
        >
          <ProbabilityPlot spec={probabilityPlotSpec()} height={340} />
        </Card>

        <Card
          idx={14}
          group="diagnostic"
          title="Heatmap + Dendrogram — FDC correlations"
          hint="Single-linkage clustering reorders rows/cols by similarity."
          wide
          height={420}
        >
          <HeatmapDendro spec={heatmapDendroSpec()} height={420} />
        </Card>

        {/* Wafer */}
        <Card
          idx={15}
          group="wafer"
          title="Wafer Heatmap — 49-site thickness"
          hint="IDW interpolation + measurement points + stats footer."
          height={420}
        >
          <WaferHeatmap spec={waferHeatmapSpec()} height={420} />
        </Card>

        <Card
          idx={16}
          group="wafer"
          title="Defect Stack — multi-wafer overlay"
          hint="Click legend swatch to toggle a defect type. Particles cluster upper-left."
          height={420}
        >
          <DefectStack spec={defectStackSpec()} height={420} />
        </Card>

        <Card
          idx={17}
          group="wafer"
          title="Spatial Pareto — yield zone"
          hint="Worst cell outlined in black; lower-right quadrant has injected drop."
          height={420}
        >
          <SpatialPareto spec={spatialParetoSpec()} height={420} />
        </Card>

        <Card
          idx={18}
          group="wafer"
          title="Trend Wafer Maps — pre/post PM (Mar 30)"
          hint="Small multiples with shared color domain; PM day marked dashed alert."
          wide
          height={300}
        >
          <TrendWaferMaps spec={trendWaferMapsSpec()} height={300} />
        </Card>
      </div>

      <div style={{ marginTop: 32, fontSize: 12, color: '#75736d' }}>
        18/18 charts rendered · all data is synthetic / seeded ·{' '}
        <a
          href="https://github.com/gillggx/ai-ops-agentic-platform/tree/main/aiops-app/src/components/pipeline-builder/charts"
          style={{ color: '#2563EB' }}
        >
          source on GitHub
        </a>
      </div>
    </div>
  );
}
