"use client";
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";

function getApiUrl() {
  if (typeof window === "undefined") return "/simulator-api/api/v1";
  const isLocal =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";
  return `${window.location.origin}/simulator-api/api/v1`;
}

// ── Types ──────────────────────────────────────────────────────
interface SubsystemAudit {
  index_entries: number;
  distinct_objects: number;
  compression_ratio: number | null;
  newest_event_time: string | null;
  oldest_event_time: string | null;
}

interface AuditData {
  subsystems: Record<string, SubsystemAudit>;
  event_fanout: { TOOL_EVENT: number; LOT_EVENT: number };
  master_data: {
    recipe_versions: number;
    apc_models: number;
    lots: number;
    tools: number;
  };
}

// ── Visual config per subsystem ────────────────────────────────
const SUBSYSTEM_CONFIG: Record<
  string,
  { color: string; bar: string; badge: string; desc: string }
> = {
  APC: {
    color: "text-teal-700",
    bar:   "bg-teal-500",
    badge: "bg-teal-100 text-teal-700 border-teal-200",
    desc:  "Run-to-Run parameter snapshots",
  },
  DC: {
    color: "text-indigo-700",
    bar:   "bg-indigo-500",
    badge: "bg-indigo-100 text-indigo-700 border-indigo-200",
    desc:  "30-sensor high-frequency data collection",
  },
  SPC: {
    color: "text-amber-700",
    bar:   "bg-amber-500",
    badge: "bg-amber-100 text-amber-700 border-amber-200",
    desc:  "5 control charts (xbar / R / S / p / c)",
  },
  RECIPE: {
    color: "text-sky-700",
    bar:   "bg-sky-500",
    badge: "bg-sky-100 text-sky-700 border-sky-200",
    desc:  "Static recipe master — versioned objects",
  },
};

// ── Helpers ────────────────────────────────────────────────────
function fmtNum(n: number): string {
  return n.toLocaleString();
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toISOString().replace("T", " ").slice(0, 19) + "Z";
}

