"use client";
/**
 * DualTrackScrubber v4 — Light Theme Forensic Scrubber
 *
 * Architecture: Invisible <input type="range"> + SVG ruler overlay
 * Theme: light (white/slate-50 background)
 *
 * Layout:
 *   Header: LOT | TOOL big tab switcher
 *   Body:   Single active-track event list (scrollable)
 *   Footer: jQuery-style time ruler with color-coded event markers + grip handle
 *
 * Color markers on ruler:
 *   OOC     → red tall ticks
 *   Pass    → green medium ticks
 *   Normal  → slate short ticks
 *
 * Interaction:
 *   onInput   → move handle + update time label (visual only, no API)
 *   onMouseUp → snap to nearest event → onSelect()
 */
import { useState, useEffect, useCallback, useRef } from "react";

function getApiBase() {
  if (typeof window === "undefined") return "/simulator-api";
  const isLocal =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";
  return `${window.location.origin}/simulator-api`;
}

// ── Types ──────────────────────────────────────────────────────────────────────

export interface ScrubberSelection {
  lotID:          string | null;
  step:           string | null;
  eventTime:      string;
  toolID?:        string | null;
  processStatus?: "ProcessStart" | "ProcessEnd";
}

// New merged step format from v2 trajectory API (start_time + end_time)
interface LotStep {
  step:             string;
  tool_id:          string;
  start_time?:      string;   // ProcessStart eventTime
  end_time?:        string;   // ProcessEnd eventTime (null = in-progress)
  recipe_id:        string | null;
  apc_id?:          string | null;
  spc_status:       string | null;
  dc_snapshot_id?:  string | null;
  spc_snapshot_id?: string | null;
}

interface ToolBatch {
  lot_id:           string | null;
  step:             string | null;
  start_time?:      string;
  end_time?:        string;
  recipe_id:        string | null;
  apc_id?:          string | null;
  spc_status:       string | null;
  dc_snapshot_id?:  string | null;
  spc_snapshot_id?: string | null;
}

export interface TimePoint {
  id:             string;
  time:           Date;
  step:           string | null;
  lot_id:         string | null;
  tool_id:        string | null;
  spc_status:     string | null;
  track:          "lot" | "tool";
  processStatus:  "ProcessStart" | "ProcessEnd";
}

interface ScrubberEvent {
  id:            string;
  track:         "LOT" | "TOOL";
  percent:       number;
  timeMs:        number;
  step:          string | null;
  lot_id:        string | null;
  tool_id:       string | null;
  status:        "ooc" | "pass" | "normal";
  processStatus: "ProcessStart" | "ProcessEnd";
}

