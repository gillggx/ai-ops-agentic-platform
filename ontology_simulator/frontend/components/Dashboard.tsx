"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Wifi, WifiOff, Activity, AlertTriangle, Radio, Clock, Search } from "lucide-react";
import { useMachineStore } from "@/hooks/useMachineStore";
import { useConsole } from "@/hooks/useConsole";
import { MachineState } from "@/lib/types";
import MachineCard from "./MachineCard";
import TopologyView, { TopoNode } from "./TopologyView";
import RightInspector from "./RightInspector";
import ConsolePanel from "./ConsolePanel";
import NexusCenter from "./NexusCenter";
import ArchView from "./ArchView";
import LotTimelinePanel, { LotStepEvent } from "./LotTimelinePanel";
import ObjectIndexExplorer, {
  useObjIndex,
  ObjIndexProvider,
  ObjIndexLeftPanel,
  ObjIndexCenterPanel,
  ObjIndexRightPanel,
} from "./ObjectIndexExplorer";

function getApiUrl() {
  if (typeof window === "undefined") return "/simulator-api/api/v1";
  const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
  return `${window.location.origin}/simulator-api/api/v1`;
}

function priorityOf(m: MachineState): number {
  if (m.stage === "STAGE_DONE_OOC") return 0;
  if (m.stage !== "STAGE_IDLE")     return 1;
  return 2;
}

// ── Event timeline item ───────────────────────────────────────
interface EventDoc {
  eventTime: string;
  eventType: string;
  lotID: string;
  toolID: string;
  step: string;
  recipeID?: string | null;
  spc_status?: string | null;
  status?: string | null;
}

