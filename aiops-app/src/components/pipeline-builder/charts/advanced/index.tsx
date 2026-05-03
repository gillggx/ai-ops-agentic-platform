"use client";

/**
 * Per-chart Advanced settings registry.
 *
 * Maps ChartType → React component that renders the chart's
 * non-Simple controls. Charts not in this map have no Advanced tab
 * (StyleAdjuster shows "此 chart 無進階選項" instead).
 *
 * 14 entries cover the chart families that benefit from per-chart
 * tuning beyond palette/stroke (audit table in the Spec). The 4 Simple-
 * sufficient charts (bar / scatter / variability_gauge / probability_plot)
 * are intentionally absent.
 */

import * as React from "react";
import type { ChartType } from "../types";
import {
  ColorRow, SelectRow, SliderRow, ToggleRow, SectionHeader,
  type AdvancedProps,
} from "./_primitives";

// ── Line ──────────────────────────────────────────────────────────────
function LineAdvanced(props: AdvancedProps) {
  return (
    <>
      <SectionHeader>Rule lines (UCL/LCL/Center)</SectionHeader>
      <ColorRow {...props} label="UCL" field="_uclColor" defaultValue="#dc2626" />
      <ColorRow {...props} label="LCL" field="_lclColor" defaultValue="#dc2626" />
      <ColorRow {...props} label="Center" field="_centerColor" defaultValue="#4a5568" />
      <SectionHeader>Highlight markers</SectionHeader>
      <ColorRow {...props} label="OOC ring" field="_highlightColor" defaultValue="#dc2626" />
      <SliderRow {...props} label="Ring r" field="_highlightR" min={4} max={14} step={1} defaultValue={8} />
    </>
  );
}

// ── Box Plot ──────────────────────────────────────────────────────────
function BoxPlotAdvanced(props: AdvancedProps) {
  return (
    <>
      <ToggleRow {...props} label="Show outliers" field="show_outliers" defaultValue={true} />
      <ToggleRow {...props} label="Expanded (groups)" field="expanded" defaultValue={true} />
      <SliderRow {...props} label="IQR fill α" field="_iqrFillAlpha" min={0} max={0.6} step={0.05} defaultValue={0.18} />
      <ColorRow {...props} label="Outlier color" field="_outlierColor" defaultValue="#dc2626" />
    </>
  );
}

// ── SPLOM ─────────────────────────────────────────────────────────────
function SplomAdvanced(props: AdvancedProps) {
  return (
    <>
      <ColorRow {...props} label="Density color" field="_densityColor" defaultValue="#475569" />
      <SelectRow
        {...props}
        label="|r| palette"
        field="_corrPalette"
        defaultValue="viridis"
        options={[["viridis", "Viridis"], ["diverging", "Diverging"]]}
      />
    </>
  );
}

// ── Histogram ─────────────────────────────────────────────────────────
function HistogramAdvanced(props: AdvancedProps) {
  return (
    <>
      <SliderRow {...props} label="Bins" field="bins" min={6} max={60} step={1} defaultValue={28} />
      <ToggleRow {...props} label="Show normal fit" field="show_normal" defaultValue={true} />
      <ColorRow {...props} label="Normal curve" field="_normalColor" defaultValue="#2563eb" />
      <ColorRow {...props} label="USL/LSL line" field="_specLineColor" defaultValue="#dc2626" />
      <ToggleRow {...props} label="Show ppm" field="_showPpm" defaultValue={true} />
    </>
  );
}

