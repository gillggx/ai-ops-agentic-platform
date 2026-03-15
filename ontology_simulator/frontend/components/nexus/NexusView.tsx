"use client";
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import type { SankeyAuditData } from "./SankeyFlow";

// ECharts must only run on client — dynamic import guards SSR
const SankeyFlow = dynamic(() => import("./SankeyFlow"), { ssr: false });

// ── URL helpers ───────────────────────────────────────────────────────────────
function apiUrl(version: "v1" | "v2", path: string): string {
  if (typeof window === "undefined") return `http://localhost:8001/api/${version}${path}`;
  const isLocal =
    window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
  const base = isLocal
    ? `http://${window.location.hostname}:8001`
    : `${window.location.origin}/simulator-api`;
  return `${base}/api/${version}${path}`;
}

// ── Types ─────────────────────────────────────────────────────────────────────
interface EventRecord {
  eventTime:     string;
  lotID:         string;
  toolID:        string;
  step:          string;
  recipeID:      string;
  apcID:         string;
  spc_status:    string;
  eventType:     string;
}

interface ContextNode {
  [key: string]: string | number | boolean | Record<string, unknown> | null | undefined;
}

interface GraphContext {
  root:   { lot_id: string; step: string; event_id: string; event_time: string; spc_status: string; recipe_id?: string; apc_id?: string; tool_id?: string };
  tool:   ContextNode | null;
  recipe: ContextNode | null;
  apc:    ContextNode | null;
  dc:     ContextNode | null;
  spc:    ContextNode | null;
}

interface LotRecord { lot_id: string; status: string }

const SUBSYSTEM_COLORS: Record<string, string> = {
  APC:    "text-teal-400",
  DC:     "text-indigo-400",
  SPC:    "text-amber-400",
  RECIPE: "text-sky-400",
};

const BAR_COLORS: Record<string, { idx: string; obj: string }> = {
  APC:    { idx: "#0d9488", obj: "#5eead4" },
  DC:     { idx: "#4f46e5", obj: "#a5b4fc" },
  SPC:    { idx: "#d97706", obj: "#fcd34d" },
  RECIPE: { idx: "#0284c7", obj: "#7dd3fc" },
};

// ── Sub-components ────────────────────────────────────────────────────────────