function TraceTimeline({
  toolId,
  selectedTime,
  onSelect,
  addLog,
}: {
  toolId: string;
  selectedTime: string | null;
  onSelect: (evt: EventDoc) => void;
  addLog: (type: "API_REQ" | "API_RES" | "ERROR", text: string) => void;
}) {
  const [events, setEvents] = useState<EventDoc[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const url = `${getApiUrl()}/events?toolID=${toolId}&limit=50`;
    setLoading(true);
    addLog("API_REQ", `GET ${url}`);
    fetch(url)
      .then(r => r.json())
      .then((docs: EventDoc[]) => {
        // Group by (step, lotID) — ProcessEnd always wins over ProcessStart.
        // Prevents recycled lots (same step run again) from showing ⏳ Processing
        // over an already-completed PASS/OOC result.
        const groupMap = new Map<string, EventDoc>();
        for (const d of docs) {
          if (d.eventType !== "TOOL_EVENT") continue;
          const key = `${d.step}|${d.lotID}`;
          const existing = groupMap.get(key);
          if (!existing) {
            groupMap.set(key, d);
          } else if (existing.status === "ProcessStart" && d.status !== "ProcessStart") {
            groupMap.set(key, d); // ProcessEnd supersedes ProcessStart
          }
        }
        const deduped = Array.from(groupMap.values())
          .sort((a, b) => new Date(b.eventTime).getTime() - new Date(a.eventTime).getTime())
          .slice(0, 30);
        addLog("API_RES", `events for ${toolId}: ${deduped.length} steps`);
        setEvents(deduped);
      })
      .catch(e => addLog("ERROR", `events fetch: ${e}`))
      .finally(() => setLoading(false));
  }, [toolId, addLog]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <span className="text-[12px] text-slate-400">Loading events…</span>
      </div>
    );
  }

  if (events.length === 0) {
    return <p className="text-[12px] text-slate-400 px-3 py-4">No events yet for {toolId}.</p>;
  }

  return (
    <div className="relative border-l-2 border-slate-200 ml-5 pl-4 py-2 space-y-4">
      {events.map((evt, i) => {
        const ts = new Date(evt.eventTime);
        const timeStr = `${String(ts.getHours()).padStart(2,"0")}:${String(ts.getMinutes()).padStart(2,"0")}:${String(ts.getSeconds()).padStart(2,"0")}`;
        const isSelected = selectedTime === evt.eventTime;
        const isOOC        = evt.spc_status === "OOC";
        const isInProgress = evt.status === "ProcessStart";

        return (
          <div
            key={i}
            onClick={() => onSelect(evt)}
            className={[
              "relative cursor-pointer group",
              isSelected ? "bg-purple-50 p-2 rounded border border-purple-100 -ml-2 mr-2" : "",
            ].join(" ")}
          >
            <div className={[
              "absolute -left-[22px] top-1 w-3 h-3 rounded-full border-2 transition-colors",
              isSelected
                ? "bg-purple-100 border-purple-500"
                : isOOC
                  ? "bg-amber-50 border-amber-400"
                  : isInProgress
                    ? "bg-blue-50 border-blue-300"
                    : "bg-white border-slate-300 group-hover:border-purple-400",
            ].join(" ")} />

            <div className="flex items-center justify-between">
              <span className={`text-[10px] font-bold ${isSelected ? "text-purple-600" : "text-slate-400"}`}>
                {timeStr}{isSelected ? " (LOCKED)" : ""}
              </span>
              {isOOC && (
                <span className="text-[9px] font-bold bg-amber-100 text-amber-700 px-1 rounded ml-1">
                  SPC OOC
                </span>
              )}
            </div>
            <div className={`text-[11px] font-mono font-bold mt-0.5 ${isSelected ? "text-purple-900" : "text-slate-700"}`}>
              {evt.step} · {evt.lotID}
              {isInProgress
                ? <span className="text-[9px] bg-blue-100 text-blue-600 px-1 rounded ml-1 font-normal">⏳ Processing</span>
                : !isOOC && <span className="text-[9px] bg-green-100 text-green-700 px-1 rounded ml-1 font-normal">PASS</span>
              }
            </div>
            {evt.recipeID && (
              <div className={`text-[10px] ${isSelected ? "text-purple-500" : "text-slate-400"}`}>
                {evt.recipeID}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Main Dashboard ────────────────────────────────────────────
export default function Dashboard() {
  const router = useRouter();
  const { logs, addLog, clear } = useConsole();
  const { machines, connected, acknowledge } = useMachineStore(addLog);

  const [selectedId,      setSelectedId]      = useState<string | null>(null);
  const [activeNode,      setActiveNode]       = useState<TopoNode | null>(null);
  const [mode,            setMode]             = useState<"LIVE" | "TRACE">("LIVE");
  const [traceEventTime,  setTraceEventTime]   = useState<string | null>(null);
  const [traceSnapshot,   setTraceSnapshot]    = useState<MachineState | null>(null);
  const [hideIdle,        setHideIdle]         = useState(false);
  const [clock,           setClock]            = useState("");
  const [consoleOpen,     setConsoleOpen]      = useState(false);
  const [centerTab,       setCenterTab]        = useState<"TOPOLOGY" | "NEXUS" | "LOT_TRACE" | "OBJ_INDEX" | "ARCH">("TOPOLOGY");

  // Object Index shared state (Mode C)
  const objIndexState = useObjIndex();

  useEffect(() => {
    if (mode === "TRACE") return;
    setClock(new Date().toTimeString().split(" ")[0]);
    const t = setInterval(() => setClock(new Date().toTimeString().split(" ")[0]), 1000);
    return () => clearInterval(t);
  }, [mode]);

  const sorted      = [...machines].sort((a, b) => priorityOf(a) - priorityOf(b));
  const liveMachine = machines.find(m => m.id === selectedId) ?? null;
  const selected    = mode === "TRACE" && traceSnapshot ? traceSnapshot : liveMachine;

  const holdCount = machines.filter(m => m.stage === "STAGE_DONE_OOC").length;
  const runCount  = machines.filter(m => m.stage !== "STAGE_IDLE" && m.stage !== "STAGE_DONE_OOC").length;

  const isTrace = mode === "TRACE";

  const displayClock = isTrace && traceEventTime
    ? (() => {
        const d = new Date(traceEventTime);
        return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}:${String(d.getSeconds()).padStart(2,"0")} (LOCKED)`;
      })()
    : clock;

  const handleSelectMachine = useCallback((m: MachineState) => {
    setSelectedId(m.id);
    setActiveNode(null);
    setTraceEventTime(null);
    setTraceSnapshot(null);
  }, []);

  const handleNodeClick = useCallback((node: TopoNode) => {
    setActiveNode(node);
  }, []);

  const handleSetLive = useCallback(() => {
    setMode("LIVE");
    setTraceEventTime(null);
    setTraceSnapshot(null);
    addLog("USER", "Mode → LIVE");
  }, [addLog]);

  const handleSetTrace = useCallback(() => {
    setMode("TRACE");
    addLog("USER", "Mode → TRACE");
  }, [addLog]);

  const handleTraceSelect = useCallback((evt: EventDoc | LotStepEvent) => {
    setTraceEventTime(evt.eventTime);
    setActiveNode(null);
    const stepNum = parseInt(evt.step.split("_")[1]);
    const apcId   = `APC-${String(stepNum).padStart(3, "0")}`;
    setTraceSnapshot({
      id:              evt.toolID,
      stage:           evt.spc_status === "OOC" ? "STAGE_DONE_OOC" : "STAGE_DONE_PASS",
      lotId:           evt.lotID,
      recipe:          evt.recipeID ?? null,
      step:            evt.step,
      apcId,
      apc:             { active: true, mode: "Run-to-Run" },
      dc:              { active: true, collectionPlan: "HIGH_FREQ" },
      spc:             { active: true },
      bias:            null, biasTrend: null, biasAlert: false,
      reflection:      null,
      lastEvent:       evt.eventTime,
      processStartTime: null,
      holdType:        null,
    });
    addLog("TRACE", `Snapshot → ${evt.toolID} ${evt.step} ${evt.lotID} @ ${evt.eventTime}`);
  }, [addLog]);

  return (
    <div className="h-screen bg-slate-50 flex flex-col overflow-hidden no-select">

      {/* ── Top bar ─────────────────────────────────────────────── */}
      <header className={[
        "shrink-0 h-14 border-b flex items-center px-6 gap-4 shadow-sm z-20 transition-colors duration-300",
        isTrace ? "bg-indigo-950 border-indigo-900" : "bg-white border-slate-200",
      ].join(" ")}>

        <div className="flex items-center gap-3 mr-auto">
          <div className={[
            "w-3 h-3 rounded-sm transition-colors duration-300",
            isTrace ? "bg-indigo-400" : "bg-blue-600",
          ].join(" ")} />
          <h1 className={[
            "text-sm font-bold tracking-wide transition-colors duration-300",
            isTrace ? "text-white" : "text-slate-800",
          ].join(" ")}>
            Agentic OS · Digital Twin
            <span className={[
              "ml-2 text-[11px] font-normal transition-colors duration-300",
              isTrace ? "text-indigo-300" : "text-slate-400",
            ].join(" ")}>
              {isTrace ? "| EVENT TRACING (RCA)" : "| Fab Monitor v1.10"}
            </span>
          </h1>
        </div>

        {!isTrace && (
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <Activity size={11} className="text-blue-400" />
            <span>{runCount} Running</span>
          </div>
        )}

        {!isTrace && holdCount > 0 && (
          <div className="flex items-center gap-1.5 text-xs px-2 py-0.5 rounded bg-amber-50 border border-amber-300 text-amber-700">
            <AlertTriangle size={11} />
            <span className="font-semibold">{holdCount} HOLD</span>
          </div>
        )}

        {!isTrace && (
          <div className={[
            "flex items-center gap-1.5 text-xs px-2 py-0.5 rounded border",
            connected
              ? "border-emerald-300 text-emerald-600 bg-emerald-50"
              : "border-slate-300 text-slate-400",
          ].join(" ")}>
            {connected ? <Wifi size={11} /> : <WifiOff size={11} />}
            <span>{connected ? "WS" : "OFFLINE"}</span>
          </div>
        )}

        {/* LIVE / TRACE toggle */}
        <div className="flex rounded border border-slate-600 overflow-hidden text-[10px] font-semibold">
          <button
            onClick={handleSetLive}
            className={[
              "flex items-center gap-1 px-2.5 py-1.5 transition-colors",
              !isTrace
                ? "bg-emerald-500 text-white"
                : "bg-slate-800 text-slate-400 hover:bg-slate-700",
            ].join(" ")}
          >
            <Radio size={9} /> LIVE
          </button>
          <button
            onClick={handleSetTrace}
            className={[
              "flex items-center gap-1 px-2.5 py-1.5 transition-colors border-l border-slate-600",
              isTrace
                ? "bg-purple-600 text-white"
                : "bg-slate-800 text-slate-400 hover:bg-slate-700",
            ].join(" ")}
          >
            <Clock size={9} /> TRACE
          </button>
        </div>

        {/* OOC Forensic Hall link */}
        <button
          onClick={() => router.push("/forensic")}
          className={[
            "flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1.5 rounded border transition-colors",
            isTrace
              ? "bg-red-900/40 border-red-700 text-red-300 hover:bg-red-900/60"
              : "bg-red-50 border-red-200 text-red-600 hover:bg-red-100",
          ].join(" ")}
        >
          <Search size={11} />
          OOC RCA
        </button>

        <button
          onClick={() => router.push("/history")}
          className={[
            "flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1.5 rounded border transition-colors",
            isTrace
              ? "bg-indigo-800 border-indigo-600 text-indigo-200 hover:bg-indigo-700"
              : "bg-white border-slate-300 text-slate-500 hover:bg-slate-50",
          ].join(" ")}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>
          </svg>
          EXPLORER
        </button>

        <button
          onClick={() => router.push("/audit")}
          className={[
            "flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1.5 rounded border transition-colors",
            isTrace
              ? "bg-indigo-800 border-indigo-600 text-indigo-200 hover:bg-indigo-700"
              : "bg-white border-slate-300 text-slate-500 hover:bg-slate-50",
          ].join(" ")}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>
          </svg>
          AUDIT
        </button>

        <button
          onClick={() => router.push("/aiops")}
          className={[
            "flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1.5 rounded border transition-colors",
            isTrace
              ? "bg-purple-900 border-purple-700 text-purple-300 hover:bg-purple-800"
              : "bg-purple-50 border-purple-200 text-purple-600 hover:bg-purple-100",
          ].join(" ")}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9.663 17h4.673M12 3v1m6.364 1.636-.707.707M21 12h-1M4 12H3m3.343-5.657-.707-.707m2.828 9.9a5 5 0 1 1 7.072 0l-.548.547A3.374 3.374 0 0 0 14 18.469V19a2 2 0 1 1-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
          </svg>
          LAB
        </button>

        <div className={[
          "font-mono text-[12px] px-3 py-1.5 rounded-md border shadow-inner min-w-[100px] text-center transition-colors duration-300",
          isTrace
            ? "bg-indigo-900/60 text-purple-200 border-indigo-700"
            : "bg-slate-50 text-slate-600 border-slate-200",
        ].join(" ")}>
          {displayClock}
        </div>
      </header>

      {/* ── Body ─────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden flex flex-col">

        <div className="flex-1 overflow-hidden grid grid-cols-[240px_1fr_360px]">

          {/* ── LEFT panel ─────────────────────────────────────────── */}
          <aside className="border-r border-slate-200 bg-slate-50 overflow-hidden flex flex-col shadow-[4px_0_15px_rgba(0,0,0,0.03)] z-10">
            <div className="px-3 py-2.5 border-b border-slate-200 bg-white shadow-sm shrink-0 flex items-center justify-between">
              <span className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">
                {isTrace ? "Event Timeline" : "Equipment Setup"}
              </span>
              <span className={`text-[11px] font-semibold ${isTrace ? "text-purple-500" : "text-blue-500"}`}>
                {isTrace && selectedId ? selectedId : `${machines.length} Tools`}
              </span>
            </div>

            {/* TRACE mode sub-tabs */}
            {isTrace && (
              <div className="shrink-0 flex items-center border-b border-slate-200 bg-white px-2">
                {(["TIMELINE", "LOT_TRACE", "OBJ_INDEX"] as const).map(tab => {
                  const active =
                    tab === "TIMELINE"  ? (centerTab === "TOPOLOGY" || centerTab === "NEXUS") :
                    tab === "LOT_TRACE" ? centerTab === "LOT_TRACE" :
                                          centerTab === "OBJ_INDEX";
                  const labels = { TIMELINE: "Timeline", LOT_TRACE: "Lot Trace", OBJ_INDEX: "Obj Index" };
                  return (
                    <button
                      key={tab}
                      onClick={() => {
                        if (tab === "TIMELINE")  setCenterTab("TOPOLOGY");
                        if (tab === "LOT_TRACE") setCenterTab("LOT_TRACE");
                        if (tab === "OBJ_INDEX") setCenterTab("OBJ_INDEX");
                      }}
                      className={[
                        "text-[9px] font-bold px-2 py-2 border-b-2 transition-colors -mb-px",
                        active
                          ? "border-purple-500 text-purple-700"
                          : "border-transparent text-slate-400 hover:text-purple-500",
                      ].join(" ")}
                    >
                      {labels[tab]}
                    </button>
                  );
                })}
              </div>
            )}

            {mode === "LIVE" ? (
              <>
                <div className="px-3 py-1.5 border-b border-slate-100 bg-white shrink-0 flex items-center justify-end">
                  <button
                    onClick={() => setHideIdle(p => !p)}
                    className={[
                      "text-[10px] px-1.5 py-0.5 rounded border transition-colors",
                      hideIdle
                        ? "bg-slate-700 text-white border-slate-700"
                        : "bg-white text-slate-400 border-slate-200 hover:bg-slate-50",
                    ].join(" ")}
                  >
                    {hideIdle ? "Show All" : "Active Only"}
                  </button>
                </div>
                <div className="p-2 space-y-1.5 overflow-y-auto flex-1">
                  {sorted
                    .filter(m => !hideIdle || m.stage !== "STAGE_IDLE")
                    .map(m => (
                    <MachineCard
                      key={m.id}
                      machine={m}
                      isSelected={m.id === selectedId}
                      onClick={handleSelectMachine}
                      onAcknowledge={acknowledge}
                    />
                  ))}
                  {hideIdle && sorted.every(m => m.stage === "STAGE_IDLE") && (
                    <p className="text-[11px] text-slate-400 text-center py-4">All machines idle</p>
                  )}
                </div>
              </>
            ) : (
              <div className="flex-1 overflow-y-auto flex flex-col">
                {/* Machine picker grid (only for Timeline/Nexus sub-tab) */}
                {(centerTab === "TOPOLOGY" || centerTab === "NEXUS") && (
                  <div className="px-2 pt-2 pb-1 grid grid-cols-2 gap-1 border-b border-slate-100 shrink-0">
                    {sorted.map(m => (
                      <button
                        key={m.id}
                        onClick={() => handleSelectMachine(m)}
                        className={[
                          "text-[10px] font-mono px-2 py-1.5 rounded border text-left truncate transition-colors",
                          m.id === selectedId
                            ? "bg-purple-50 border-purple-300 text-purple-700"
                            : "bg-white border-slate-200 text-slate-500 hover:bg-slate-50",
                        ].join(" ")}
                      >
                        {m.id}
                      </button>
                    ))}
                  </div>
                )}

                {/* Timeline (only when Timeline sub-tab active) */}
                {(centerTab === "TOPOLOGY" || centerTab === "NEXUS") && (
                  selectedId ? (
                    <div className="pt-3 pb-2 flex-1 overflow-y-auto">
                      <TraceTimeline
                        toolId={selectedId}
                        selectedTime={traceEventTime}
                        onSelect={handleTraceSelect}
                        addLog={addLog}
                      />
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-400 text-center py-6">Select a machine above</p>
                  )
                )}

                {/* Lot Trace */}
                {centerTab === "LOT_TRACE" && (
                  <div className="flex-1 overflow-hidden">
                    <LotTimelinePanel
                      onStepSelect={handleTraceSelect}
                      selectedTime={traceEventTime}
                    />
                  </div>
                )}

                {/* Obj Index */}
                {centerTab === "OBJ_INDEX" && (
                  <ObjIndexProvider state={objIndexState}>
                    <div className="flex-1 overflow-hidden">
                      <ObjIndexLeftPanel />
                    </div>
                  </ObjIndexProvider>
                )}
              </div>
            )}
          </aside>

          {/* ── CENTER ──────────────────────────────────────────────── */}
          <main className="relative bg-[#0b1120] overflow-hidden border-r border-slate-800 flex flex-col">

            <div className="shrink-0 flex items-center justify-between px-4 pt-3 pb-0 z-10">
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setCenterTab("TOPOLOGY")}
                  className={[
                    "text-[10px] font-bold px-2.5 py-1 rounded-md border transition-colors",
                    centerTab === "TOPOLOGY"
                      ? "bg-slate-800 text-slate-200 border-slate-600 shadow-sm"
                      : "bg-transparent text-slate-500 border-transparent hover:text-slate-300",
                  ].join(" ")}
                >
                  TOPOLOGY
                </button>
                <button
                  onClick={() => setCenterTab("NEXUS")}
                  className={[
                    "text-[10px] font-bold px-2.5 py-1 rounded-md border transition-colors flex items-center gap-1",
                    centerTab === "NEXUS"
                      ? "bg-violet-900/50 text-violet-300 border-violet-700 shadow-sm"
                      : "bg-transparent text-slate-500 border-transparent hover:text-violet-400",
                  ].join(" ")}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="9" height="9" viewBox="0 0 24 24"
                       fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
                    <path d="m8.59 13.51 6.83 3.98M15.41 6.51l-6.82 3.98"/>
                  </svg>
                  NEXUS
                </button>
                <button
                  onClick={() => setCenterTab("ARCH")}
                  className={[
                    "text-[10px] font-bold px-2.5 py-1 rounded-md border transition-colors flex items-center gap-1",
                    centerTab === "ARCH"
                      ? "bg-cyan-900/50 text-cyan-300 border-cyan-700 shadow-sm"
                      : "bg-transparent text-slate-500 border-transparent hover:text-cyan-400",
                  ].join(" ")}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="9" height="9" viewBox="0 0 24 24"
                       fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
                    <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
                  </svg>
                  ARCH
                </button>
              </div>

              {(centerTab === "TOPOLOGY" || centerTab === "LOT_TRACE") && (
                <div className="pointer-events-none text-right">
                  <h2 className="text-base font-bold text-slate-300">
                    {centerTab === "LOT_TRACE" ? "Lot Step Topology" : isTrace ? "Historical Snapshot" : "Context Topology"}
                  </h2>
                  <p className="text-[10px] text-slate-500 mt-0">
                    {centerTab === "LOT_TRACE"
                      ? traceEventTime ? `Step locked · ${displayClock}` : "Select a step from the timeline"
                      : isTrace && traceEventTime
                        ? `Locked at ${displayClock}`
                        : "Click nodes to fetch detail"}
                  </p>
                </div>
              )}
            </div>

            <div className="flex-1 overflow-hidden">
              {(centerTab === "TOPOLOGY" || centerTab === "LOT_TRACE") && (
                <div className="h-full p-4">
                  <TopologyView
                    machine={selected}
                    activeNode={activeNode}
                    onNodeClick={handleNodeClick}
                  />
                </div>
              )}
              {centerTab === "NEXUS" && <NexusCenter />}
              {centerTab === "ARCH"  && (
                <ArchView machineCount={machines.filter(m => m.stage !== "STAGE_IDLE").length} />
              )}
              {centerTab === "OBJ_INDEX" && (
                <ObjIndexProvider state={objIndexState}>
                  <ObjIndexCenterPanel />
                </ObjIndexProvider>
              )}
            </div>

          </main>

          {/* ── RIGHT ───────────────────────────────────────────────── */}
          <aside className="bg-white overflow-hidden shadow-[-4px_0_15px_rgba(0,0,0,0.03)] z-10">
            {centerTab === "OBJ_INDEX" ? (
              <ObjIndexProvider state={objIndexState}>
                <ObjIndexRightPanel />
              </ObjIndexProvider>
            ) : (
              <RightInspector
                machine={selected}
                activeNode={activeNode}
                traceEventTime={mode === "TRACE" ? traceEventTime : null}
                addLog={addLog}
              />
            )}
          </aside>
        </div>

        {/* ── BOTTOM: Console ─────────────────────────────────────── */}
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
