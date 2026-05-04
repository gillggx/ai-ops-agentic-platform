"use client";

/**
 * 28-day timeline scrubber + status histogram.
 * Port of reference app-chrome.jsx Timeline.
 *
 * Bins runs into 28 day-buckets, stacks ok / warn / alarm vertically.
 * Window selection is a draggable rectangle with left/right resize handles.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { RunRecord } from "./lib/types";

interface Props {
  outerWindow: [number, number];          // total scrubable range (e.g. last 28 d)
  selected:    [number, number];          // currently selected slice
  onChange:    (range: [number, number]) => void;
  runs:        RunRecord[];               // all runs in outerWindow
  focusedRunIds?: Set<string> | null;     // when present, only focused runs counted
  // 2026-05-04: outer window is now user-adjustable. Parent owns the
  // canonical value and updates it via this callback when user picks a
  // different size from the dropdown row.
  onWindowSizeChange?: (newSpanMs: number) => void;
  windowSizeMs?: number;                  // current outer span in ms (for highlighting)
}

// Available outer window choices for the picker. Tuple = (ms, label).
const WINDOW_OPTIONS: Array<[number, string]> = [
  [6 * 60 * 60 * 1000,           "6h"],
  [24 * 60 * 60 * 1000,          "1d"],
  [2 * 24 * 60 * 60 * 1000,      "2d"],
  [7 * 24 * 60 * 60 * 1000,      "7d"],
  [30 * 24 * 60 * 60 * 1000,     "30d"],
];

const MIN_MS  = 60 * 1000;
const HOUR_MS = 60 * MIN_MS;
const DAY_MS  = 24 * HOUR_MS;

/**
 * Pick a bucket size that gives us ~80–200 bins across the outer window.
 * Granularities: 5m / 15m / 1h / 6h / 1d.
 */
function pickBucketMs(spanMs: number): number {
  if (spanMs <=  4 * HOUR_MS) return  5 * MIN_MS;   // ≤4h → 5min bins (48 bins)
  if (spanMs <= 24 * HOUR_MS) return 15 * MIN_MS;   // ≤1d → 15min bins (96 bins)
  if (spanMs <=  3 * DAY_MS)  return  1 * HOUR_MS;  // ≤3d → 1h bins
  if (spanMs <= 14 * DAY_MS)  return  6 * HOUR_MS;  // ≤2w → 6h bins
  return DAY_MS;
}

function fmtBucketLabel(bucketMs: number): string {
  if (bucketMs >= DAY_MS)  return `${bucketMs / DAY_MS}d`;
  if (bucketMs >= HOUR_MS) return `${bucketMs / HOUR_MS}h`;
  return `${bucketMs / MIN_MS}m`;
}

