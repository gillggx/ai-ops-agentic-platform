"use client";
import { useState, useEffect, useCallback } from "react";
import dynamic from "next/dynamic";
import type { SankeyAuditData } from "./nexus/SankeyFlow";

// ECharts must only run on client
const SankeyFlow = dynamic(() => import("./nexus/SankeyFlow"), { ssr: false });

function getApiUrl(version: "v1" | "v2") {
  if (typeof window === "undefined") return `http://localhost:8001/api/${version}`;
  const isLocal =
    window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
  const base = isLocal
    ? `http://${window.location.hostname}:8001`
    : `${window.location.origin}/simulator-api`;
  return `${base}/api/${version}`;
}

const BAR_COLORS: Record<string, { idx: string; obj: string }> = {
  APC:    { idx: "#0d9488", obj: "#5eead4" },
  DC:     { idx: "#4f46e5", obj: "#a5b4fc" },
  SPC:    { idx: "#d97706", obj: "#fcd34d" },
  RECIPE: { idx: "#0284c7", obj: "#7dd3fc" },
};

const LABEL_COLORS: Record<string, string> = {
  APC:    "text-teal-600",
  DC:     "text-indigo-600",
  SPC:    "text-amber-600",
  RECIPE: "text-sky-600",
};

export default function NexusCenter() {
  const [audit,       setAudit]       = useState<SankeyAuditData | null>(null);
  const [orphanCount, setOrphanCount] = useState(0);
  const [lastFetch,   setLastFetch]   = useState<string>("");

  const fetchAudit = useCallback(async () => {
    try {
      const [a, o] = await Promise.all([
        fetch(`${getApiUrl("v1")}/audit`).then(r => r.json()) as Promise<SankeyAuditData>,
        fetch(`${getApiUrl("v2")}/ontology/orphans?limit=50`).then(r => r.json()) as Promise<{ total_orphans: number }>,
      ]);
      setAudit(a);
      setOrphanCount(o.total_orphans ?? 0);
      setLastFetch(new Date().toTimeString().split(" ")[0]);
    } catch {/* silent */}
  }, []);

  useEffect(() => {
    fetchAudit();
    const id = setInterval(fetchAudit, 20_000);
    return () => clearInterval(id);
  }, [fetchAudit]);

  const totalEvents = audit
    ? (audit.event_fanout.TOOL_EVENT ?? 0) + (audit.event_fanout.LOT_EVENT ?? 0)
    : 0;
  const totalObjects = audit
    ? Object.values(audit.subsystems).reduce((s, v) => s + v.distinct_objects, 0)
    : 0;

  const ratioData = audit
    ? Object.entries(audit.subsystems).map(([name, s]) => ({
        name,
        indices: s.index_entries,
        objects: s.distinct_objects,
        ratio:   s.compression_ratio ?? 0,
      }))
    : [];

  return (
    <div className="h-full flex flex-col overflow-hidden">

      {/* ── Header bar ──────────────────────────────────────────── */}
      <div className="shrink-0 flex items-center justify-between px-4 py-2.5 border-b border-slate-200 bg-white">
        <div className="flex items-center gap-2.5">
          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"
               fill="none" stroke="#7c3aed" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
            <path d="m8.59 13.51 6.83 3.98M15.41 6.51l-6.82 3.98"/>
          </svg>
          <span className="text-[11px] font-bold text-slate-600 uppercase tracking-widest">
            Ontology Fan-out
          </span>
          {audit && (
            <span className="text-[10px] text-slate-400 font-mono">
              {totalEvents.toLocaleString()} events → {totalObjects.toLocaleString()} objects
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {orphanCount > 0 ? (
            <span className="text-[10px] font-bold bg-red-50 text-red-600 border border-red-200 rounded-full px-2 py-0.5 animate-pulse">
              ⚡ {orphanCount} orphan{orphanCount > 1 ? "s" : ""}
            </span>
          ) : audit ? (
            <span className="text-[10px] font-semibold bg-emerald-50 text-emerald-600 border border-emerald-200 rounded-full px-2 py-0.5">
              ✓ No orphans
            </span>
          ) : null}
          <button
            onClick={fetchAudit}
            className="text-slate-400 hover:text-slate-600 transition-colors text-xs font-mono px-1"
            title="Refresh"
          >
            ↻
          </button>
          {lastFetch && (
            <span className="text-[9px] text-slate-300 font-mono">{lastFetch}</span>
          )}
        </div>
      </div>

      {/* ── Sankey (dark window in center) ──────────────────────── */}
      <div className="shrink-0 bg-slate-900 border-b border-slate-700" style={{ height: "260px" }}>
        {audit ? (
          <SankeyFlow audit={audit} orphanCount={orphanCount} />
        ) : (
          <div className="h-full flex flex-col items-center justify-center gap-2">
            <div className="w-6 h-6 rounded-full border-2 border-violet-500 border-t-transparent animate-spin" />
            <span className="text-[11px] text-slate-600 font-mono">Connecting to OntologySimulator…</span>
          </div>
        )}
      </div>

      {/* ── Ratio stats grid ────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {ratioData.length > 0 ? (
          <>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2.5">
              Object-Index Compression Ratio
            </p>
            <div className="grid grid-cols-2 gap-2">
              {ratioData.map(d => {
                const barTotal = d.indices;
                const objPct   = barTotal > 0 ? (d.objects / barTotal) * 100 : 0;
                const col      = BAR_COLORS[d.name];
                return (
                  <div
                    key={d.name}
                    className="bg-white border border-slate-200 rounded-lg px-3 py-2.5 shadow-sm"
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <span className={`text-[10px] font-bold uppercase tracking-widest ${LABEL_COLORS[d.name] ?? "text-slate-500"}`}>
                        {d.name}
                      </span>
                      <span className={`font-mono text-sm font-black ${LABEL_COLORS[d.name] ?? "text-slate-700"}`}>
                        {d.ratio ? `${d.ratio.toFixed(1)}×` : "—"}
                      </span>
                    </div>

                    {/* Index bar (full width) */}
                    <div className="w-full h-2 rounded-full bg-slate-100 mb-1 overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{ width: "100%", backgroundColor: col?.idx ?? "#7c3aed" }}
                      />
                    </div>
                    {/* Object bar (proportional) */}
                    <div className="w-full h-2 rounded-full bg-slate-100 overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${Math.max(2, objPct)}%`, backgroundColor: col?.obj ?? "#a78bfa" }}
                      />
                    </div>

                    <div className="flex items-center justify-between mt-1.5 text-[9px] font-mono text-slate-400">
                      <span className="flex items-center gap-1">
                        <span className="w-2 h-1.5 rounded-sm inline-block" style={{ backgroundColor: col?.idx }} />
                        {d.indices.toLocaleString()} idx
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="w-2 h-1.5 rounded-sm inline-block" style={{ backgroundColor: col?.obj }} />
                        {d.objects.toLocaleString()} obj
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Total summary */}
            <div className="mt-3 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 flex items-center justify-between">
              <span className="text-[10px] text-slate-500 font-semibold">Total fan-out</span>
              <div className="flex items-center gap-3 text-[10px] font-mono text-slate-600">
                <span><span className="font-bold text-violet-600">{totalEvents.toLocaleString()}</span> process events</span>
                <span className="text-slate-300">→</span>
                <span><span className="font-bold text-teal-600">{totalObjects.toLocaleString()}</span> unique objects</span>
              </div>
            </div>
          </>
        ) : (
          <div className="h-full flex items-center justify-center">
            <span className="text-[11px] text-slate-300 font-mono">Waiting for audit data…</span>
          </div>
        )}
      </div>

    </div>
  );
}
