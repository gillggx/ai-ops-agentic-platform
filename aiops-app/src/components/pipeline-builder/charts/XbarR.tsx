/**
 * XbarR — proper X̄/R control chart (subgroup mean + range), with WECO
 * R1–R8 highlighting on the X̄ panel. Replaces ad-hoc `block_chart(line)
 * + block_weco_rules` combos for SPC use cases.
 *
 * Two input shapes:
 *   1. Pre-aggregated:
 *        spec.subgroups: number[][]  — one inner array per subgroup
 *   2. Raw rows:
 *        spec.value_column / spec.y[0] = numeric column
 *        spec.subgroup_column          = grouping column (lot_id, etc.)
 *      → groups by subgroup_column, each subgroup's values become a row.
 *
 * Spec extras:
 *   spec.subgroup_size?     hint for control-limit constants when groups
 *                           are uneven (defaults to inferred mode)
 *   spec.weco_rules?        WecoRuleId[] — which rules to enable (default all)
 *   spec.title?
 */

'use client';

import * as React from 'react';
import { useSvgChart, mean } from './lib';
import { renderDualPanel, type ControlPanelData } from './lib/dual-panel';
import { spcConstants } from './lib/spc';
import { wecoCheck, type WecoRuleId, ALL_WECO_RULES } from './lib/weco';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

/** Build subgroups from spec — pre-agg first, then raw rows. */
function readSubgroups(spec: ChartSpec): number[][] {
  // Pre-aggregated path
  if (Array.isArray(spec.subgroups)) {
    return (spec.subgroups as unknown[][]).map((g) =>
      Array.isArray(g)
        ? g.map((v) => Number(v)).filter((v): v is number => Number.isFinite(v))
        : [],
    );
  }

  const data = Array.isArray(spec.data) ? spec.data : [];
  if (data.length === 0) return [];

  const valueCol = (spec.value_column as string | undefined)
    ?? (Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : null);
  const subgroupCol = (spec.subgroup_column as string | undefined) ?? null;
  if (!valueCol) return [];

  if (!subgroupCol) {
    // No grouping column — assume each row is a subgroup of size 1 (degenerate;
    // user probably wants IMR instead). Still render to avoid crash.
    return data
      .map((r) => Number(r[valueCol]))
      .filter((v): v is number => Number.isFinite(v))
      .map((v) => [v]);
  }

  const map = new Map<string, number[]>();
  // Preserve first-seen order so chart x-axis is chronological per subgroup.
  for (const row of data) {
    const key = String(row[subgroupCol] ?? '');
    let arr = map.get(key);
    if (!arr) {
      arr = [];
      map.set(key, arr);
    }
    const v = Number(row[valueCol]);
    if (Number.isFinite(v)) arr.push(v);
  }
  return Array.from(map.values()).filter((g) => g.length > 0);
}

function inferSize(subgroups: number[][]): number {
  if (subgroups.length === 0) return 5;
  // Use the most common length (mode), capped at 10 for the constants table.
  const counts = new Map<number, number>();
  for (const g of subgroups) {
    counts.set(g.length, (counts.get(g.length) ?? 0) + 1);
  }
  let best = 5;
  let bestCount = -1;
  counts.forEach((c, n) => {
    if (c > bestCount) {
      bestCount = c;
      best = n;
    }
  });
  return Math.max(2, Math.min(10, best));
}

function compute(spec: ChartSpec): {
  top: ControlPanelData;
  bot: ControlPanelData;
  totalViolations: number;
} {
  const subgroups = readSubgroups(spec);
  if (subgroups.length === 0) {
    const empty: ControlPanelData = { values: [], CL: 0, UCL: 0, LCL: 0, violations: [] };
    return { top: empty, bot: empty, totalViolations: 0 };
  }
  const n = (typeof spec.subgroup_size === 'number' && spec.subgroup_size >= 2)
    ? Math.min(10, Math.floor(spec.subgroup_size as number))
    : inferSize(subgroups);
  const c = spcConstants(n);

  const xbars = subgroups.map((g) => mean(g));
  const ranges = subgroups.map((g) => (g.length ? Math.max(...g) - Math.min(...g) : 0));
  const xCL = mean(xbars);
  const rCL = mean(ranges);
  const xUCL = xCL + c.A2 * rCL;
  const xLCL = xCL - c.A2 * rCL;
  const rUCL = c.D4 * rCL;
  const rLCL = c.D3 * rCL;
  // σ_X̄ for WECO zones (X̄ chart's σ is the standard error of the subgroup mean)
  const sigmaProcess = c.d2 > 0 ? rCL / c.d2 : 0;
  const sigmaXbar = sigmaProcess / Math.sqrt(n);

  const enabled: ReadonlyArray<WecoRuleId> = Array.isArray(spec.weco_rules)
    ? (spec.weco_rules as WecoRuleId[]).filter((r) => ALL_WECO_RULES.includes(r))
    : ALL_WECO_RULES;

  const xViol = xbars.map((_, i) => {
    const v = wecoCheck(xbars, xCL, sigmaXbar, i, enabled);
    return v ? v.reason : null;
  });
  const rViol = ranges.map((v) =>
    Number.isFinite(rUCL) && (v > rUCL || v < rLCL) ? 'R1: outside R control limit' : null,
  );

  let total = 0;
  for (const r of xViol) if (r) total += 1;
  for (const r of rViol) if (r) total += 1;

  return {
    top: { values: xbars, CL: xCL, UCL: xUCL, LCL: xLCL, violations: xViol, sigma: sigmaXbar },
    bot: { values: ranges, CL: rCL, UCL: rUCL, LCL: rLCL, violations: rViol, sigma: sigmaProcess },
    totalViolations: total,
  };
}

export default function XbarR({ spec, height }: Props) {
  const ref = useSvgChart((svg) => {
    const { top, bot } = compute(spec);
    renderDualPanel(svg, top, bot, {
      topLabel: 'X̄ (subgroup mean)',
      botLabel: 'R (range)',
      title: spec.title,
    });
  }, [spec]);
  return (
    <div className="pb-chart-card" style={{ height: height ?? 360 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Xbar-R chart'} />
    </div>
  );
}

export { compute as computeXbarR };
