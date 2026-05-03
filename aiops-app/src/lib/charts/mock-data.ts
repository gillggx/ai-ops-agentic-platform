/**
 * Mock data generators for the chart preview page.
 *
 * All datasets use a seeded PRNG (mulberry32) so re-renders are deterministic.
 * Adapted from /Users/gill/AIOps - Charting design/data.js — the same shapes
 * the reference HTML uses, repackaged into ChartSpec inputs.
 */

import type { ChartSpec } from '@/components/pipeline-builder/charts';

// ── PRNG + helpers ──────────────────────────────────────────────────────────

function mulberry32(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function randn(r: () => number, mu = 0, sigma = 1): number {
  let u = 0;
  let v = 0;
  while (u === 0) u = r();
  while (v === 0) v = r();
  return mu + sigma * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

const TOOLS = ['ETCH-01', 'ETCH-02', 'ETCH-03', 'ETCH-04'];
const CHAMBERS = ['A', 'B', 'C', 'D'];
const DEFECT_CODES = ['Particle', 'Scratch', 'Residue', 'Pattern', 'Bridge', 'Open', 'Void', 'Other'];

// ── Primitives (PR-B) ───────────────────────────────────────────────────────

export function lineSpec(): ChartSpec {
  // SPC-style trend with UCL/LCL/Center + a few OOC points highlighted
  const r = mulberry32(101);
  const data = [];
  const center = 500;
  const sigma = 8;
  for (let i = 0; i < 60; i += 1) {
    let v = randn(r, center, sigma);
    if (i === 12 || i === 28 || i === 47) v = center + 35; // injected OOC
    data.push({
      eventTime: new Date(Date.now() - (60 - i) * 3600000).toISOString(),
      value: v,
      is_ooc: Math.abs(v - center) > 3 * sigma,
      tool: TOOLS[i % TOOLS.length],
    });
  }
  return {
    type: 'line',
    title: 'EQP-01 SPC X̄ trend (legacy line + rules)',
    data,
    x: 'eventTime',
    y: ['value'],
    rules: [
      { value: center + 3 * sigma, label: 'UCL', style: 'danger' },
      { value: center, label: 'CL', style: 'center' },
      { value: center - 3 * sigma, label: 'LCL', style: 'danger' },
    ],
    highlight: { field: 'is_ooc', eq: true },
    series_field: 'tool',
  };
}

export function barSpec(): ChartSpec {
  return {
    type: 'bar',
    title: 'OOC count per equipment (last 24h)',
    data: [
      { eqp: 'EQP-01', count: 12, severity: 'high' },
      { eqp: 'EQP-02', count: 4, severity: 'low' },
      { eqp: 'EQP-03', count: 8, severity: 'medium' },
      { eqp: 'EQP-04', count: 17, severity: 'high' },
      { eqp: 'EQP-05', count: 2, severity: 'low' },
      { eqp: 'EQP-06', count: 6, severity: 'medium' },
    ],
    x: 'eqp',
    y: ['count'],
    rules: [{ value: 10, label: 'threshold', style: 'warning' }],
    highlight: { field: 'severity', eq: 'high' },
  };
}

export function scatterSpec(): ChartSpec {
  const r = mulberry32(202);
  const data = [];
  for (let i = 0; i < 200; i += 1) {
    const rfp = randn(r, 1200, 40);
    // mild correlation: thickness drifts with RF Power
    const thickness = 500 + (rfp - 1200) * 0.06 + randn(r, 0, 1.5);
    data.push({ rf_power: rfp, thickness, tool: TOOLS[i % TOOLS.length] });
  }
  return {
    type: 'scatter',
    title: 'RF Power vs Thickness (correlation)',
    data,
    x: 'rf_power',
    y: ['thickness'],
    series_field: 'tool',
  };
}

// ── EDA (PR-C) ──────────────────────────────────────────────────────────────

export function boxPlotSpec(): ChartSpec {
  const r = mulberry32(11);
  const data: Array<Record<string, unknown>> = [];
  TOOLS.forEach((tool, ti) => {
    CHAMBERS.forEach((ch, ci) => {
      const baseMu = 502 + (ti === 2 ? 4 : 0) + (ti === 3 && ci === 1 ? -6 : 0);
      const sigma = 1.2 + (ti === 2 ? 0.8 : 0);
      const values: number[] = [];
      for (let i = 0; i < 60; i += 1) {
        let v = randn(r, baseMu, sigma);
        if (r() < 0.04) v += (r() < 0.5 ? -1 : 1) * (5 + r() * 8);
        values.push(v);
      }
      data.push({ tool, chamber: ch, values });
    });
  });
  return {
    type: 'box_plot',
    title: 'Thickness by Tool / Chamber',
    data,
    x: 'chamber',
    y: ['value'],
    group_by_secondary: 'tool',
    values_field: 'values',
    show_outliers: true,
    expanded: true,
    y_label: 'Thickness (Å)',
  };
}

export function splomSpec(): ChartSpec {
  const r = mulberry32(22);
  const data = [];
  for (let i = 0; i < 250; i += 1) {
    const rf = randn(r, 1200, 40);
    const press = randn(r, 80, 4) + (rf - 1200) * 0.05;
    const gas = randn(r, 220, 8) - (press - 80) * 0.3;
    const temp = randn(r, 65, 1.2);
    const ep = randn(r, 28, 0.8) + (rf - 1200) * 0.02;
    const outlier = r() < 0.03;
    data.push({
      'RF Power': rf,
      Pressure: press,
      'Gas Flow': gas,
      Temp: temp,
      Endpoint: ep,
      outlier,
    });
  }
  return {
    type: 'splom',
    title: 'FDC Parameter Matrix',
    data,
    x: '',
    y: [],
    dimensions: ['RF Power', 'Pressure', 'Gas Flow', 'Temp', 'Endpoint'],
    outlier_field: 'outlier',
  };
}

export function histogramSpec(): ChartSpec {
  const r = mulberry32(33);
  const data = [];
  for (let i = 0; i < 800; i += 1) {
    data.push({ thickness: randn(r, 45.15, 0.55) });
  }
  return {
    type: 'histogram',
    title: 'CD distribution with spec window',
    data,
    x: '',
    y: [],
    value_column: 'thickness',
    usl: 47.0,
    lsl: 43.0,
    target: 45.0,
    bins: 32,
    show_normal: true,
    unit: 'nm',
  };
}

// ── SPC (PR-D) ──────────────────────────────────────────────────────────────

export function xbarRSpec(): ChartSpec {
  const r = mulberry32(44);
  const subgroups: number[][] = [];
  for (let g = 0; g < 30; g += 1) {
    const drift = g >= 18 && g < 24 ? (g - 17) * 0.4 : 0; // injected drift
    const grp: number[] = [];
    for (let i = 0; i < 5; i += 1) grp.push(randn(r, 100 + drift, 1.2));
    subgroups.push(grp);
  }
  return {
    type: 'xbar_r',
    title: 'X̄-R chart (subgroup size 5, drift around g18)',
    data: [],
    x: '',
    y: [],
    subgroups,
    subgroup_size: 5,
  };
}

export function imrSpec(): ChartSpec {
  const r = mulberry32(55);
  const values: number[] = [];
  for (let i = 0; i < 50; i += 1) {
    let v = randn(r, 250, 2.5);
    if (i === 32) v = 262; // single outlier
    values.push(v);
  }
  return {
    type: 'imr',
    title: 'I-MR (single-shot measurement)',
    data: [],
    x: '',
    y: [],
    values,
  };
}

export function ewmaCusumSpec(mode: 'ewma' | 'cusum' = 'ewma'): ChartSpec {
  const r = mulberry32(66);
  const values: number[] = [];
  for (let i = 0; i < 80; i += 1) {
    const shift = i > 50 ? 0.8 : 0;
    values.push(randn(r, 50 + shift, 1.5));
  }
  return {
    type: 'ewma_cusum',
    title: mode === 'ewma' ? 'EWMA chart (small-shift detection)' : 'CUSUM (cumulative drift)',
    data: [],
    x: '',
    y: [],
    values,
    mode,
    lambda: 0.2,
    k: 0.5,
    h: 4,
  };
}

// ── Diagnostic (PR-E) ───────────────────────────────────────────────────────

export function paretoSpec(): ChartSpec {
  return {
    type: 'pareto',
    title: 'Defect Pareto (last 7 days)',
    data: [
      { code: 'Particle', count: 142 },
      { code: 'Scratch', count: 97 },
      { code: 'Residue', count: 64 },
      { code: 'Pattern', count: 38 },
      { code: 'Bridge', count: 22 },
      { code: 'Open', count: 14 },
      { code: 'Void', count: 8 },
      { code: 'Other', count: 6 },
    ],
    x: 'code',
    y: ['count'],
    category_column: 'code',
    value_column: 'count',
    cumulative_threshold: 80,
  };
}

export function variabilityGaugeSpec(): ChartSpec {
  const r = mulberry32(77);
  const data: Array<Record<string, unknown>> = [];
  ['L24-001', 'L24-002', 'L24-003'].forEach((lot, li) => {
    ['W1', 'W2', 'W3'].forEach((wafer, wi) => {
      ['T-A', 'T-B'].forEach((tool, ti) => {
        const baseMu = 100 + li * 0.6 + (wi === 2 ? 0.3 : 0) + (ti === 1 && wi === 0 ? -0.4 : 0);
        for (let k = 0; k < 12; k += 1) {
          data.push({ lot, wafer, tool, value: randn(r, baseMu, 0.4) });
        }
      });
    });
  });
  return {
    type: 'variability_gauge',
    title: 'Variability Gauge — Lot › Wafer › Tool',
    data,
    x: 'tool',
    y: ['value'],
    value_column: 'value',
    levels: ['lot', 'wafer', 'tool'],
  };
}

export function parallelCoordsSpec(): ChartSpec {
  const r = mulberry32(88);
  const data = [];
  for (let i = 0; i < 80; i += 1) {
    const rf = randn(r, 1200, 30);
    const press = randn(r, 80, 3);
    const gas = randn(r, 220, 6);
    const temp = randn(r, 65, 1);
    // yield depends on closeness to target
    const baseYield = 95 - 0.02 * Math.abs(rf - 1200) - 0.4 * Math.abs(press - 80);
    const y = baseYield + randn(r, 0, 0.7);
    data.push({ 'RF Power': rf, Pressure: press, 'Gas Flow': gas, Temp: temp, 'Yield%': y });
  }
  return {
    type: 'parallel_coords',
    title: 'Recipe profile (color by yield)',
    data,
    x: '',
    y: [],
    dimensions: ['RF Power', 'Pressure', 'Gas Flow', 'Temp', 'Yield%'],
    color_by: 'Yield%',
    alert_below: 92,
  };
}

export function probabilityPlotSpec(): ChartSpec {
  const r = mulberry32(99);
  const data = [];
  // Mix of normal + slight skew so AD picks it up
  for (let i = 0; i < 100; i += 1) {
    const v = randn(r, 250, 2.5) + (r() < 0.05 ? 4 : 0);
    data.push({ value: v });
  }
  return {
    type: 'probability_plot',
    title: 'Probability plot (Anderson-Darling)',
    data,
    x: '',
    y: [],
    value_column: 'value',
  };
}

export function heatmapDendroSpec(): ChartSpec {
  // Build a synthetic 8×8 correlation matrix
  const params = ['RF', 'Press', 'Flow', 'Temp', 'Endpt', 'Bias', 'Cap', 'Vac'];
  const r = mulberry32(123);
  const matrix: number[][] = [];
  for (let i = 0; i < params.length; i += 1) {
    const row: number[] = [];
    for (let j = 0; j < params.length; j += 1) {
      if (i === j) row.push(1);
      else if ((i < 3 && j < 3) || (i >= 5 && j >= 5)) row.push(0.55 + r() * 0.4);
      else if ((i < 3 && j >= 5) || (j < 3 && i >= 5)) row.push(-(0.4 + r() * 0.3));
      else row.push((r() - 0.5) * 0.4);
    }
    matrix.push(row);
  }
  // Symmetrize
  for (let i = 0; i < params.length; i += 1) {
    for (let j = i + 1; j < params.length; j += 1) {
      const v = (matrix[i][j] + matrix[j][i]) / 2;
      matrix[i][j] = v;
      matrix[j][i] = v;
    }
  }
  return {
    type: 'heatmap_dendro',
    title: 'FDC correlation matrix (clustered)',
    data: [],
    x: '',
    y: [],
    matrix,
    params,
    cluster: true,
  };
}

// ── Wafer (PR-F) ────────────────────────────────────────────────────────────

function generate49Sites(r: () => number, mu: number, radial: number): Array<{ x: number; y: number; v: number }> {
  // 49-site standard pattern: center + 6 rings × 8 slots, kept inside r=145mm
  const sites: Array<{ x: number; y: number; v: number }> = [];
  sites.push({ x: 0, y: 0, v: randn(r, mu, 0.5) });
  const ringRadii = [25, 50, 75, 100, 125, 145];
  ringRadii.forEach((R) => {
    const n = 8;
    for (let k = 0; k < n; k += 1) {
      const theta = (k / n) * 2 * Math.PI;
      const x = R * Math.cos(theta);
      const y = R * Math.sin(theta);
      // Edge tends to drop slightly
      const drift = (R / 150) * radial;
      sites.push({ x, y, v: randn(r, mu + drift, 0.5) });
    }
  });
  return sites;
}

export function waferHeatmapSpec(): ChartSpec {
  const r = mulberry32(444);
  const points = generate49Sites(r, 500, -2.5);
  return {
    type: 'wafer_heatmap',
    title: 'Thickness map (49-site)',
    data: points.map((p) => ({ x: p.x, y: p.y, value: p.v })),
    x: 'x',
    y: ['value'],
    x_column: 'x',
    y_column: 'y',
    value_column: 'value',
    wafer_radius_mm: 150,
    notch: 'bottom',
    unit: 'Å',
    color_mode: 'viridis',
  };
}

export function defectStackSpec(): ChartSpec {
  const r = mulberry32(555);
  const data = [];
  for (let i = 0; i < 220; i += 1) {
    // Cluster particles in upper-left quadrant for visual interest
    const codeBias = r();
    const code = codeBias < 0.4 ? 'Particle' : DEFECT_CODES[Math.floor(r() * DEFECT_CODES.length)];
    let x: number;
    let y: number;
    if (code === 'Particle') {
      x = -50 - r() * 60;
      y = 30 + r() * 80;
    } else {
      const angle = r() * 2 * Math.PI;
      const radius = Math.sqrt(r()) * 145;
      x = radius * Math.cos(angle);
      y = radius * Math.sin(angle);
    }
    data.push({ x, y, defect_code: code });
  }
  return {
    type: 'defect_stack',
    title: 'Defect stack (last 20 wafers)',
    data,
    x: 'x',
    y: ['defect_code'],
    x_column: 'x',
    y_column: 'y',
    defect_column: 'defect_code',
    wafer_radius_mm: 150,
    notch: 'bottom',
  };
}

export function spatialParetoSpec(): ChartSpec {
  const r = mulberry32(666);
  // Build cells across wafer grid
  const data = [];
  const radius = 150;
  const gridN = 12;
  for (let i = 0; i < gridN; i += 1) {
    for (let j = 0; j < gridN; j += 1) {
      const cx = -radius + (i + 0.5) * (2 * radius / gridN);
      const cy = -radius + (j + 0.5) * (2 * radius / gridN);
      if (cx * cx + cy * cy > radius * radius) continue;
      // Lower-right quadrant has yield drop
      const drop = (cx > 50 && cy < -50) ? 8 : 0;
      const yieldPct = 95 - drop + randn(r, 0, 1.5);
      data.push({ x: cx, y: cy, yield_pct: yieldPct });
    }
  }
  return {
    type: 'spatial_pareto',
    title: 'Yield zone analysis (worst cell highlighted)',
    data,
    x: 'x',
    y: ['yield_pct'],
    x_column: 'x',
    y_column: 'y',
    value_column: 'yield_pct',
    wafer_radius_mm: 150,
    grid_n: gridN,
    notch: 'bottom',
    unit: '%',
  };
}

export function trendWaferMapsSpec(): ChartSpec {
  const r = mulberry32(777);
  const dates = ['Mar 25', 'Mar 26', 'Mar 27', 'Mar 28', 'Mar 29', 'Mar 30 (PM)', 'Apr 01'];
  const radial = [-2.5, -2.4, -2.3, -2.0, -1.8, 0.5, -1.2]; // PM resets the drift
  const maps = dates.map((date, k) => ({
    date,
    is_pm: date.includes('PM'),
    points: generate49Sites(r, 500, radial[k]),
  }));
  return {
    type: 'trend_wafer_maps',
    title: 'Thickness over time (PM at Mar 30)',
    data: [],
    x: '',
    y: [],
    maps,
    cols: 7,
    wafer_radius_mm: 150,
    notch: 'bottom',
  };
}