// ── Xbar/R ────────────────────────────────────────────────────────────
function XbarRAdvanced(props: AdvancedProps) {
  return (
    <>
      <SectionHeader>WECO 規則顏色</SectionHeader>
      <ColorRow {...props} label="R1 (3σ outside)" field="_wecoR1Color" defaultValue="#dc2626" />
      <ColorRow {...props} label="R2 (9 same side)" field="_wecoR2Color" defaultValue="#ea580c" />
      <ColorRow {...props} label="R3 (6 trending)" field="_wecoR3Color" defaultValue="#d97706" />
      <ColorRow {...props} label="R4 (14 alternating)" field="_wecoR4Color" defaultValue="#ca8a04" />
      <ColorRow {...props} label="R5 (4 of 5 > 1σ)" field="_wecoR5Color" defaultValue="#65a30d" />
      <ColorRow {...props} label="R6 (15 within 1σ)" field="_wecoR6Color" defaultValue="#0891b2" />
      <ColorRow {...props} label="R7 (8 outside 1σ)" field="_wecoR7Color" defaultValue="#7c3aed" />
      <ColorRow {...props} label="R8 (any 2 of 3 > 2σ)" field="_wecoR8Color" defaultValue="#c026d3" />
      <SectionHeader>Sigma zones</SectionHeader>
      <ToggleRow {...props} label="Show ±σ zones" field="_showSigmaZones" defaultValue={true} />
      <ToggleRow {...props} label="Subgroup separator" field="_subgroupSeparator" defaultValue={false} />
    </>
  );
}

// ── IMR ───────────────────────────────────────────────────────────────
function ImrAdvanced(props: AdvancedProps) {
  return (
    <>
      <SectionHeader>WECO 規則顏色（同 X̄/R）</SectionHeader>
      <ColorRow {...props} label="R1" field="_wecoR1Color" defaultValue="#dc2626" />
      <ColorRow {...props} label="R2" field="_wecoR2Color" defaultValue="#ea580c" />
      <ColorRow {...props} label="R5" field="_wecoR5Color" defaultValue="#65a30d" />
      <SectionHeader>MR limits</SectionHeader>
      <ColorRow {...props} label="MR upper limit" field="_mrLimitColor" defaultValue="#dc2626" />
    </>
  );
}

// ── EWMA / CUSUM ──────────────────────────────────────────────────────
function EwmaCusumAdvanced(props: AdvancedProps) {
  return (
    <>
      <SelectRow
        {...props}
        label="Mode"
        field="mode"
        defaultValue="ewma"
        options={[["ewma", "EWMA (small-shift)"], ["cusum", "CUSUM (累積偏移)"]]}
      />
      <SliderRow {...props} label="λ (EWMA)" field="lambda" min={0.05} max={1} step={0.05} defaultValue={0.2} />
      <SliderRow {...props} label="k (CUSUM σ)" field="k" min={0.1} max={2} step={0.1} defaultValue={0.5} />
      <SliderRow {...props} label="h (CUSUM σ)" field="h" min={2} max={10} step={0.5} defaultValue={4} />
      <ColorRow {...props} label="Decision interval" field="_decisionColor" defaultValue="#dc2626" />
    </>
  );
}

// ── Pareto ────────────────────────────────────────────────────────────
function ParetoAdvanced(props: AdvancedProps) {
  return (
    <>
      <SliderRow {...props} label="80% threshold" field="cumulative_threshold" min={50} max={95} step={5} defaultValue={80} />
      <ColorRow {...props} label="Cumulative line" field="_cumulativeColor" defaultValue="#2563eb" />
      <ColorRow {...props} label="Threshold line" field="_thresholdColor" defaultValue="#dc2626" />
    </>
  );
}

// ── Parallel Coords ───────────────────────────────────────────────────
function ParallelCoordsAdvanced(props: AdvancedProps) {
  return (
    <>
      <SliderRow {...props} label="Alert below" field="alert_below" min={0} max={100} step={1} defaultValue={92} />
      <ColorRow {...props} label="Alert color" field="_alertColor" defaultValue="#dc2626" />
      <ColorRow {...props} label="Brush color" field="_brushColor" defaultValue="#2563eb" />
      <SliderRow {...props} label="Default opacity" field="_lineOpacity" min={0.05} max={1} step={0.05} defaultValue={0.35} />
    </>
  );
}

// ── Heatmap Dendro ────────────────────────────────────────────────────
function HeatmapDendroAdvanced(props: AdvancedProps) {
  return (
    <>
      <ToggleRow {...props} label="Cluster (re-order)" field="cluster" defaultValue={true} />
      <ToggleRow {...props} label="Show dendrogram" field="_showDendro" defaultValue={true} />
      <SelectRow
        {...props}
        label="Palette"
        field="_palette"
        defaultValue="diverging"
        options={[["diverging", "Diverging (-1..1)"], ["viridis", "Viridis (sequential)"]]}
      />
    </>
  );
}

