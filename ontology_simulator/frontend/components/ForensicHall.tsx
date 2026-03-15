"use client";
/**
 * ForensicHall — 2.2.3 OOC Forensic Showcase
 * 獨立頁面 /forensic
 *
 * Layout:
 *   LEFT (280px)  : Global OOC Watchlist
 *   CENTER (flex) : Topology Canvas (65%) + Dual-Track Scrubber (35%)
 *   RIGHT (360px) : Universal Inspector (RightInspector)
 */
import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { MachineState } from "@/lib/types";
import { TopoNode } from "./TopologyView";
import TopologyView from "./TopologyView";
import RightInspector from "./RightInspector";
import OOCWatchlist, { OOCAlert } from "./OOCWatchlist";
import DualTrackScrubber, { ScrubberSelection } from "./DualTrackScrubber";
import { useConsole } from "@/hooks/useConsole";
import ConsolePanel from "./ConsolePanel";

export default function ForensicHall() {
  const router = useRouter();
  const { logs, addLog, clear } = useConsole();

  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [forensicLotID,   setForensicLotID]   = useState<string | null>(null);
  const [forensicToolID,  setForensicToolID]  = useState<string | null>(null);
  const [traceEventTime,  setTraceEventTime]  = useState<string | null>(null);
  const [traceSnapshot,   setTraceSnapshot]   = useState<MachineState | null>(null);
  const [activeNode,      setActiveNode]      = useState<TopoNode | null>(null);
  const [consoleOpen,     setConsoleOpen]     = useState<boolean>(false);

  // ── Per-tab time tracking ────────────────────────────────────────────────────
  // oocAnchorTime: the original OOC event time — never changes after alert selection
  // lotSelectedTime / toolSelectedTime: independent playhead positions per tab
  const [oocAnchorTime,    setOocAnchorTime]    = useState<string | null>(null);
  const [lotSelectedTime,  setLotSelectedTime]  = useState<string | null>(null);
  const [toolSelectedTime, setToolSelectedTime] = useState<string | null>(null);
  const [activeTrack,      setActiveTrack]      = useState<"LOT" | "TOOL">("LOT");

  const buildSnapshot = (
    lotID: string, toolID: string, step: string, eventTime: string
  ): MachineState => {
    const stepNum = parseInt((step ?? "STEP_000").split("_")[1] ?? "0");
    return {
      id:              toolID,
      stage:           "STAGE_DONE_OOC",
      lotId:           lotID,
      recipe:          null,
      step,
      apcId:           `APC-${String(stepNum).padStart(3, "0")}`,
      apc:             { active: true, mode: "Run-to-Run" },
      dc:              { active: true, collectionPlan: "HIGH_FREQ" },
      spc:             { active: true },
      bias:            null, biasTrend: null, biasAlert: false,
      reflection:      null,
      lastEvent:       eventTime,
      processStartTime: null,
      holdType:        null,
    };
  };

  // Stage 1: user clicks OOC alert → load dual-track
  const handleOOCSelect = useCallback((alert: OOCAlert) => {
    setSelectedAlertId(alert.index_id);
    setForensicLotID(alert.lot_id);
    setForensicToolID(alert.tool_id);
    setTraceEventTime(alert.event_time);
    setActiveNode(null);
    setActiveTrack("LOT");

    // Lock the anchor times for both tabs to the OOC event time
    setOocAnchorTime(alert.event_time);
    setLotSelectedTime(alert.event_time);
    setToolSelectedTime(alert.event_time);

    if (alert.lot_id && alert.tool_id && alert.step && alert.event_time) {
      setTraceSnapshot(buildSnapshot(alert.lot_id, alert.tool_id, alert.step, alert.event_time));
    }
    addLog("TRACE", `OOC Alert → ${alert.lot_id} @ ${alert.tool_id} step=${alert.step}`);
  }, [addLog]);

  // Tab switching: LOT→TOOL resets TOOL playhead to oocAnchorTime
  const handleTrackChange = useCallback((track: "LOT" | "TOOL") => {
    setActiveTrack(track);
    if (track === "TOOL") {
      // Always return to OOC anchor time when entering TOOL view
      setToolSelectedTime(oocAnchorTime);
      setTraceEventTime(oocAnchorTime);
    } else {
      // Restore where the user left off in LOT view
      setTraceEventTime(lotSelectedTime);
    }
  }, [oocAnchorTime, lotSelectedTime]);

  // Stage 2/3: user scrubs within a tab → update topology + per-tab time
  const handleScrubberSelect = useCallback((sel: ScrubberSelection) => {
    setTraceEventTime(sel.eventTime);
    setActiveNode(null);

    if (activeTrack === "LOT") {
      setLotSelectedTime(sel.eventTime);
    } else {
      setToolSelectedTime(sel.eventTime);
    }

    if (sel.lotID && sel.step) {
      setTraceSnapshot(
        buildSnapshot(sel.lotID, sel.toolID ?? forensicToolID ?? "", sel.step, sel.eventTime)
      );
    }
    addLog("TRACE", `Scrubber → ${sel.lotID} step=${sel.step} @ ${new Date(sel.eventTime).toLocaleTimeString()}`);
  }, [addLog, forensicToolID, activeTrack]);

  const handleNodeClick = useCallback((node: TopoNode) => {
    setActiveNode(node);
  }, []);

  const lockedTime = traceEventTime
    ? new Date(traceEventTime).toLocaleTimeString()
    : null;

  return (
    <div className="h-screen bg-slate-950 flex flex-col overflow-hidden">

      {/* ── Header ──────────────────────────────────────────────── */}
      <header className="shrink-0 h-14 border-b border-slate-800 flex items-center px-6 gap-4 z-20">
        <button
          onClick={() => router.push("/")}
          className="flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 transition-colors"
        >
          <ArrowLeft size={11} /> DASHBOARD
        </button>

        <div className="w-px h-5 bg-slate-700" />

        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse" />
          <h1 className="text-sm font-bold text-white tracking-wide">
            OOC Forensic Hall
            <span className="ml-2 text-[11px] font-normal text-red-300">
              v2.2.3
            </span>
          </h1>
        </div>

        <div className="ml-auto flex items-center gap-3 text-[10px]">
          {forensicLotID && (
            <>
              <span className="text-slate-500">Case:</span>
              <span className="font-mono text-amber-300">{forensicLotID}</span>
              <span className="text-slate-600">@</span>
              <span className="font-mono text-cyan-300">{forensicToolID}</span>
            </>
          )}
          {lockedTime && (
            <span className="font-mono text-red-300 border border-red-800 px-2 py-0.5 rounded bg-red-950/40">
              ⚑ {lockedTime}
            </span>
          )}
          <button
            onClick={() => router.push("/aiops")}
            className="flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1.5 rounded border border-purple-700 text-purple-300 bg-purple-900/30 hover:bg-purple-900/50 transition-colors"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24"
                 fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9.663 17h4.673M12 3v1m6.364 1.636-.707.707M21 12h-1M4 12H3m3.343-5.657-.707-.707m2.828 9.9a5 5 0 1 1 7.072 0l-.548.547A3.374 3.374 0 0 0 14 18.469V19a2 2 0 1 1-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
            </svg>
            LAB
          </button>
        </div>
      </header>

      {/* ── Body ────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <div className="flex-1 overflow-hidden grid grid-cols-[280px_1fr_360px]">

          {/* LEFT: Global OOC Watchlist */}
          <aside className="overflow-hidden z-10">
            <OOCWatchlist
              onSelect={handleOOCSelect}
              selectedId={selectedAlertId}
            />
          </aside>

          {/* CENTER: Topology Canvas (top 65%) + Dual-Track Scrubber (bottom 35%) */}
          <main className="overflow-hidden border-r border-slate-800 flex flex-col bg-slate-950">

            {/* Topology Canvas */}
            <div className="flex flex-col overflow-hidden" style={{ height: "65%" }}>
              <div className="shrink-0 px-4 py-2 border-b border-slate-800 flex items-center justify-between">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                  Topology Canvas
                </span>
                {!forensicLotID && (
                  <span className="text-[9px] text-slate-600 italic">
                    Click an OOC alert to begin investigation
                  </span>
                )}
              </div>
              <div className="flex-1 overflow-hidden p-4 bg-white/[0.02]">
                <TopologyView
                  machine={traceSnapshot}
                  activeNode={activeNode}
                  onNodeClick={handleNodeClick}
                />
              </div>
            </div>

            {/* Dual-Track Scrubber */}
            <div className="overflow-hidden" style={{ height: "35%" }}>
              <DualTrackScrubber
                lotID={forensicLotID}
                toolID={forensicToolID}
                onSelect={handleScrubberSelect}
                selectedTime={activeTrack === "LOT" ? lotSelectedTime : toolSelectedTime}
                activeTrack={activeTrack}
                onTrackChange={handleTrackChange}
              />
            </div>
          </main>

          {/* RIGHT: Universal Inspector */}
          <aside className="overflow-hidden z-10">
            <RightInspector
              machine={traceSnapshot}
              activeNode={activeNode}
              traceEventTime={traceEventTime}
              addLog={addLog}
            />
          </aside>
        </div>

        {/* Console */}
        <div className="shrink-0">
          <ConsolePanel
            logs={logs}
            onClear={clear}
            isOpen={consoleOpen}
            onToggle={() => setConsoleOpen(v => !v)}
          />
        </div>
      </div>
    </div>
  );
}
