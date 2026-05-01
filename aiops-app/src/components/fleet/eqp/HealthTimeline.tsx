"use client";

import { SEV_COLOR } from "../primitives";
import type { TimelineEvent } from "../eqp-types";

const LANE_LABELS: Record<string, string> = {
  ooc: "SPC OOC",
  apc: "APC",
  fdc: "FDC",
  ec:  "EC",
  recipe: "Recipe 變更",
  lot: "LOT",
};

const LANES: Array<TimelineEvent["lane"]> = ["ooc", "apc", "fdc", "ec", "recipe", "lot"];

export function HealthTimeline({ events, since, asOf }: {
  events: TimelineEvent[];
  since: string;
  asOf: string;
}) {
  const t0 = new Date(since).getTime();
  const t1 = new Date(asOf).getTime();
  const span = Math.max(1, t1 - t0);

  const W = 1080, laneH = 28, padL = 110, padR = 16;
  const innerW = W - padL - padR;

  return (
    <div className="surface" style={{ padding: "14px 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 12 }}>
        <div className="h2">健康度時間軸</div>
        <div className="micro mono" style={{ color: "var(--c-ink-3)" }}>-24h ─────── now</div>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${LANES.length * laneH + 28}`} style={{ display: "block" }}>
        {/* hour grid */}
        {Array.from({ length: 25 }).map((_, h) => {
          const x = padL + (h / 24) * innerW;
          return (
            <g key={h}>
              <line x1={x} x2={x} y1={8} y2={LANES.length * laneH + 8}
                    stroke={h % 6 === 0 ? "#d4d4cf" : "#ededea"} strokeWidth={1} />
              {h % 6 === 0 && (
                <text x={x} y={LANES.length * laneH + 22} fontSize={10}
                      fill="#a4a4a8" fontFamily="var(--font-mono)" textAnchor="middle">
                  {h === 0 ? "-24h" : h === 24 ? "now" : `-${24 - h}h`}
                </text>
              )}
            </g>
          );
        })}
        {/* lane labels + baseline */}
        {LANES.map((lane, i) => {
          const y = 16 + i * laneH;
          return (
            <g key={lane}>
              <text x={padL - 12} y={y + 4} fontSize={11} fill="#4a4a4d"
                    textAnchor="end" fontFamily="var(--font-sans)">
                {LANE_LABELS[lane]}
              </text>
              <line x1={padL} x2={W - padR} y1={y} y2={y} stroke="#f4f4f2" strokeWidth={1} />
            </g>
          );
        })}
        {/* events */}
        {events.map((e, i) => {
          const laneIdx = LANES.indexOf(e.lane);
          if (laneIdx < 0) return null;
          const tt = new Date(e.t).getTime();
          const ratio = Math.max(0, Math.min(1, (tt - t0) / span));
          const x = padL + ratio * innerW;
          const y = 16 + laneIdx * laneH;
          const c = SEV_COLOR[e.severity] ?? SEV_COLOR.neutral;
          return (
            <g key={i}>
              <title>{`${e.label}${e.detail ? " — " + e.detail : ""}`}</title>
              <circle cx={x} cy={y} r={e.severity === "crit" ? 4.5 : 3.5}
                      fill={c} stroke="#fff" strokeWidth={1.5} />
            </g>
          );
        })}
      </svg>
      <div style={{ display: "flex", gap: 14, fontSize: 11, color: "var(--c-ink-3)", marginTop: 6, flexWrap: "wrap" }}>
        <span>● <span style={{ color: "var(--c-crit)" }}>OOC / 嚴重</span></span>
        <span>● <span style={{ color: "var(--c-warn)" }}>異常 / 警告</span></span>
        <span>● <span style={{ color: "var(--c-info)" }}>變更</span></span>
        <span>● <span style={{ color: "var(--c-ok)" }}>正常完成</span></span>
        <span style={{ marginLeft: "auto" }}>共 {events.length} 個事件</span>
      </div>
    </div>
  );
}