// ── Wafer Heatmap ─────────────────────────────────────────────────────
function WaferHeatmapAdvanced(props: AdvancedProps) {
  return (
    <>
      <SelectRow
        {...props}
        label="Notch"
        field="notch"
        defaultValue="bottom"
        options={[["top", "Top"], ["bottom", "Bottom"], ["left", "Left"], ["right", "Right"]]}
      />
      <SelectRow
        {...props}
        label="Color mode"
        field="color_mode"
        defaultValue="viridis"
        options={[["viridis", "Viridis (連續)"], ["diverging", "Diverging (對稱)"]]}
      />
      <SliderRow {...props} label="Grid n (插值)" field="grid_n" min={20} max={200} step={10} defaultValue={60} />
      <SliderRow {...props} label="Wafer radius (mm)" field="wafer_radius_mm" min={75} max={300} step={25} defaultValue={150} />
      <ToggleRow {...props} label="Show points" field="show_points" defaultValue={true} />
    </>
  );
}

// ── Defect Stack ──────────────────────────────────────────────────────
function DefectStackAdvanced(props: AdvancedProps) {
  return (
    <>
      <SelectRow
        {...props}
        label="Notch"
        field="notch"
        defaultValue="bottom"
        options={[["top", "Top"], ["bottom", "Bottom"], ["left", "Left"], ["right", "Right"]]}
      />
      <SliderRow {...props} label="Wafer radius (mm)" field="wafer_radius_mm" min={75} max={300} step={25} defaultValue={150} />
      <SliderRow {...props} label="Marker size" field="_markerSize" min={2} max={10} step={1} defaultValue={4} />
      <SliderRow {...props} label="Marker opacity" field="_markerOpacity" min={0.2} max={1} step={0.1} defaultValue={0.7} />
    </>
  );
}

// ── Spatial Pareto ────────────────────────────────────────────────────
function SpatialParetoAdvanced(props: AdvancedProps) {
  return (
    <>
      <SelectRow
        {...props}
        label="Notch"
        field="notch"
        defaultValue="bottom"
        options={[["top", "Top"], ["bottom", "Bottom"], ["left", "Left"], ["right", "Right"]]}
      />
      <SliderRow {...props} label="Grid n (切格)" field="grid_n" min={4} max={30} step={1} defaultValue={12} />
      <SliderRow {...props} label="Wafer radius (mm)" field="wafer_radius_mm" min={75} max={300} step={25} defaultValue={150} />
    </>
  );
}

// ── Trend Wafer Maps ──────────────────────────────────────────────────
function TrendWaferMapsAdvanced(props: AdvancedProps) {
  return (
    <>
      <SliderRow {...props} label="Cols (grid 欄數)" field="cols" min={1} max={10} step={1} defaultValue={4} />
      <SliderRow {...props} label="Grid n per panel" field="grid_n" min={10} max={60} step={2} defaultValue={28} />
      <ColorRow {...props} label="PM marker" field="_pmMarkerColor" defaultValue="#dc2626" />
      <ToggleRow {...props} label="Show PM markers" field="_showPmMarker" defaultValue={true} />
    </>
  );
}

// ── Registry ──────────────────────────────────────────────────────────

export const ADVANCED_SETTINGS: Partial<Record<ChartType, React.FC<AdvancedProps>>> = {
  line: LineAdvanced,
  box_plot: BoxPlotAdvanced,
  splom: SplomAdvanced,
  histogram: HistogramAdvanced,
  xbar_r: XbarRAdvanced,
  imr: ImrAdvanced,
  ewma_cusum: EwmaCusumAdvanced,
  pareto: ParetoAdvanced,
  parallel_coords: ParallelCoordsAdvanced,
  heatmap_dendro: HeatmapDendroAdvanced,
  wafer_heatmap: WaferHeatmapAdvanced,
  defect_stack: DefectStackAdvanced,
  spatial_pareto: SpatialParetoAdvanced,
  trend_wafer_maps: TrendWaferMapsAdvanced,
};

export type { AdvancedProps } from "./_primitives";
