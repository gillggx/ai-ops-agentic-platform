/**
 * IMR — Individual + Moving Range chart for unsubgrouped data.
 *
 * Used when each measurement is a single value (no subgroup), e.g. one
 * thickness reading per wafer. σ is estimated from the mean moving range
 * (M̄R / d2 where d2(n=2) = 1.128).
 *
 * Spec shape (mirrors XbarR's raw mode):
 *   spec.value_column / spec.y[0]   numeric column to chart
 *   spec.values?: number[]          alternative pre-aggregated path
 *   spec.weco_rules?: WecoRuleId[]
 */

'use client';

import * as React from 'react';
import { useSvgChart, mean } from './lib';
import { renderDualPanel, type ControlPanelData } from './lib/dual-panel';
import { IMR_D2, IMR_D4 } from './lib/spc';
import { wecoCheck, type WecoRuleId, ALL_WECO_RULES } from './lib/weco';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

function readValues(spec: ChartSpec): number[] {
  if (Array.isArray(spec.values)) {
    return (spec.values as unknown[])
      .map((v) => Number(v))
      .filter((v): v is number => Number.isFinite(v));
  }
  const data = Array.isArray(spec.data) ? spec.data : [];
  const valueCol = (spec.value_column as string | undefined)
    ?? (Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : null);
  if (!valueCol) return [];
  return data
    .map((r) => Number(r[valueCol]))
    .filter((v): v is number => Number.isFinite(v));
}

function compute(spec: ChartSpec): {
  top: ControlPanelData;
  bot: ControlPanelData;
} {
  const vals = readValues(spec);
  if (vals.length === 0) {
    const empty: ControlPanelData = { values: [], CL: 0, UCL: 0, LCL: 0, violations: [] };
    return { top: empty, bot: empty };
  }
  const mr: number[] = [];
  for (let i = 1; i < vals.length; i++) mr.push(Math.abs(vals[i] - vals[i - 1]));
  const iCL = mean(vals);
  const mrCL = mr.length > 0 ? mean(mr) : 0;
  const sigma = mrCL / IMR_D2;
  const iUCL = iCL + 3 * sigma;
  const iLCL = iCL - 3 * sigma;
  const mrUCL = IMR_D4 * mrCL;
  const mrLCL = 0; // D3=0 for n=2

  const enabled: ReadonlyArray<WecoRuleId> = Array.isArray(spec.weco_rules)
    ? (spec.weco_rules as WecoRuleId[]).filter((r) => ALL_WECO_RULES.includes(r))
    : ALL_WECO_RULES;

  const iViol = vals.map((_, i) => {
    const v = wecoCheck(vals, iCL, sigma, i, enabled);
    return v ? v.reason : null;
  });
  // MR: only check vs UCL (no negatives, no WECO since MRs are absolute differences)
  const mrViol = mr.map((v) => (v > mrUCL ? 'R1: outside MR limit' : null));

  return {
    top: { values: vals, CL: iCL, UCL: iUCL, LCL: iLCL, violations: iViol, sigma },
    // Pad MR with leading null so X-axis lines up with I panel
    bot: {
      values: [NaN, ...mr] as number[],
      CL: mrCL,
      UCL: mrUCL,
      LCL: mrLCL,
      violations: [null, ...mrViol],
    },
  };
}

export default function IMR({ spec, height }: Props) {
  const ref = useSvgChart((svg) => {
    const { top, bot } = compute(spec);
    renderDualPanel(svg, top, bot, {
      topLabel: 'I (individual)',
      botLabel: 'MR (moving range)',
      title: spec.title,
    });
  }, [spec]);
  return (
    <div className="pb-chart-card" style={{ width: '100%', height: height ?? 360 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'I-MR chart'} />
    </div>
  );
}

export { compute as computeIMR };