export default function Timeline({
  outerWindow, selected, onChange, runs, focusedRunIds,
  onWindowSizeChange, windowSizeMs,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ mode: "left" | "right" | "move"; startX: number; start: [number, number]; rect: DOMRect } | null>(null);

  const t0 = outerWindow[0];
  const t1 = outerWindow[1];
  const span = t1 - t0;
  const bucketMs = useMemo(() => pickBucketMs(span), [span]);
  const totalBins = Math.max(1, Math.ceil(span / bucketMs));
  const minSelMs  = bucketMs;          // selection can shrink down to 1 bucket

  // Bin runs into N buckets
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

  const w0pct = ((selected[0] - t0) / span) * 100;
  const w1pct = ((selected[1] - t0) / span) * 100;

  const onMouseDown = (e: React.MouseEvent, mode: "left" | "right" | "move") => {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    setDrag({ mode, startX: e.clientX, start: [...selected] as [number, number], rect });
    e.preventDefault();
  };

  useEffect(() => {
    if (!drag) return;
    const onMove = (e: MouseEvent) => {
      const dx   = e.clientX - drag.startX;
      const dPct = dx / drag.rect.width;
      const dT   = dPct * span;
      let n0 = drag.start[0], n1 = drag.start[1];
      if (drag.mode === "left") {
        n0 = Math.max(t0, Math.min(n1 - minSelMs, drag.start[0] + dT));
      } else if (drag.mode === "right") {
        n1 = Math.max(n0 + minSelMs, Math.min(t1, drag.start[1] + dT));
      } else {
        const w = drag.start[1] - drag.start[0];
        n0 = Math.max(t0, Math.min(t1 - w, drag.start[0] + dT));
        n1 = n0 + w;
      }
      onChange([n0, n1]);
    };
    const onUp = () => setDrag(null);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [drag, span, t0, t1, onChange]);

  const maxBin = Math.max(1, ...bins.map((b) => b.ok + b.warn + b.alarm));
  const fmt    = (t: number) => new Date(t).toLocaleString("zh-TW", {
    hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
  const fmtTick = (t: number) => bucketMs >= DAY_MS
    ? new Date(t).toLocaleDateString("zh-TW", { month: "numeric", day: "numeric" })
    : new Date(t).toLocaleString("zh-TW", { hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
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
        marginBottom: 4, textTransform: "uppercase",
      }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span>TIMELINE · {fmtSpanLabel()} · {fmtBucketLabel(bucketMs)} bins</span>
          {/* Window-size picker (2026-05-04). Parent owns the canonical
              outerWindow; we just emit onWindowSizeChange when user picks. */}
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
        <span style={{ fontFamily: "ui-monospace, Menlo, monospace", letterSpacing: 0 }}>
          {fmt(selected[0])} → {fmt(selected[1])}
        </span>
      </div>
      <div ref={ref} style={{
        position: "relative", height: 44,
        background: "#fafafa", border: "1px solid #f0f0f0",
        borderRadius: 2, userSelect: "none",
      }}>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "flex-end", padding: "3px 2px", gap: 1 }}>
          {bins.map((b, i) => (
            <div key={i} style={{
              flex: 1, height: 36,
              display: "flex", flexDirection: "column", justifyContent: "flex-end",
            }}>
              {b.alarm > 0 && <div style={{ height: (b.alarm / maxBin) * 36, background: "#e0245e" }} />}
              {b.warn  > 0 && <div style={{ height: (b.warn  / maxBin) * 36, background: "#f59e0b" }} />}
              {b.ok    > 0 && <div style={{ height: (b.ok    / maxBin) * 36, background: "#cbd5d8" }} />}
            </div>
          ))}
        </div>
        {/* Selection rectangle */}
        <div
          onMouseDown={(e) => onMouseDown(e, "move")}
          style={{
            position: "absolute", top: 0, bottom: 0,
            left: `${w0pct}%`, width: `${w1pct - w0pct}%`,
            background: "rgba(17,17,17,0.06)",
            borderLeft: "2px solid #111", borderRight: "2px solid #111",
            cursor: drag?.mode === "move" ? "grabbing" : "grab",
          }}
        >
          <div onMouseDown={(e) => { e.stopPropagation(); onMouseDown(e, "left"); }}
               style={{ position: "absolute", left: -4, top: 0, bottom: 0, width: 8, cursor: "ew-resize" }} />
          <div onMouseDown={(e) => { e.stopPropagation(); onMouseDown(e, "right"); }}
               style={{ position: "absolute", right: -4, top: 0, bottom: 0, width: 8, cursor: "ew-resize" }} />
        </div>
      </div>
      {/* Hour-level x-axis ticks (2026-05-04). Computes tick stride from
          span: ≤6h → every hour, ≤1d → every 4h, ≤2d → every 6h, ≤7d → every
          1d, >7d → every 7d. Caps at ~12 visible labels so layout doesn't
          overflow. */}
      <TimelineAxis t0={t0} span={span} />
    </div>
  );
}

// ── X-axis tick labels with adaptive stride ────────────────────────────
function TimelineAxis({ t0, span }: { t0: number; span: number }) {
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
  // First tick aligned to stride boundary at or after t0
  const firstTick = Math.ceil(t0 / stride) * stride;
  const ticks: number[] = [];
  for (let t = firstTick; t <= t0 + span; t += stride) ticks.push(t);
  // Cap at 12 ticks max so it never overflows
  const step = Math.max(1, Math.ceil(ticks.length / 12));
  const visible = ticks.filter((_, i) => i % step === 0);
  return (
    <div style={{
      position: "relative", height: 14, marginTop: 4,
      fontSize: 9.5, color: "#bbb",
    }}>
      {visible.map((t, i) => {
        const pct = ((t - t0) / span) * 100;
        // Add the date prefix only on the first label and on day-boundary ticks
        const d = new Date(t);
        const includeDate = i === 0 || (stride < DAY_MS && d.getHours() === 0);
        return (
          <span key={t} style={{
            position: "absolute", left: `${pct}%`,
            transform: pct < 5 ? "translateX(0)" : pct > 95 ? "translateX(-100%)" : "translateX(-50%)",
            whiteSpace: "nowrap",
          }}>
            {fmt(t, includeDate)}
          </span>
        );
      })}
      <span style={{
        position: "absolute", right: 0,
        fontWeight: 600, color: "#999",
      }}>NOW</span>
    </div>
  );
}

function pickTickStrideMs(span: number): number {
  if (span <=  6 * HOUR_MS) return HOUR_MS;          // every hour
  if (span <= 24 * HOUR_MS) return 4 * HOUR_MS;      // every 4 hours
  if (span <=  2 * DAY_MS)  return 6 * HOUR_MS;      // every 6 hours
  if (span <=  7 * DAY_MS)  return DAY_MS;           // every day
  return 7 * DAY_MS;                                 // every week
}