function NodeCard({
  title, colorClass, data, maxParams = 5,
}: {
  title: string;
  colorClass: string;
  data: ContextNode | null;
  maxParams?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!data) return null;
  const isOrphan = data.orphan === true;

  const params = data.parameters as Record<string, number> | null | undefined;
  const paramEntries = params ? Object.entries(params) : [];

  return (
    <div className={`rounded-lg border ${isOrphan ? "border-red-500/50 bg-red-950/30" : "border-slate-700 bg-slate-800/60"} p-3`}>
      <div className={`flex items-center justify-between mb-2`}>
        <span className={`text-xs font-bold uppercase tracking-wider ${isOrphan ? "text-red-400" : colorClass}`}>
          {isOrphan ? "⚡ ORPHAN" : title}
        </span>
        {isOrphan && (
          <span className="text-[10px] bg-red-900/60 text-red-300 border border-red-500/40 rounded px-1.5 py-0.5">
            Snapshot Missing
          </span>
        )}
      </div>

      {/* Key fields */}
      <div className="space-y-0.5">
        {Object.entries(data)
          .filter(([k]) => k !== "parameters" && k !== "orphan" && k !== "spc_status")
          .slice(0, 4)
          .map(([k, v]) => (
            <div key={k} className="flex items-center gap-2 text-[11px]">
              <span className="text-slate-500 shrink-0 w-28 truncate">{k}</span>
              <span className="font-mono text-slate-300 truncate">{String(v ?? "—")}</span>
            </div>
          ))}
      </div>

      {/* Parameters preview */}
      {paramEntries.length > 0 && (
        <div className="mt-2 border-t border-slate-700/60 pt-2">
          <button
            onClick={() => setExpanded(e => !e)}
            className="text-[10px] text-slate-500 hover:text-slate-300 font-mono transition-colors flex items-center gap-1"
          >
            <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>▶</span>
            {paramEntries.length} parameters
          </button>
          {expanded && (
            <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 max-h-40 overflow-y-auto">
              {paramEntries.map(([k, v]) => (
                <div key={k} className="flex items-center gap-1 text-[10px]">
                  <span className="text-slate-600 w-16 truncate shrink-0">{k}</span>
                  <span className="font-mono text-teal-300">{typeof v === "number" ? v.toFixed(4) : String(v)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Context Drawer ────────────────────────────────────────────────────────────
function ContextDrawer({
  ctx, loading, onClose,
}: {
  ctx: GraphContext | null;
  loading: boolean;
  onClose: () => void;
}) {
  const spcOOC = ctx?.root?.spc_status === "OOC";

  return (
    <div className="h-full flex flex-col bg-slate-900 border-l border-slate-700 overflow-hidden">
      {/* Drawer header */}
      <div className={`shrink-0 px-4 py-3 border-b flex items-center justify-between
                       ${spcOOC ? "border-red-700/50 bg-red-950/30" : "border-slate-700"}`}>
        {ctx ? (
          <div>
            <div className="flex items-center gap-2">
              <span className="text-white font-bold text-sm">{ctx.root.lot_id}</span>
              <span className="text-slate-400 text-xs">·</span>
              <span className="font-mono text-violet-400 text-xs font-bold">{ctx.root.step}</span>
              {spcOOC && (
                <span className="ml-1 text-[10px] font-bold bg-red-900/60 text-red-300 border border-red-500/40 rounded px-1.5 py-0.5">
                  ⚠ OOC
                </span>
              )}
            </div>
            <div className="text-[10px] text-slate-500 font-mono mt-0.5">
              {new Date(ctx.root.event_time).toISOString().replace("T", " ").slice(0, 19)}Z
            </div>
          </div>
        ) : (
          <span className="text-slate-500 text-sm">Select an event…</span>
        )}
        <button
          onClick={onClose}
          className="text-slate-500 hover:text-slate-300 transition-colors ml-3 shrink-0"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
          </svg>
        </button>
      </div>

      {/* Drawer body */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2.5">
        {loading && (
          <div className="flex items-center justify-center py-16">
            <div className="w-6 h-6 rounded-full border-2 border-violet-500 border-t-transparent animate-spin" />
          </div>
        )}

        {!loading && ctx && (
          <>
            {/* Tool */}
            <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-3">
              <div className="text-xs font-bold text-emerald-400 uppercase tracking-wider mb-1.5">🔧 Tool</div>
              <div className="flex items-center gap-3">
                <span className="font-mono text-white text-sm font-bold">{(ctx.tool as { tool_id?: string })?.tool_id}</span>
                <span className={`text-xs font-bold px-2 py-0.5 rounded-full
                  ${(ctx.tool as { status?: string })?.status === "Busy"
                    ? "bg-emerald-900/60 text-emerald-400 border border-emerald-500/40"
                    : "bg-slate-700 text-slate-400 border border-slate-600"}`}>
                  {(ctx.tool as { status?: string })?.status ?? "—"}
                </span>
              </div>
            </div>

            {/* Recipe */}
            <NodeCard title="📋 Recipe" colorClass={SUBSYSTEM_COLORS.RECIPE} data={ctx.recipe} />
            {/* APC */}
            <NodeCard title="⚡ APC" colorClass={SUBSYSTEM_COLORS.APC} data={ctx.apc} />
            {/* DC */}
            <NodeCard title="📡 DC Sensors" colorClass={SUBSYSTEM_COLORS.DC} data={ctx.dc} />
            {/* SPC */}
            <NodeCard title="🎯 SPC" colorClass={SUBSYSTEM_COLORS.SPC} data={ctx.spc} />
          </>
        )}

        {!loading && !ctx && (
          <div className="py-16 text-center text-slate-600 text-sm">
            Click a timeline event to inspect its context
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function NexusView() {
  const router = useRouter();

  // Audit / Sankey state
  const [audit,       setAudit]       = useState<SankeyAuditData | null>(null);
  const [orphanCount, setOrphanCount] = useState(0);

  // Timeline state
  const [lots,        setLots]        = useState<LotRecord[]>([]);
  const [selectedLot, setSelectedLot] = useState<string>("LOT-0001");
  const [events,      setEvents]      = useState<EventRecord[]>([]);
  const [loadingEvts, setLoadingEvts] = useState(false);

  // Drawer / context state
  const [drawerOpen,    setDrawerOpen]    = useState(false);
  const [ctxLoading,    setCtxLoading]    = useState(false);
  const [graphContext,  setGraphContext]  = useState<GraphContext | null>(null);
  const [activeStep,    setActiveStep]    = useState<string | null>(null);

  // Chart data
  const ratioData = audit
    ? Object.entries(audit.subsystems).map(([name, s]) => ({
        name,
        Indices:  s.index_entries,
        Objects:  s.distinct_objects,
        Ratio:    s.compression_ratio ?? 0,
      }))
    : [];

  // ── Fetch audit + orphans ────────────────────────────────────────────────
  const fetchAudit = useCallback(async () => {
    try {
      const [a, o] = await Promise.all([
        fetch(apiUrl("v1", "/audit")).then(r => r.json()) as Promise<SankeyAuditData>,
        fetch(apiUrl("v2", "/ontology/orphans?limit=50")).then(r => r.json()) as Promise<{ total_orphans: number }>,
      ]);
      setAudit(a);
      setOrphanCount(o.total_orphans ?? 0);
    } catch {/* silent */}
  }, []);

  useEffect(() => {
    fetchAudit();
    const id = setInterval(fetchAudit, 15_000);
    return () => clearInterval(id);
  }, [fetchAudit]);

  // ── Fetch lots for selector ──────────────────────────────────────────────
  useEffect(() => {
    fetch(apiUrl("v1", "/lots"))
      .then(r => r.json())
      .then((data: LotRecord[]) => {
        setLots(data.slice(0, 20));
        if (data.length > 0) setSelectedLot(data[0].lot_id);
      })
      .catch(() => {});
  }, []);

  // ── Fetch events for selected lot ────────────────────────────────────────
  const fetchEvents = useCallback(async (lotId: string) => {
    setLoadingEvts(true);
    try {
      const data = await fetch(apiUrl("v1", `/events?lotID=${lotId}&limit=100`))
        .then(r => r.json()) as EventRecord[];
      // Show TOOL_EVENTs only, deduplicate by step (newest per step)
      const seen = new Set<string>();
      const deduped = data.filter(e => {
        if (e.eventType !== "TOOL_EVENT") return false;
        if (seen.has(e.step)) return false;
        seen.add(e.step);
        return true;
      });
      setEvents(deduped);
    } catch {/* silent */} finally {
      setLoadingEvts(false);
    }
  }, []);

  useEffect(() => { fetchEvents(selectedLot); }, [selectedLot, fetchEvents]);

  // ── Click event → fetch graph context ───────────────────────────────────
  const handleEventClick = useCallback(async (e: EventRecord) => {
    setActiveStep(e.step);
    setDrawerOpen(true);
    setCtxLoading(true);
    setGraphContext(null);
    try {
      const ctx = await fetch(
        apiUrl("v2", `/ontology/context?lot_id=${e.lotID}&step=${e.step}`)
      ).then(r => r.json()) as GraphContext;
      setGraphContext(ctx);
    } catch {/* silent */} finally {
      setCtxLoading(false);
    }
  }, []);

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="h-screen flex flex-col overflow-hidden bg-slate-950 text-slate-100">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <header className="h-13 shrink-0 border-b border-slate-800 bg-slate-900/80 backdrop-blur
                         flex items-center justify-between px-6 z-30">
        <div className="flex items-center gap-3">
          {/* Logo */}
          <div className="w-7 h-7 rounded-lg bg-violet-600/20 border border-violet-500/30
                          flex items-center justify-center">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
                 fill="none" stroke="#a78bfa" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
              <path d="m8.59 13.51 6.83 3.98M15.41 6.51l-6.82 3.98"/>
            </svg>
          </div>
          <div>
            <span className="text-sm font-bold text-white tracking-wide">Agentic OS</span>
            <span className="text-slate-500 text-xs ml-2">· Ontology Nexus</span>
          </div>

          {orphanCount > 0 && (
            <span className="ml-2 text-[11px] font-bold bg-red-900/50 text-red-300
                             border border-red-500/40 rounded-full px-2.5 py-0.5 animate-pulse">
              ⚡ {orphanCount} orphan{orphanCount > 1 ? "s" : ""} detected
            </span>
          )}
          {orphanCount === 0 && audit && (
            <span className="ml-2 text-[11px] font-bold bg-emerald-900/40 text-emerald-400
                             border border-emerald-500/30 rounded-full px-2.5 py-0.5">
              ✓ No orphans
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button onClick={fetchAudit}
                  className="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/60
                             text-slate-400 hover:text-white hover:border-slate-600 transition text-xs font-semibold">
            ↻ Refresh
          </button>
          <button onClick={() => router.push("/audit")}
                  className="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/60
                             text-slate-400 hover:text-white transition text-xs font-semibold">
            Audit
          </button>
          <button onClick={() => router.push("/")}
                  className="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/60
                             text-slate-400 hover:text-white transition text-xs font-semibold">
            Dashboard
          </button>
        </div>
      </header>

      {/* ── Body ──────────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden flex flex-col gap-0">

        {/* ── Sankey Panel ──────────────────────────────────────────────── */}
        <div className="shrink-0 border-b border-slate-800/70 bg-slate-900/40">
          {/* Panel header */}
          <div className="flex items-center justify-between px-6 pt-4 pb-2">
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-4 rounded-full bg-violet-500 inline-block" />
              <span className="text-xs font-bold text-slate-300 uppercase tracking-widest">
                Event Fan-out Sankey
              </span>
              <span className="text-[10px] text-slate-600 ml-1">
                {audit ? `${(audit.event_fanout.TOOL_EVENT + audit.event_fanout.LOT_EVENT).toLocaleString()} events → 4 subsystems → ${Object.values(audit.subsystems).reduce((s, v) => s + v.distinct_objects, 0)} objects` : "Loading…"}
              </span>
            </div>
            <div className="flex items-center gap-4 text-[10px] text-slate-600">
              {["violet:Process Events", "teal:APC", "indigo:DC", "amber:SPC", "sky:Recipe"].map(s => {
                const [color, label] = s.split(":");
                const dot: Record<string, string> = { violet: "bg-violet-500", teal: "bg-teal-500", indigo: "bg-indigo-500", amber: "bg-amber-500", sky: "bg-sky-500" };
                return (
                  <span key={s} className="flex items-center gap-1">
                    <span className={`w-2 h-2 rounded-full ${dot[color]}`} />
                    {label}
                  </span>
                );
              })}
              {orphanCount > 0 && (
                <span className="flex items-center gap-1 text-red-400">
                  <span className="w-2 h-2 rounded-full bg-red-500" />Orphan
                </span>
              )}
            </div>
          </div>

          {/* Chart area */}
          <div className="h-[260px] px-2 pb-2">
            {audit ? (
              <SankeyFlow audit={audit} orphanCount={orphanCount} />
            ) : (
              <div className="h-full flex items-center justify-center">
                <div className="w-8 h-8 rounded-full border-2 border-violet-500 border-t-transparent animate-spin" />
              </div>
            )}
          </div>
        </div>

        {/* ── Bottom two columns ────────────────────────────────────────── */}
        <div className="flex-1 overflow-hidden flex min-h-0">

          {/* ── Event Timeline (left) ──────────────────────────────────── */}
          <div className={`flex flex-col border-r border-slate-800 transition-all duration-300
                           ${drawerOpen ? "w-[30%]" : "w-[55%]"}`}>
            {/* Timeline header */}
            <div className="shrink-0 px-5 py-3 border-b border-slate-800/60 bg-slate-900/20
                            flex items-center gap-3">
              <span className="w-1.5 h-4 rounded-full bg-teal-500 inline-block" />
              <span className="text-xs font-bold text-slate-300 uppercase tracking-widest">
                Event Timeline Inspector
              </span>
              <div className="ml-auto flex items-center gap-2">
                <select
                  value={selectedLot}
                  onChange={e => { setSelectedLot(e.target.value); setDrawerOpen(false); setActiveStep(null); }}
                  className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300
                             px-3 py-1.5 font-mono focus:outline-none focus:border-violet-500"
                >
                  {lots.map(l => (
                    <option key={l.lot_id} value={l.lot_id}>
                      {l.lot_id} — {l.status}
                    </option>
                  ))}
                </select>
                <button onClick={() => fetchEvents(selectedLot)}
                        className="text-slate-500 hover:text-slate-300 transition text-sm font-mono">
                  ↻
                </button>
              </div>
            </div>

            {/* Timeline body */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {loadingEvts ? (
                <div className="flex items-center justify-center py-16">
                  <div className="w-6 h-6 rounded-full border-2 border-teal-500 border-t-transparent animate-spin" />
                </div>
              ) : events.length === 0 ? (
                <div className="py-16 text-center text-slate-600 text-sm font-mono">
                  No events for {selectedLot}
                </div>
              ) : (
                <div className="relative">
                  {/* Vertical rail */}
                  <div className="absolute left-[7px] top-2 bottom-2 w-px bg-slate-700/60" />

                  <div className="space-y-0">
                    {[...events].reverse().map((evt, idx) => {
                      const isOOC    = evt.spc_status === "OOC";
                      const isActive = activeStep === evt.step;
                      return (
                        <button
                          key={`${evt.step}-${idx}`}
                          onClick={() => handleEventClick(evt)}
                          className={`relative flex items-start gap-3 w-full text-left px-0 py-2
                                      group hover:bg-slate-800/30 rounded-lg transition-colors pl-1`}
                        >
                          {/* Node dot */}
                          <div className={`relative z-10 shrink-0 mt-1 w-3.5 h-3.5 rounded-full border-2 transition-all
                            ${isActive
                              ? "scale-125 border-violet-400 bg-violet-500/30 shadow-lg shadow-violet-500/40"
                              : isOOC
                                ? "border-red-500 bg-red-500/20 group-hover:scale-110"
                                : "border-teal-500 bg-teal-500/10 group-hover:scale-110"
                            }`}
                          />

                          {/* Content */}
                          <div className="flex-1 min-w-0 pr-2">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-xs font-bold text-slate-300">{evt.step}</span>
                              {isOOC && (
                                <span className="text-[9px] font-bold bg-red-900/50 text-red-400
                                                 border border-red-500/40 rounded px-1.5 py-0.5">
                                  OOC
                                </span>
                              )}
                              {isActive && (
                                <span className="text-[9px] font-bold bg-violet-900/50 text-violet-400
                                                 border border-violet-500/40 rounded px-1.5 py-0.5 ml-auto">
                                  SELECTED
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-2 mt-0.5">
                              <span className="text-[10px] font-mono text-slate-600">
                                {new Date(evt.eventTime).toISOString().slice(11, 19)}Z
                              </span>
                              <span className="text-[10px] text-slate-600 truncate">{evt.toolID}</span>
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* ── Context Drawer (slides in from right of timeline) ─────── */}
          {drawerOpen && (
            <div className="w-[30%] border-r border-slate-800 overflow-hidden">
              <ContextDrawer
                ctx={graphContext}
                loading={ctxLoading}
                onClose={() => { setDrawerOpen(false); setActiveStep(null); }}
              />
            </div>
          )}

          {/* ── Object-Index Ratio Chart (right) ───────────────────────── */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Chart header */}
            <div className="shrink-0 px-5 py-3 border-b border-slate-800/60 bg-slate-900/20 flex items-center gap-2">
              <span className="w-1.5 h-4 rounded-full bg-sky-500 inline-block" />
              <span className="text-xs font-bold text-slate-300 uppercase tracking-widest">
                Object-Index Ratio
              </span>
            </div>

            {/* Recharts */}
            <div className="flex-1 overflow-hidden px-4 py-4">
              {ratioData.length > 0 ? (
                <ResponsiveContainer width="100%" height="75%">
                  <BarChart data={ratioData} barGap={3} barCategoryGap="30%">
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                    <XAxis
                      dataKey="name"
                      tick={{ fill: "#94a3b8", fontSize: 11, fontWeight: "bold" }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fill: "#64748b", fontSize: 10 }}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={(v: number) => v.toLocaleString()}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1e293b",
                        border: "1px solid #334155",
                        borderRadius: "8px",
                        fontSize: "12px",
                        color: "#e2e8f0",
                      }}
                      formatter={(value: unknown, name: unknown) => [(Number(value ?? 0)).toLocaleString(), String(name ?? "")]}
                    />
                    <Legend
                      wrapperStyle={{ fontSize: "11px", color: "#94a3b8", paddingTop: "8px" }}
                    />
                    <Bar dataKey="Indices" name="Index Entries" radius={[3, 3, 0, 0]}>
                      {ratioData.map(entry => (
                        <Cell key={entry.name} fill={BAR_COLORS[entry.name]?.idx ?? "#7c3aed"} />
                      ))}
                    </Bar>
                    <Bar dataKey="Objects" name="Actual Objects" radius={[3, 3, 0, 0]}>
                      {ratioData.map(entry => (
                        <Cell key={entry.name} fill={BAR_COLORS[entry.name]?.obj ?? "#a78bfa"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center">
                  <div className="w-6 h-6 rounded-full border-2 border-sky-500 border-t-transparent animate-spin" />
                </div>
              )}

              {/* Ratio stats */}
              {ratioData.length > 0 && (
                <div className="grid grid-cols-2 gap-2 mt-2">
                  {ratioData.map(d => (
                    <div key={d.name}
                         className="bg-slate-800/40 border border-slate-700/60 rounded-lg px-3 py-2">
                      <div className="flex items-center justify-between">
                        <span className={`text-[10px] font-bold uppercase tracking-wider
                          ${SUBSYSTEM_COLORS[d.name] ?? "text-slate-400"}`}>{d.name}</span>
                        <span className={`font-mono text-sm font-black
                          ${SUBSYSTEM_COLORS[d.name] ?? "text-slate-300"}`}>
                          {d.Ratio ? `${d.Ratio.toFixed(1)}×` : "—"}
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-600 mt-0.5">
                        {d.Indices.toLocaleString()} idx / {d.Objects.toLocaleString()} obj
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