function BarCell({
  value,
  max,
  barClass,
}: {
  value: number;
  max: number;
  barClass: string;
}) {
  const pct = max > 0 ? Math.max(4, (value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-slate-100 rounded-full h-2 overflow-hidden">
        <div
          className={`${barClass} h-2 rounded-full transition-all duration-700`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-[13px] font-bold text-slate-700 w-14 text-right shrink-0">
        {fmtNum(value)}
      </span>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────
export default function AuditTracker() {
  const router = useRouter();

  const [data,      setData]      = useState<AuditData | null>(null);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<Date | null>(null);

  const fetchAudit = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${getApiUrl()}/audit`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as AuditData;
      setData(json);
      setLastFetch(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // Auto-refresh every 10 s
  useEffect(() => {
    fetchAudit();
    const id = setInterval(fetchAudit, 10_000);
    return () => clearInterval(id);
  }, [fetchAudit]);

  const maxIndex = data
    ? Math.max(...Object.values(data.subsystems).map((s) => s.index_entries), 1)
    : 1;
  const maxObjs = data
    ? Math.max(...Object.values(data.subsystems).map((s) => s.distinct_objects), 1)
    : 1;

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-slate-50 no-select">
      {/* Header */}
      <header className="h-14 border-b border-slate-200 bg-white flex shrink-0 items-center justify-between px-6 shadow-sm z-20">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-6 h-6 rounded bg-violet-100 text-violet-600">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"
                 fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>
            </svg>
          </div>
          <h1 className="text-sm font-bold tracking-wide text-slate-800">
            Agentic OS · Digital Twin
            <span className="text-slate-400 font-medium ml-2 text-[12px]">| OBJECT & INDEX TRACKER</span>
          </h1>
        </div>

        <div className="flex items-center gap-3">
          {lastFetch && (
            <span className="text-[11px] font-mono text-slate-400">
              updated {lastFetch.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchAudit}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-white border border-slate-300
                       text-slate-600 hover:bg-slate-50 transition shadow-sm font-semibold text-sm
                       disabled:opacity-50"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" strokeWidth="2.5"
              strokeLinecap="round" strokeLinejoin="round"
              className={loading ? "animate-spin" : ""}
            >
              <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
            </svg>
            Refresh
          </button>
          <button
            onClick={() => router.push("/")}
            className="flex items-center gap-2 px-3 py-1.5 rounded bg-white border border-slate-300
                       text-slate-600 hover:bg-slate-50 transition shadow-sm font-semibold text-sm"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
                 fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>
            </svg>
            Dashboard
          </button>
        </div>
      </header>

      {/* Body */}
      <main className="flex-1 overflow-y-auto px-8 py-6 space-y-6">

        {error && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-700 font-mono">
            ⚠ {error}
          </div>
        )}

        {/* Event Fan-out + Master Data row */}
        {data && (
          <div className="grid grid-cols-2 gap-4">
            {/* Event Fan-out */}
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
              <h2 className="font-bold text-slate-700 text-sm mb-4 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
                Event Fan-out Counter
              </h2>
              <div className="grid grid-cols-2 gap-4">
                {(["TOOL_EVENT", "LOT_EVENT"] as const).map((et) => (
                  <div key={et} className="bg-slate-50 rounded-lg px-4 py-3 text-center border border-slate-100">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">{et}</div>
                    <div className="font-mono text-2xl font-black text-slate-800">
                      {fmtNum(data.event_fanout[et])}
                    </div>
                    <div className="text-[10px] text-slate-400 mt-1">events written</div>
                  </div>
                ))}
              </div>
              <div className="mt-3 text-[11px] text-slate-400 font-mono text-center">
                Ratio TOOL : LOT ={" "}
                {data.event_fanout.LOT_EVENT > 0
                  ? (data.event_fanout.TOOL_EVENT / data.event_fanout.LOT_EVENT).toFixed(2)
                  : "—"}
                &nbsp;(should be 1:1)
              </div>
            </div>

            {/* Master Data */}
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
              <h2 className="font-bold text-slate-700 text-sm mb-4 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-sky-500 inline-block" />
                Master Data Objects (Static)
              </h2>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: "Recipe Versions",  value: data.master_data.recipe_versions, color: "text-sky-700" },
                  { label: "APC Models",        value: data.master_data.apc_models,      color: "text-teal-700" },
                  { label: "Lots Registered",   value: data.master_data.lots,            color: "text-violet-700" },
                  { label: "Tools Registered",  value: data.master_data.tools,           color: "text-rose-700" },
                ].map(({ label, value, color }) => (
                  <div key={label} className="bg-slate-50 rounded-lg px-4 py-3 border border-slate-100">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">{label}</div>
                    <div className={`font-mono text-xl font-black ${color}`}>{fmtNum(value)}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Subsystem Audit Table */}
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 bg-slate-50/60 flex items-center justify-between">
            <h2 className="font-bold text-slate-700 text-sm flex items-center gap-2">
              <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24"
                   fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                   className="text-violet-500">
                <rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>
              </svg>
              Subsystem Index vs Actual Data Objects
            </h2>
            <span className="text-[11px] font-mono text-slate-400">
              Auto-refresh 10s
            </span>
          </div>

          {!data && !loading && (
            <div className="py-16 text-center text-slate-400 font-mono text-sm">No data yet.</div>
          )}
          {loading && !data && (
            <div className="py-16 text-center text-slate-400 font-mono text-sm animate-pulse">Loading…</div>
          )}

          {data && (
            <div className="divide-y divide-slate-100">
              {/* Column headers */}
              <div className="grid grid-cols-[180px_1fr_1fr_120px_1fr_1fr] gap-4 px-5 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-400 bg-slate-50/40">
                <div>Subsystem</div>
                <div>Index Entries (calls)</div>
                <div>Actual Data Objects</div>
                <div className="text-center">Ratio</div>
                <div>Oldest Snapshot</div>
                <div>Newest Snapshot</div>
              </div>

              {Object.entries(data.subsystems).map(([name, stats]) => {
                const cfg = SUBSYSTEM_CONFIG[name] ?? {
                  color: "text-slate-700",
                  bar:   "bg-slate-400",
                  badge: "bg-slate-100 text-slate-700 border-slate-200",
                  desc:  "",
                };
                return (
                  <div key={name}
                       className="grid grid-cols-[180px_1fr_1fr_120px_1fr_1fr] gap-4 px-5 py-4 items-center hover:bg-slate-50/50 transition-colors">
                    {/* Name */}
                    <div>
                      <span className={`inline-block px-2.5 py-1 rounded border text-[11px] font-bold ${cfg.badge} mr-0`}>
                        {name}
                      </span>
                      <div className="text-[10px] text-slate-400 mt-1 leading-tight">{cfg.desc}</div>
                    </div>

                    {/* Index entries bar */}
                    <BarCell value={stats.index_entries}  max={maxIndex} barClass={cfg.bar} />

                    {/* Distinct objects bar */}
                    <BarCell value={stats.distinct_objects} max={maxObjs} barClass={`${cfg.bar} opacity-60`} />

                    {/* Compression ratio */}
                    <div className="text-center">
                      {stats.compression_ratio !== null ? (
                        <span className={`font-mono text-[13px] font-black ${cfg.color}`}>
                          {stats.compression_ratio.toFixed(1)}×
                        </span>
                      ) : (
                        <span className="text-slate-300 font-mono text-sm">—</span>
                      )}
                      <div className="text-[9px] text-slate-400 mt-0.5">calls/object</div>
                    </div>

                    {/* Oldest */}
                    <div className="font-mono text-[11px] text-slate-500">
                      {fmtTime(stats.oldest_event_time)}
                    </div>

                    {/* Newest */}
                    <div className="font-mono text-[11px] text-slate-500">
                      {fmtTime(stats.newest_event_time)}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Explanation note */}
        <div className="bg-violet-50 border border-violet-200 rounded-xl px-5 py-4 text-sm text-violet-700">
          <p className="font-bold mb-1">How to read this table</p>
          <p className="text-[13px] leading-relaxed">
            <strong>Index Entries</strong> = total times each subsystem was called (one snapshot per process step).&nbsp;
            <strong>Actual Data Objects</strong> = number of unique physical objects stored (e.g., 20 recipe versions).&nbsp;
            <strong>Ratio</strong> shows data reuse: RECIPE typically shows a high ratio because many runs share the same recipe version,
            while DC &amp; SPC ratios approach 1× because each snapshot is unique.
          </p>
        </div>
      </main>
    </div>
  );
}
