"use client";

/**
 * Timeline scrubber + status histogram.
 *
 * 2026-05-08 — rewritten to use @visx/brush instead of a hand-rolled drag
 * handler. visx provides resize cursors, edge handles, and proper hit zones
 * out of the box. Min brush width is clamped to outer/24 (so 7d→7h min,
 * 6h→15min min); max width is the outer window itself.
 *
 * Histogram bins runs into ~28 buckets (sized via pickBucketMs), stacked
 * ok / warn / alarm vertically. Bin width adapts to the outer window.
 */

import { useMemo, useRef } from "react";
import { Brush } from "@visx/brush";
import { scaleTime, scaleLinear } from "@visx/scale";
import { Group } from "@visx/group";
import type BaseBrush from "@visx/brush/lib/BaseBrush";
import type { BrushHandleRenderProps } from "@visx/brush/lib/BrushHandle";
import { RunRecord } from "./lib/types";

interface Props {
  outerWindow:        [number, number];
  selected:           [number, number];
  onChange:           (range: [number, number]) => void;
  runs:               RunRecord[];
  focusedRunIds?:     Set<string> | null;
  onWindowSizeChange?: (newSpanMs: number) => void;
  windowSizeMs?:      number;
}

const WINDOW_OPTIONS: Array<[number, string]> = [
  [6 * 60 * 60 * 1000,        "6h"],
  [24 * 60 * 60 * 1000,       "1d"],
  [2 * 24 * 60 * 60 * 1000,   "2d"],
  [7 * 24 * 60 * 60 * 1000,   "7d"],
  [30 * 24 * 60 * 60 * 1000,  "30d"],
];

const MIN_MS  = 60 * 1000;
const HOUR_MS = 60 * MIN_MS;
const DAY_MS  = 24 * HOUR_MS;

const BG_OK    = "#cbd5d8";
const BG_WARN  = "#f59e0b";
const BG_ALARM = "#e0245e";

function pickBucketMs(spanMs: number): number {
  if (spanMs <=  4 * HOUR_MS) return  5 * MIN_MS;
  if (spanMs <= 24 * HOUR_MS) return 15 * MIN_MS;
  if (spanMs <=  3 * DAY_MS)  return  1 * HOUR_MS;
  if (spanMs <= 14 * DAY_MS)  return  6 * HOUR_MS;
  return DAY_MS;
}

function fmtBucketLabel(bucketMs: number): string {
  if (bucketMs >= DAY_MS)  return `${bucketMs / DAY_MS}d`;
  if (bucketMs >= HOUR_MS) return `${bucketMs / HOUR_MS}h`;
  return `${bucketMs / MIN_MS}m`;
}

function fmtMinSpan(ms: number): string {
  if (ms >= HOUR_MS) return `${(ms / HOUR_MS).toFixed(ms >= 10 * HOUR_MS ? 0 : 1)}h`;
  return `${Math.round(ms / MIN_MS)}min`;
}

const TIMELINE_HEIGHT = 64;
const AXIS_HEIGHT     = 18;
const PAD_X           = 8;

