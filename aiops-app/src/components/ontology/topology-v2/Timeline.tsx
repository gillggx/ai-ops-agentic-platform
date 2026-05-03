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
}

const DAY_MS = 24 * 60 * 60 * 1000;

export default function Timeline({ outerWindow, selected, onChange, runs, focusedRunIds }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ mode: "left" | "right" | "move"; startX: number; start: [number, number]; rect: DOMRect } | null>(null);

  const t0 = outerWindow[0];
  const t1 = outerWindow[1];
  const span = t1 - t0;
  const totalDays = Math.max(1, Math.round(span / DAY_MS));

  // Bin runs into N day-buckets
  const bins = useMemo(() => {
    const arr = new Array(totalDays).fill(0).map(() => ({ ok: 0, warn: 0, alarm: 0 }));
    for (const r of runs) {
      const i = Math.min(totalDays - 1, Math.floor((Date.parse(r.eventTime) - t0) / DAY_MS));
      if (i < 0) continue;
      if (focusedRunIds && !focusedRunIds.has(r.id)) continue;
      arr[i][r.status]++;
    }
    return arr;
  }, [runs, focusedRunIds, t0, totalDays]);

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
        n0 = Math.max(t0, Math.min(n1 - DAY_MS, drag.start[0] + dT));
      } else if (drag.mode === "right") {
        n1 = Math.max(n0 + DAY_MS, Math.min(t1, drag.start[1] + dT));
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
  const fmtDay = (t: number) => new Date(t).toLocaleDateString("zh-TW", { month: "numeric", day: "numeric" });

  return (
    <div style={{
      borderTop: "1px solid #ececec", background: "#fff",
      padding: "8px 18px 10px", flex: "0 0 auto",
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between",
        fontSize: 9.5, letterSpacing: "0.08em", color: "#999",
        marginBottom: 4, textTransform: "uppercase",
      }}>
        <span>TIMELINE · {totalDays} D</span>
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
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9.5, color: "#bbb", marginTop: 3 }}>
        <span>{fmtDay(t0)}</span>
        <span>{fmtDay(t0 + span * 0.5)}</span>
        <span>NOW</span>
      </div>
    </div>
  );
}