interface Props {
  lotID:         string | null;
  toolID:        string | null;
  onSelect:      (sel: ScrubberSelection) => void;
  selectedTime:  string | null;
  activeTrack:   "LOT" | "TOOL";
  onTrackChange: (track: "LOT" | "TOOL") => void;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function buildTicks(minT: number, maxT: number) {
  const span = maxT - minT;
  const rawInterval = span / 7;
  const niceMs = [5, 10, 15, 30, 60, 120, 240, 360].map(m => m * 60 * 1000);
  const interval = niceMs.find(v => v >= rawInterval) ?? niceMs[niceMs.length - 1];
  const ticks: { ms: number; label: string }[] = [];
  const start = Math.ceil(minT / interval) * interval;
  for (let t = start; t <= maxT; t += interval) {
    const d = new Date(t);
    ticks.push({
      ms: t,
      label: `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`,
    });
  }
  return ticks;
}

function fmtTimeFull(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// ── Event list rows (light theme) ──────────────────────────────────────────────

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function PhaseBadge({ phase }: { phase: "ProcessStart" | "ProcessEnd" }) {
  return phase === "ProcessStart"
    ? <span className="text-[8px] font-bold px-1 py-0.5 rounded bg-violet-100 text-violet-600 border border-violet-200">▶ Start</span>
    : <span className="text-[8px] font-bold px-1 py-0.5 rounded bg-teal-100 text-teal-600 border border-teal-200">■ End</span>;
}

function SpcBadge({ status }: { status: string | null }) {
  return status === "OOC"
    ? <span className="text-[8px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-600 border border-red-200">OOC</span>
    : status === "IN_CTRL"
    ? <span className="text-[8px] font-bold px-1.5 py-0.5 rounded bg-green-100 text-green-600 border border-green-200">OK</span>
    : <span className="text-[8px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-400">–</span>;
}

// LOT tab rows — one entry per step showing Start→End times + SPC
function LotRow({ step, startTime, endTime, toolId, spcStatus, isSelected, onClickStart, onClickEnd }: {
  step: string; startTime?: string; endTime?: string; toolId: string;
  spcStatus: string | null; isSelected: boolean;
  onClickStart: () => void; onClickEnd: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (isSelected) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [isSelected]);

  const dotColor = spcStatus === "OOC" ? "bg-red-500" : spcStatus === "IN_CTRL" ? "bg-green-500" : "bg-slate-300";

  return (
    <div ref={ref} className={[
      "border-b border-slate-100 transition-colors",
      isSelected ? "bg-blue-50 border-l-2 border-l-blue-500" : "",
    ].join(" ")}>
      {/* Step header */}
      <div className="flex items-center gap-2 px-3 pt-1.5 pb-0.5">
        <div className={`w-2 h-2 rounded-full shrink-0 ${dotColor}`} />
        <span className="font-mono text-[11px] font-semibold text-slate-700 w-16 shrink-0">{step}</span>
        <span className="text-[10px] text-slate-400 truncate ml-auto">{toolId}</span>
        <SpcBadge status={spcStatus} />
      </div>
      {/* Phase buttons */}
      <div className="flex gap-1 px-3 pb-1.5 pl-7">
        {startTime && (
          <button onClick={onClickStart}
            className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-violet-700 hover:bg-violet-50 rounded px-1.5 py-0.5 transition-colors">
            <PhaseBadge phase="ProcessStart" />
            <span className="font-mono">{fmtTime(startTime)}</span>
          </button>
        )}
        {endTime && (
          <button onClick={onClickEnd}
            className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-teal-700 hover:bg-teal-50 rounded px-1.5 py-0.5 transition-colors">
            <PhaseBadge phase="ProcessEnd" />
            <span className="font-mono">{fmtTime(endTime)}</span>
          </button>
        )}
        {!endTime && (
          <span className="text-[9px] text-amber-500 font-semibold animate-pulse px-1">⏳ 加工中…</span>
        )}
      </div>
    </div>
  );
}

// TOOL tab rows — same two-phase layout
function ToolRow({ lotId, step, startTime, endTime, spcStatus, isSelected, onClickStart, onClickEnd }: {
  lotId: string | null; step: string | null; startTime?: string; endTime?: string;
  spcStatus: string | null; isSelected: boolean;
  onClickStart: () => void; onClickEnd: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (isSelected) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [isSelected]);

  const dotColor = spcStatus === "OOC" ? "bg-red-500" : spcStatus === "IN_CTRL" ? "bg-green-500" : "bg-slate-300";

  return (
    <div ref={ref} className={[
      "border-b border-slate-100 transition-colors",
      isSelected ? "bg-blue-50 border-l-2 border-l-blue-500" : "",
    ].join(" ")}>
      <div className="flex items-center gap-2 px-3 pt-1.5 pb-0.5">
        <div className={`w-2 h-2 rounded-full shrink-0 ${dotColor}`} />
        <span className="font-mono text-[11px] font-semibold text-amber-700 w-20 shrink-0 truncate">{lotId ?? "–"}</span>
        <span className="text-[10px] text-slate-400 truncate ml-auto">{step ?? "–"}</span>
        <SpcBadge status={spcStatus} />
      </div>
      <div className="flex gap-1 px-3 pb-1.5 pl-7">
        {startTime && (
          <button onClick={onClickStart}
            className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-violet-700 hover:bg-violet-50 rounded px-1.5 py-0.5 transition-colors">
            <PhaseBadge phase="ProcessStart" />
            <span className="font-mono">{fmtTime(startTime)}</span>
          </button>
        )}
        {endTime && (
          <button onClick={onClickEnd}
            className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-teal-700 hover:bg-teal-50 rounded px-1.5 py-0.5 transition-colors">
            <PhaseBadge phase="ProcessEnd" />
            <span className="font-mono">{fmtTime(endTime)}</span>
          </button>
        )}
        {!endTime && (
          <span className="text-[9px] text-amber-500 font-semibold animate-pulse px-1">⏳ 加工中…</span>
        )}
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function DualTrackScrubber({ lotID, toolID, onSelect, selectedTime, activeTrack, onTrackChange }: Props) {
  const [lotSteps,    setLotSteps]   = useState<LotStep[]>([]);
  const [toolBatches, setToolBatches] = useState<ToolBatch[]>([]);
  const [loading,     setLoading]    = useState(false);
  const [error,       setError]      = useState<string | null>(null);

  const [sliderVal,   setSliderVal]   = useState<number>(50);
  // activeTrack is now managed by parent (ForensicHall) via props
  const [listOpen,    setListOpen]    = useState<boolean>(false);

  // Refs for stale-closure-safe event handlers
  const minTRef = useRef(0);
  const spanRef = useRef(1);

  const fetchTracks = useCallback(async (lot: string, tool: string) => {
    setLoading(true);
    setError(null);
    try {
      const base = getApiBase();
      const [lotRes, toolRes] = await Promise.all([
        fetch(`${base}/api/v2/ontology/trajectory/lot/${encodeURIComponent(lot)}`),
        fetch(`${base}/api/v2/ontology/trajectory/tool/${encodeURIComponent(tool)}?limit=300`),
      ]);
      if (!lotRes.ok)  throw new Error(`Lot trajectory: ${lotRes.status}`);
      if (!toolRes.ok) throw new Error(`Tool trajectory: ${toolRes.status}`);
      const [lotData, toolData] = await Promise.all([lotRes.json(), toolRes.json()]);
      setLotSteps(lotData.steps ?? []);
      setToolBatches((toolData.batches ?? []).reverse());
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (lotID && toolID) fetchTracks(lotID, toolID);
  }, [lotID, toolID, fetchTracks]);

  // Sync slider when selectedTime changes OR when data loads (lotSteps)
  // Reason: selectedTime may arrive before data fetch completes, making minT/span invalid.
  // Adding lotSteps as dep ensures we re-sync once the timeline range is valid.
  useEffect(() => {
    if (selectedTime && spanRef.current > 0) {
      const ms  = new Date(selectedTime).getTime();
      const pct = Math.max(0, Math.min(100, ((ms - minTRef.current) / spanRef.current) * 100));
      setSliderVal(pct);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTime, lotSteps]);

  // ── Guard states ────────────────────────────────────────────────────────────
  if (!lotID || !toolID) {
    return (
      <div className="h-full flex items-center justify-center bg-white border-t border-slate-200">
        <p className="text-[12px] text-slate-400">Click an OOC alert to load the Forensic Scrubber</p>
      </div>
    );
  }
  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-white border-t border-slate-200">
        <p className="text-[12px] text-slate-400 animate-pulse">Loading tracks…</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="h-full flex items-center justify-center bg-white border-t border-slate-200">
        <p className="text-[12px] text-red-500">{error}</p>
      </div>
    );
  }

  // ── TimePoints — each step emits up to 2 points (Start + End) ──────────────
  const lotPoints: TimePoint[] = lotSteps.flatMap((s, i) => {
    const pts: TimePoint[] = [];
    if (s.start_time) pts.push({
      id: `lot-${i}-start`,
      time: new Date(s.start_time),
      step: s.step, lot_id: lotID, tool_id: s.tool_id ?? toolID,
      spc_status: null,  // SPC only known at ProcessEnd
      track: "lot", processStatus: "ProcessStart",
    });
    if (s.end_time) pts.push({
      id: `lot-${i}-end`,
      time: new Date(s.end_time),
      step: s.step, lot_id: lotID, tool_id: s.tool_id ?? toolID,
      spc_status: s.spc_status ?? null,
      track: "lot", processStatus: "ProcessEnd",
    });
    return pts;
  });

  const toolPoints: TimePoint[] = toolBatches.flatMap((b, i) => {
    const pts: TimePoint[] = [];
    if (b.start_time) pts.push({
      id: `tool-${i}-start`,
      time: new Date(b.start_time),
      step: b.step, lot_id: b.lot_id, tool_id: toolID,
      spc_status: null,
      track: "tool", processStatus: "ProcessStart",
    });
    if (b.end_time) pts.push({
      id: `tool-${i}-end`,
      time: new Date(b.end_time),
      step: b.step, lot_id: b.lot_id, tool_id: toolID,
      spc_status: b.spc_status ?? null,
      track: "tool", processStatus: "ProcessEnd",
    });
    return pts;
  });

  const selMs = selectedTime ? new Date(selectedTime).getTime() : null;

  // ── Timeline math ───────────────────────────────────────────────────────────
  const BUFFER_MS   = 30 * 60 * 1000;
  const lotMs       = lotPoints.map(p => p.time.getTime());
  const hasTimeline = lotPoints.length > 0;
  const lotMinT     = hasTimeline ? Math.min(...lotMs) : 0;
  const lotMaxT     = hasTimeline ? Math.max(...lotMs) : 1;
  const anchorMin   = selMs ? Math.min(lotMinT, selMs) : lotMinT;
  const anchorMax   = selMs ? Math.max(lotMaxT, selMs) : lotMaxT;
  const minT        = anchorMin - BUFFER_MS;
  const maxT        = anchorMax + BUFFER_MS;
  const span        = maxT - minT || 1;
  const frac        = (t: Date) => (t.getTime() - minT) / span;
  const ticks       = hasTimeline ? buildTicks(minT, maxT) : [];

  const toolPointsInWindow = toolPoints.filter(
    p => p.time.getTime() >= minT && p.time.getTime() <= maxT
  );

  // Update refs every render
  minTRef.current = minT;
  spanRef.current = span;

  const toStatus = (s: string | null): "ooc" | "pass" | "normal" =>
    s === "OOC" ? "ooc" : s === "IN_CTRL" ? "pass" : "normal";

  const scrubberEvents: ScrubberEvent[] = [
    ...lotPoints.map(p => ({
      id: p.id, track: "LOT" as const,
      percent: Math.max(0, Math.min(100, frac(p.time) * 100)),
      timeMs: p.time.getTime(),
      step: p.step, lot_id: p.lot_id, tool_id: p.tool_id,
      status: toStatus(p.spc_status),
      processStatus: p.processStatus,
    })),
    ...toolPointsInWindow.map(p => ({
      id: p.id, track: "TOOL" as const,
      percent: Math.max(0, Math.min(100, frac(p.time) * 100)),
      timeMs: p.time.getTime(),
      step: p.step, lot_id: p.lot_id, tool_id: p.tool_id,
      status: toStatus(p.spc_status),
      processStatus: p.processStatus,
    })),
  ];

  // ── Handlers ────────────────────────────────────────────────────────────────
  const handleScrub = (val: number) => setSliderVal(val);

  const handleSnap = (val: number) => {
    const candidates = scrubberEvents.filter(e => e.track === activeTrack);
    if (!candidates.length) return;
    const nearest = candidates.reduce((prev, curr) =>
      Math.abs(curr.percent - val) < Math.abs(prev.percent - val) ? curr : prev
    );
    setSliderVal(nearest.percent);
    onSelect({
      lotID:         nearest.lot_id ?? lotID,
      step:          nearest.step,
      eventTime:     new Date(nearest.timeMs).toISOString(),
      toolID:        activeTrack === "LOT" ? (nearest.tool_id ?? toolID) : toolID,
      processStatus: nearest.processStatus,
    });
  };

  const isLotRowSelected  = (s: LotStep)   => {
    if (selMs === null) return false;
    const st = s.start_time ? new Date(s.start_time).getTime() : null;
    const et = s.end_time   ? new Date(s.end_time).getTime()   : null;
    return (st !== null && Math.abs(st - selMs) < 2000) ||
           (et !== null && Math.abs(et - selMs) < 2000);
  };
  const isToolRowSelected = (b: ToolBatch) => {
    if (selMs === null) return false;
    const st = b.start_time ? new Date(b.start_time).getTime() : null;
    const et = b.end_time   ? new Date(b.end_time).getTime()   : null;
    return (st !== null && Math.abs(st - selMs) < 2000) ||
           (et !== null && Math.abs(et - selMs) < 2000);
  };

  // ── Playhead time display ───────────────────────────────────────────────────
  const playheadTimeStr = (() => {
    const ms = minT + (sliderVal / 100) * span;
    return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  })();

  // ── SVG ruler constants ─────────────────────────────────────────────────────
  const SVG_W   = 1000;
  const PAD_L   = 4;    // left padding (px in viewBox)
  const PAD_R   = 4;    // right padding
  const TW      = SVG_W - PAD_L - PAD_R;
  const RULER_Y = 38;   // y of the main ruler line
  const SVG_H   = 72;   // total SVG height

  // Event tick heights (px in viewBox)
  const TICK_OOC    = 20;
  const TICK_PASS   = 12;
  const TICK_NORMAL = 6;

  // Handle (grip) dimensions
  const HDL_W = 22;
  const HDL_H = 28;

  // xPh: playhead x in SVG units
  const xPh = PAD_L + (sliderVal / 100) * TW;

  // Clamp handle so it doesn't overflow SVG
  const hx = Math.min(Math.max(xPh - HDL_W / 2, PAD_L), PAD_L + TW - HDL_W);

  const lotOOC  = lotSteps.filter(s => s.spc_status === "OOC").length;
  const toolOOC = toolBatches.filter(b => b.spc_status === "OOC").length;

  return (
    <div className="h-full flex flex-col overflow-hidden bg-white border-t border-slate-200">

      {/* ── LOT / TOOL Tab Switcher ───────────────────────────────────────────── */}
      <div className="shrink-0 flex border-b border-slate-200">
        {(["LOT", "TOOL"] as const).map(t => {
          const isActive = activeTrack === t;
          const oocCount = t === "LOT" ? lotOOC : toolOOC;
          const count    = t === "LOT" ? lotSteps.length : toolBatches.length;
          const label    = t === "LOT" ? `Lot  ${lotID}` : `Machine  ${toolID}`;
          const accent   = t === "LOT" ? "border-amber-500 text-amber-700" : "border-cyan-500 text-cyan-700";
          const inactive = "border-transparent text-slate-400 hover:text-slate-600 hover:bg-slate-50";
          return (
            <button
              key={t}
              onClick={() => onTrackChange(t)}
              className={[
                "flex-1 flex items-center justify-center gap-2 px-4 py-2.5 border-b-2 transition-all font-medium text-[12px]",
                isActive ? accent : inactive,
              ].join(" ")}
            >
              <span className={`font-bold text-[10px] px-1.5 py-0.5 rounded ${t === "LOT" ? "bg-amber-100 text-amber-600" : "bg-cyan-100 text-cyan-600"}`}>
                {t}
              </span>
              <span className="font-mono">{label}</span>
              <span className="text-[10px] text-slate-400">{count}</span>
              {oocCount > 0 && (
                <span className="text-[9px] font-bold bg-red-100 text-red-600 px-1.5 py-0.5 rounded-full">
                  {oocCount} OOC
                </span>
              )}
            </button>
          );
        })}

        {/* Selected time badge + collapse toggle */}
        <div className="shrink-0 flex items-center gap-2 px-3 border-l border-slate-200">
          {selectedTime && (
            <span className="text-[10px] font-mono bg-blue-50 text-blue-600 border border-blue-200 px-2 py-1 rounded">
              ⚑ {fmtTimeFull(selectedTime)}
            </span>
          )}
          <button
            onClick={() => setListOpen(v => !v)}
            title={listOpen ? "收起清單" : "展開清單"}
            className="text-slate-400 hover:text-slate-600 transition-colors p-1"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              {listOpen
                ? <path d="M2 4l5 5 5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                : <path d="M2 10l5-5 5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              }
            </svg>
          </button>
        </div>
      </div>

      {/* ── Active track event list (collapsible, default collapsed) ─────────── */}
      <div className={`flex flex-col transition-all duration-200 ${listOpen ? "flex-1 overflow-hidden" : "h-0 overflow-hidden"}`}>
        {/* Column headers */}
        {listOpen && (
          <div className="shrink-0 flex items-center gap-2 px-3 py-1 border-b border-slate-200 bg-slate-100">
            <div className="w-2 h-2 shrink-0" />
            {activeTrack === "LOT" ? (
              <>
                <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider w-16 shrink-0">Step</span>
                <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider shrink-0 ml-7">Phase / Time</span>
                <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider truncate ml-auto">Machine</span>
              </>
            ) : (
              <>
                <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider w-20 shrink-0">Lot ID</span>
                <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider shrink-0 ml-7">Phase / Time</span>
                <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider truncate ml-auto">Step</span>
              </>
            )}
            <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider shrink-0 w-10 text-right">SPC</span>
          </div>
        )}
        <div className="overflow-y-auto flex-1">
          {activeTrack === "LOT" ? (
            lotSteps.length === 0
              ? <p className="text-[11px] text-slate-400 text-center py-6">No steps found</p>
              : lotSteps.map((s, i) => (
                  <LotRow
                    key={`lot-row-${i}`}
                    step={s.step}
                    startTime={s.start_time}
                    endTime={s.end_time}
                    toolId={s.tool_id}
                    spcStatus={s.spc_status}
                    isSelected={isLotRowSelected(s)}
                    onClickStart={() => s.start_time && onSelect({
                      lotID, step: s.step, eventTime: s.start_time,
                      toolID: s.tool_id ?? toolID, processStatus: "ProcessStart",
                    })}
                    onClickEnd={() => s.end_time && onSelect({
                      lotID, step: s.step, eventTime: s.end_time,
                      toolID: s.tool_id ?? toolID, processStatus: "ProcessEnd",
                    })}
                  />
                ))
          ) : (
            toolBatches.length === 0
              ? <p className="text-[11px] text-slate-400 text-center py-6">No batches found</p>
              : toolBatches.map((b, i) => (
                  <ToolRow
                    key={`tool-row-${i}`}
                    lotId={b.lot_id}
                    step={b.step}
                    startTime={b.start_time}
                    endTime={b.end_time}
                    spcStatus={b.spc_status}
                    isSelected={isToolRowSelected(b)}
                    onClickStart={() => b.start_time && onSelect({
                      lotID: b.lot_id ?? lotID, step: b.step, eventTime: b.start_time,
                      toolID, processStatus: "ProcessStart",
                    })}
                    onClickEnd={() => b.end_time && onSelect({
                      lotID: b.lot_id ?? lotID, step: b.step, eventTime: b.end_time,
                      toolID, processStatus: "ProcessEnd",
                    })}
                  />
                ))
          )}
        </div>
      </div>

      {/* ── jQuery-style Time Ruler ───────────────────────────────────────────── */}
      {hasTimeline && (
        <div className="shrink-0 border-t border-slate-200 bg-slate-50 px-2 pb-2 pt-1">

          {/* Playhead time label (above ruler, centered on handle) */}
          <div className="relative mb-0.5" style={{ height: 18 }}>
            <div
              className="absolute -translate-x-1/2 text-[11px] font-mono font-semibold text-slate-700 bg-white border border-slate-300 px-2 py-0.5 rounded shadow-sm pointer-events-none select-none"
              style={{ left: `${PAD_L / SVG_W * 100 + (sliderVal / 100) * (TW / SVG_W) * 100}%` }}
            >
              {playheadTimeStr}
            </div>
          </div>

          {/* Ruler + color markers container */}
          <div className="relative select-none" style={{ height: SVG_H }}>

            {/* ── SVG: ruler line, ticks, color markers, handle ── */}
            <svg
              viewBox={`0 0 ${SVG_W} ${SVG_H}`}
              className="absolute inset-0 w-full h-full pointer-events-none"
            >
              {/* ── LOT color markers (above ruler)
                    ProcessStart → small hollow circle at ruler line
                    ProcessEnd   → filled tick upward (color = spc result) ── */}
              {scrubberEvents.filter(e => e.track === "LOT").map(e => {
                const x      = PAD_L + (e.percent / 100) * TW;
                const isSel  = selMs !== null && Math.abs(e.timeMs - selMs) < 2000;
                const selClr = "#2563eb";
                const opac   = activeTrack === "LOT" ? 1 : 0.2;
                if (e.processStatus === "ProcessStart") {
                  const r = isSel ? 4 : 2.5;
                  return <circle key={e.id} cx={x} cy={RULER_Y} r={r}
                    fill="white" stroke={isSel ? selClr : "#a78bfa"} strokeWidth={isSel ? 2 : 1}
                    opacity={opac} />;
                }
                const h = e.status === "ooc" ? TICK_OOC : e.status === "pass" ? TICK_PASS : TICK_NORMAL;
                const c = e.status === "ooc" ? "#ef4444" : e.status === "pass" ? "#22c55e" : "#94a3b8";
                const w = e.status === "ooc" ? 2 : 1;
                return <line key={e.id} x1={x} y1={RULER_Y} x2={x} y2={RULER_Y - h}
                  stroke={isSel ? selClr : c} strokeWidth={isSel ? 2.5 : w} opacity={opac} />;
              })}

              {/* ── TOOL color markers (below ruler) — same Start/End distinction ── */}
              {scrubberEvents.filter(e => e.track === "TOOL").map(e => {
                const x      = PAD_L + (e.percent / 100) * TW;
                const isSel  = selMs !== null && Math.abs(e.timeMs - selMs) < 2000;
                const selClr = "#2563eb";
                const opac   = activeTrack === "TOOL" ? 1 : 0.2;
                if (e.processStatus === "ProcessStart") {
                  const r = isSel ? 4 : 2.5;
                  return <circle key={e.id} cx={x} cy={RULER_Y} r={r}
                    fill="white" stroke={isSel ? selClr : "#a78bfa"} strokeWidth={isSel ? 2 : 1}
                    opacity={opac} />;
                }
                const h = e.status === "ooc" ? TICK_OOC : e.status === "pass" ? TICK_PASS : TICK_NORMAL;
                const c = e.status === "ooc" ? "#ef4444" : e.status === "pass" ? "#22c55e" : "#94a3b8";
                const w = e.status === "ooc" ? 2 : 1;
                return <line key={e.id} x1={x} y1={RULER_Y} x2={x} y2={RULER_Y + h}
                  stroke={isSel ? selClr : c} strokeWidth={isSel ? 2.5 : w} opacity={opac} />;
              })}

              {/* ── Main ruler line ── */}
              <line x1={PAD_L} y1={RULER_Y} x2={PAD_L + TW} y2={RULER_Y}
                    stroke="#94a3b8" strokeWidth="2" />

              {/* ── Minor ticks on ruler ── */}
              {Array.from({ length: 61 }, (_, i) => {
                const x = PAD_L + (i / 60) * TW;
                return <line key={i} x1={x} y1={RULER_Y - 3} x2={x} y2={RULER_Y + 3}
                              stroke="#cbd5e1" strokeWidth="0.8" />;
              })}

              {/* ── Major ticks + labels ── */}
              {ticks.map(tick => {
                const x = PAD_L + ((tick.ms - minT) / span) * TW;
                return (
                  <g key={tick.ms}>
                    <line x1={x} y1={RULER_Y - 7} x2={x} y2={RULER_Y + 7}
                          stroke="#64748b" strokeWidth="1.2" />
                    <text x={x} y={SVG_H - 2} textAnchor="middle"
                          fontSize="9" fill="#64748b" fontFamily="monospace">
                      {tick.label}
                    </text>
                  </g>
                );
              })}

              {/* ── LOT label (above, left) ── */}
              <text x={PAD_L + 4} y={RULER_Y - TICK_OOC - 4} fontSize="8"
                    fill={activeTrack === "LOT" ? "#b45309" : "#d1d5db"} fontFamily="monospace" fontWeight="bold">
                LOT
              </text>

              {/* ── TOOL label (below, left) ── */}
              <text x={PAD_L + 4} y={RULER_Y + TICK_OOC + 12} fontSize="8"
                    fill={activeTrack === "TOOL" ? "#0e7490" : "#d1d5db"} fontFamily="monospace" fontWeight="bold">
                TOOL
              </text>

              {/* ── Playhead vertical line ── */}
              <line x1={xPh} y1={0} x2={xPh} y2={SVG_H}
                    stroke="#2563eb" strokeWidth="1.5" strokeDasharray="4,3" opacity="0.7" />

              {/* ── Grip handle (sits on ruler line) ── */}
              <rect x={hx} y={RULER_Y - HDL_H / 2} width={HDL_W} height={HDL_H}
                    rx="4" fill="#f8fafc" stroke="#94a3b8" strokeWidth="1.5"
                    style={{ filter: "drop-shadow(0 1px 3px rgba(0,0,0,0.15))" }} />
              {/* Grip lines */}
              {[hx + 7, hx + 11, hx + 15].map((gx, i) => (
                <line key={i} x1={gx} y1={RULER_Y - HDL_H / 2 + 6} x2={gx} y2={RULER_Y + HDL_H / 2 - 6}
                      stroke="#94a3b8" strokeWidth="1.2" />
              ))}
            </svg>

            {/* ── Invisible range input overlay (same track area as SVG) ── */}
            <input
              type="range"
              min={0} max={100} step={0.05}
              value={sliderVal}
              onChange={e  => handleScrub(+e.target.value)}
              onMouseUp={e => handleSnap(+(e.target as HTMLInputElement).value)}
              onTouchEnd={e => handleSnap(+(e.currentTarget as HTMLInputElement).value)}
              className="absolute top-0 bottom-0 h-full opacity-0 cursor-pointer z-10"
              style={{
                left:   `${(PAD_L / SVG_W) * 100}%`,
                width:  `${(TW / SVG_W) * 100}%`,
                margin: 0, padding: 0,
              }}
            />
          </div>

          {/* ── Color legend ── */}
          <div className="flex items-center gap-4 pt-0.5 px-1 flex-wrap">
            <div className="flex items-center gap-1">
              <svg width="10" height="10"><circle cx="5" cy="5" r="3.5" fill="white" stroke="#a78bfa" strokeWidth="1.5"/></svg>
              <span className="text-[9px] text-slate-400">Start</span>
            </div>
            {[
              { color: "#ef4444", label: "OOC End" },
              { color: "#22c55e", label: "Pass End" },
              { color: "#94a3b8", label: "Normal End" },
            ].map(l => (
              <div key={l.label} className="flex items-center gap-1">
                <div className="w-3 h-0.5 rounded" style={{ backgroundColor: l.color }} />
                <span className="text-[9px] text-slate-400">{l.label}</span>
              </div>
            ))}
            <span className="ml-auto text-[9px] text-slate-400 font-mono">
              LOT {lotSteps.length} steps · TOOL {toolBatches.length} batches
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