export default function Timeline({
  outerWindow, selected, onChange, runs, focusedRunIds,
  onWindowSizeChange, windowSizeMs,
}: Props) {
  const brushRef = useRef<BaseBrush | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const t0 = outerWindow[0];
  const t1 = outerWindow[1];
  const span = t1 - t0;
  const bucketMs = useMemo(() => pickBucketMs(span), [span]);
  const totalBins = Math.max(1, Math.ceil(span / bucketMs));
  // Min brush width: 1/24 of outer window. 7d → 7h, 1d → 1h, 6h → 15min.
  const minSelMs = Math.max(bucketMs, span / 24);

  // Bin runs
  const bins = useMemo(() => {
    const arr = new Array(totalBins).fill(0).map(() => ({ ok: 0, warn: 0, alarm: 0 }));
    for (const r of runs) {
      const i = Math.min(totalBins - 1, Math.floor((Date.parse(r.eventTime) - t0) / bucketMs));
      if (i < 0) continue;
      if (focusedRunIds && !focusedRunIds.has(r.id)) continue;
      arr[i][r.status]++;
    }
    return arr;
  }, [runs, focusedRunIds, t0, totalBins, bucketMs]);
  const maxBin = Math.max(1, ...bins.map((b) => b.ok + b.warn + b.alarm));

  // Track measured width so the visx scale matches the rendered SVG
  // (we can't read it during the first render — fall back to a sane default
  // and let the SVG re-layout via 100% width).
  const W = 1200;
  const innerW = Math.max(1, W - PAD_X * 2);
  const innerH = TIMELINE_HEIGHT;

  const xScale = useMemo(() => scaleTime({
    domain: [new Date(t0), new Date(t1)],
    range: [0, innerW],
  }), [t0, t1, innerW]);

  const yScale = useMemo(() => scaleLinear({
    domain: [0, maxBin],
    range: [innerH, 0],
  }), [maxBin, innerH]);

  // Re-pin the brush whenever the outer window changes (e.g. user clicks 6H).
  // Keying on outerWindow forces the visx Brush to re-mount with fresh
  // initialBrushPosition; otherwise it keeps its old internal extent and
  // disagrees with `selected` from the parent.
  const initialBrushPosition = useMemo(() => ({
    start: { x: xScale(new Date(Math.max(t0, Math.min(t1, selected[0])))) },
    end:   { x: xScale(new Date(Math.max(t0, Math.min(t1, selected[1])))) },
  }), [t0, t1]);  // intentionally omit `selected` — this is only the SEED

  const onBrushChange = (domain: { x0: number; x1: number; y0: number; y1: number } | null) => {
    if (!domain) return;
    const { x0, x1 } = domain;
    if (x0 == null || x1 == null) return;
    let from = Math.max(t0, Math.min(t1, +x0));
    let to   = Math.max(t0, Math.min(t1, +x1));
    if (to - from < minSelMs) {
      // Snap to min width, pinning whichever edge is at the boundary.
      if (to >= t1)         from = to - minSelMs;
      else if (from <= t0)  to   = from + minSelMs;
      else {
        const mid = (from + to) / 2;
        from = mid - minSelMs / 2;
        to   = mid + minSelMs / 2;
      }
    }
    if (from === selected[0] && to === selected[1]) return;
    onChange([from, to]);
  };

  // Custom handle so it has a visible vertical bar matching the prior look.
  const BrushHandle = ({ x, height, isBrushActive }: BrushHandleRenderProps) => {
    if (!isBrushActive) return null;
    return (
      <g cursor="ew-resize">
        {/* Wide invisible hit zone for easier grabbing */}
        <rect x={x - 6} y={0} width={12} height={height} fill="transparent" />
        {/* Visible vertical bar */}
        <line x1={x} x2={x} y1={0} y2={height} stroke="#111" strokeWidth={2} />
      </g>
    );
  };

  const fmt = (t: number) => new Date(t).toLocaleString("zh-TW", {
    hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
  const fmtSpanLabel = () => {
    if (span >= DAY_MS) return `${(span / DAY_MS).toFixed(span >= 7 * DAY_MS ? 0 : 1)} D`;
    return `${Math.round(span / HOUR_MS)} H`;
  };

  return (
    <div style={{
      borderTop: "1px solid #ececec", background: "#fff",
      padding: "8px 18px 10px", flex: "0 0 auto",
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        fontSize: 9.5, letterSpacing: "0.08em", color: "#999",
        marginBottom: 4, textTransform: "uppercase", flexWrap: "wrap", gap: 6,
      }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span>TIMELINE · {fmtSpanLabel()} · {fmtBucketLabel(bucketMs)} bins</span>
          {onWindowSizeChange && (
            <span style={{ display: "flex", gap: 2 }}>
              {WINDOW_OPTIONS.map(([ms, label]) => {
                const active = windowSizeMs === ms;
                return (
                  <button
                    key={label}
                    onClick={() => onWindowSizeChange(ms)}
                    style={{
                      fontSize: 9.5, letterSpacing: "0.05em",
                      padding: "1px 6px", borderRadius: 2,
                      border: active ? "1px solid #111" : "1px solid #ddd",
                      background: active ? "#111" : "#fff",
                      color: active ? "#fff" : "#666",
                      cursor: "pointer",
                      textTransform: "uppercase",
                      fontWeight: active ? 600 : 400,
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </span>
          )}
        </span>
        <span style={{
          fontFamily: "ui-monospace, Menlo, monospace",
          letterSpacing: 0,
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <span>{fmt(selected[0])} → {fmt(selected[1])}</span>
          <span style={{ color: "#bbb", textTransform: "none", letterSpacing: 0 }}>
            (min {fmtMinSpan(minSelMs)})
          </span>
        </span>
      </div>

      <div ref={containerRef} style={{
        position: "relative",
        background: "#fafafa", border: "1px solid #f0f0f0",
        borderRadius: 2, userSelect: "none",
      }}>
        <svg
          viewBox={`0 0 ${W} ${TIMELINE_HEIGHT + AXIS_HEIGHT}`}
          preserveAspectRatio="none"
          style={{ width: "100%", height: TIMELINE_HEIGHT + AXIS_HEIGHT, display: "block" }}
        >
          <Group left={PAD_X} top={0}>
            {/* Histogram bars */}
            {bins.map((b, i) => {
              const total = b.ok + b.warn + b.alarm;
              if (total === 0) return null;
              const barX = (i / totalBins) * innerW;
              const barW = Math.max(1, (innerW / totalBins) - 1);
              const okH    = (b.ok    / maxBin) * innerH;
              const warnH  = (b.warn  / maxBin) * innerH;
              const alarmH = (b.alarm / maxBin) * innerH;
              const stackH = okH + warnH + alarmH;
              const yTop   = innerH - stackH;
              return (
                <g key={i}>
                  {b.alarm > 0 && <rect x={barX} y={yTop} width={barW} height={alarmH} fill={BG_ALARM} />}
                  {b.warn  > 0 && <rect x={barX} y={yTop + alarmH} width={barW} height={warnH} fill={BG_WARN} />}
                  {b.ok    > 0 && <rect x={barX} y={yTop + alarmH + warnH} width={barW} height={okH} fill={BG_OK} />}
                </g>
              );
            })}

            {/* visx Brush — resize cursors, edge handles, hit zones built-in */}
            <Brush
              key={`${t0}-${t1}`}
              innerRef={brushRef}
              xScale={xScale}
              yScale={yScale}
              width={innerW}
              height={innerH}
              margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
              handleSize={8}
              resizeTriggerAreas={["left", "right"]}
              brushDirection="horizontal"
              initialBrushPosition={initialBrushPosition}
              onChange={onBrushChange}
              onClick={() => undefined}
              selectedBoxStyle={{
                fill: "rgba(17,17,17,0.06)",
                stroke: "#111",
                strokeWidth: 2,
              }}
              renderBrushHandle={(props) => <BrushHandle {...props} />}
              useWindowMoveEvents
            />
          </Group>

          {/* X-axis ticks */}
          <Group left={PAD_X} top={innerH + 2}>
            <TimelineAxis t0={t0} span={span} innerW={innerW} />
          </Group>
        </svg>
      </div>
    </div>
  );
}

// ── X-axis tick labels with adaptive stride (SVG, not absolute-positioned) ─
function TimelineAxis({ t0, span, innerW }: { t0: number; span: number; innerW: number }) {
  const stride = pickTickStrideMs(span);
  const fmt = (t: number, includeDate: boolean) => {
    const d = new Date(t);
    if (stride >= DAY_MS) {
      return d.toLocaleDateString("zh-TW", { month: "numeric", day: "numeric" });
    }
    const time = d.toLocaleString("zh-TW", { hour12: false, hour: "2-digit", minute: "2-digit" });
    if (includeDate) {
      const date = d.toLocaleDateString("zh-TW", { month: "numeric", day: "numeric" });
      return `${date} ${time}`;
    }
    return time;
  };
  const firstTick = Math.ceil(t0 / stride) * stride;
  const ticks: number[] = [];
  for (let t = firstTick; t <= t0 + span; t += stride) ticks.push(t);
  const step = Math.max(1, Math.ceil(ticks.length / 12));
  const visible = ticks.filter((_, i) => i % step === 0);
  return (
    <>
      {visible.map((t, i) => {
        const xPos = ((t - t0) / span) * innerW;
        const d = new Date(t);
        const includeDate = i === 0 || (stride < DAY_MS && d.getHours() === 0);
        const anchor = xPos < 24 ? "start" : xPos > innerW - 24 ? "end" : "middle";
        return (
          <text key={t} x={xPos} y={12}
                fontSize={9.5} fill="#bbb" textAnchor={anchor}>
            {fmt(t, includeDate)}
          </text>
        );
      })}
      <text x={innerW} y={12} fontSize={9.5} fill="#999" fontWeight={600} textAnchor="end">NOW</text>
    </>
  );
}

function pickTickStrideMs(span: number): number {
  if (span <=  6 * HOUR_MS) return HOUR_MS;
  if (span <= 24 * HOUR_MS) return 4 * HOUR_MS;
  if (span <=  2 * DAY_MS)  return 6 * HOUR_MS;
  if (span <=  7 * DAY_MS)  return DAY_MS;
  return 7 * DAY_MS;
}
