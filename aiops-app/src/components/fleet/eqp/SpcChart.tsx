"use client";

import type { SpcTrace } from "../eqp-types";

const TITLE_MAP: Record<string, string> = {
  c_chart: "C Chart — STEP_002 mean",
  p_chart: "P Chart — STEP_005 defect rate",
  r_chart: "R Chart — STEP_007 range",
  xbar_chart: "X̄ Chart",
  s_chart: "S Chart",
};

/** Single SPC trace with UCL/LCL/target lines. Pure SVG (no chart lib).
 *  OOC points (value > UCL or < LCL) get a red filled marker, others
 *  use a small dark dot. Target line is the dashed midline. */
export function SpcChart({ trace, w = 1080, h = 200 }: {
  trace: SpcTrace;
  w?: number; h?: number;
}) {
  const { values, ucl, lcl, target } = trace;
  if (!values || values.length === 0) {
    return <div className="micro" style={{ color: "var(--c-ink-3)", padding: 16 }}>(無 trace 資料)</div>;
  }
  const max = Math.max(...values, ucl) * 1.05;
  const min = Math.min(...values, lcl) * 0.95;
  const range = max - min || 1;
  const padL = 36, padR = 36, padT = 8, padB = 18;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const step = innerW / Math.max(1, values.length - 1);
  const y = (v: number) => padT + innerH - ((v - min) / range) * innerH;
  const path = values
    .map((v, i) => (i === 0 ? "M" : "L") + (padL + i * step).toFixed(1) + " " + y(v).toFixed(1))
    .join(" ");
  const yUCL = y(ucl);
  const yLCL = y(lcl);
  const yT = y(target);

  return (
    <div className="surface" style={{ padding: "10px 12px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
        <div className="h3">{TITLE_MAP[trace.chart] ?? trace.chart}</div>
        <div className="micro" style={{ color: "var(--c-ink-2)" }}>
          <span style={{ marginRight: 12 }}>UCL <span className="mono">{ucl}</span></span>
          <span style={{ marginRight: 12 }}>Target <span className="mono">{target.toFixed(1)}</span></span>
          <span>LCL <span className="mono">{lcl}</span></span>
        </div>
      </div>
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: "block" }}>
        <line x1={padL} x2={w - padR} y1={yT} y2={yT} stroke="#a4a4a8" strokeDasharray="2 3" strokeWidth={0.8} />
        <line x1={padL} x2={w - padR} y1={yUCL} y2={yUCL} stroke="#b8392f" strokeDasharray="3 3" strokeWidth={0.8} opacity={0.7} />
        <line x1={padL} x2={w - padR} y1={yLCL} y2={yLCL} stroke="#b8392f" strokeDasharray="3 3" strokeWidth={0.8} opacity={0.7} />
        <path d={path} fill="none" stroke="#2a2a2d" strokeWidth={1.2} />
        {values.map((v, i) => {
          const cy = y(v);
          const ooc = v > ucl || v < lcl;
          return (
            <circle key={i} cx={padL + i * step} cy={cy} r={ooc ? 3 : 1.4}
                    fill={ooc ? "#b8392f" : "#2a2a2d"}
                    stroke={ooc ? "#fff" : "none"} strokeWidth={ooc ? 1 : 0} />
          );
        })}
        <text x={padL - 6} y={yUCL + 3} fontSize={9} fill="#b8392f" textAnchor="end" fontFamily="var(--font-mono)">UCL</text>
        <text x={padL - 6} y={yLCL + 3} fontSize={9} fill="#b8392f" textAnchor="end" fontFamily="var(--font-mono)">LCL</text>
        <text x={padL - 6} y={yT + 3} fontSize={9} fill="#76767a" textAnchor="end" fontFamily="var(--font-mono)">x̄</text>
      </svg>
    </div>
  );
}
