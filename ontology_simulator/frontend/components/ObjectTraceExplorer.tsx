"use client";
import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";

function getApiUrl() { return `http://${typeof window !== "undefined" ? window.location.hostname : "localhost"}:8001/api/v1`; }

// ── Types ─────────────────────────────────────────────────────
type SnapshotDoc = Record<string, unknown>;

type ObjectType = "DC" | "APC" | "SPC" | "RECIPE";

// ── Per-type visual config ─────────────────────────────────────
const TYPE_CONFIG: Record<ObjectType, {
  dot: string;
  badge: string;
  label: string;
}> = {
  DC:     { dot: "border-indigo-500 bg-indigo-50",  badge: "bg-indigo-100 text-indigo-700 border-indigo-200",  label: "DC SNAPSHOT"     },
  APC:    { dot: "border-teal-500 bg-teal-50",      badge: "bg-teal-100 text-teal-700 border-teal-200",        label: "APC SNAPSHOT"    },
  SPC:    { dot: "border-amber-500 bg-amber-50",    badge: "bg-amber-100 text-amber-700 border-amber-200",     label: "SPC SNAPSHOT"    },
  RECIPE: { dot: "border-sky-500 bg-sky-50",        badge: "bg-sky-100 text-sky-700 border-sky-200",           label: "RECIPE SNAPSHOT" },
};

// ── JSON syntax highlight ─────────────────────────────────────
function syntaxHighlight(obj: unknown): string {
  const raw = JSON.stringify(obj, null, 2)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return raw
    .replace(/"([^"]+)":/g, '<span class="json-key">"$1"</span>:')
    .replace(/: "([^"]*)"/g, ': <span class="json-str">"$1"</span>')
    .replace(/: (-?[0-9]+\.?[0-9]*)/g, ': <span class="json-num">$1</span>');
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return [
    String(d.getHours()).padStart(2, "0"),
    String(d.getMinutes()).padStart(2, "0"),
    String(d.getSeconds()).padStart(2, "0"),
  ].join(":");
}

function fmtISO(iso: string): string {
  // Return readable ISO-like string
  return new Date(iso).toISOString().replace("T", " ").slice(0, 23) + "Z";
}

// ── Payload extractor ─────────────────────────────────────────
function extractPayload(doc: SnapshotDoc, objectName: ObjectType): unknown {
  if (objectName === "SPC") {
    return doc.charts ?? {};
  }
  const raw = doc.parameters;
  if (typeof raw === "string") {
    try { return JSON.parse(raw); } catch { return {}; }
  }
  return (raw as unknown) ?? {};
}

// ── Timeline card ─────────────────────────────────────────────
function TimelineCard({
  doc,
  objectName,
  isLast,
}: {
  doc: SnapshotDoc;
  objectName: ObjectType;
  isLast: boolean;
}) {
  const cfg      = TYPE_CONFIG[objectName];
  const objectID = (doc.objectID as string) ?? "—";
  const toolID   = (doc.toolID as string) ?? "—";
  const lotID    = (doc.lotID as string) ?? "—";
  const step     = (doc.step as string) ?? "—";
  const eventTime   = (doc.eventTime as string) ?? "";
  const updatedBy   = (doc.updated_by as string) ?? "—";
  const collPlan    = (doc.collection_plan as string) ?? null;
  const mode        = (doc.mode as string) ?? null;
  const spcStatus   = (doc.spc_status as string) ?? null;

  const payload  = extractPayload(doc, objectName);
  const timeStr  = eventTime ? fmtTime(eventTime) : "—";
  const isoStr   = eventTime ? fmtISO(eventTime) : "—";

  return (
    <div className="relative pl-12 pb-8">
      {/* Vertical timeline line */}
      {!isLast && (
        <div className="absolute left-[23px] top-[28px] bottom-0 w-0.5 bg-slate-200" />
      )}

      {/* Timeline dot */}
      <div className={`absolute left-[15px] top-[6px] w-4 h-4 rounded-full border-[3px] z-10 shadow-sm ${cfg.dot}`} />

      {/* Time label left of dot */}
      <div className="absolute left-[-56px] top-[4px] text-[11px] font-bold font-mono text-slate-500 w-14 text-right">
        {timeStr}
      </div>

      {/* Card */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden hover:shadow-md transition-shadow">

        {/* 1. Card Header */}
        <div className="bg-slate-50 border-b border-slate-100 px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className={`px-2 py-1 rounded text-[10px] font-bold border tracking-wider ${cfg.badge}`}>
              {cfg.label}
            </span>
            <span className="font-mono text-[12px] font-bold text-slate-700 truncate max-w-[180px]" title={objectID}>
              {objectID.length > 28 ? objectID.slice(0, 26) + "…" : objectID}
            </span>
          </div>
          <div className="flex items-center gap-3 text-[10px] text-slate-500 font-mono bg-white px-2 py-1 rounded border border-slate-200 shadow-sm shrink-0">
            <span title="Tool ID">⚙️ {toolID}</span>
            <span title="Lot ID">📦 {lotID}</span>
            <span title="Step">🏷️ {step}</span>
          </div>
        </div>

        {/* 2. Metadata bar */}
        <div className="bg-slate-50/50 px-4 py-2 border-b border-slate-100 flex flex-wrap gap-x-5 gap-y-0.5 text-[11px] text-slate-500">
          {collPlan && (
            <div>
              <span className="font-bold text-slate-400">collection_plan: </span>
              <span className="font-mono font-bold text-slate-700">{collPlan}</span>
            </div>
          )}
          {mode && (
            <div>
              <span className="font-bold text-slate-400">mode: </span>
              <span className="font-mono font-bold text-slate-700">{mode}</span>
            </div>
          )}
          {spcStatus && (
            <div>
              <span className="font-bold text-slate-400">spc_status: </span>
              <span className={`font-mono font-bold ${spcStatus === "OOC" ? "text-amber-600" : "text-emerald-600"}`}>
                {spcStatus}
              </span>
            </div>
          )}
          <div>
            <span className="font-bold text-slate-400">updated_by: </span>
            <span className="font-mono font-bold text-slate-700">{updatedBy}</span>
          </div>
          <div>
            <span className="font-bold text-slate-400">eventTime: </span>
            <span className="font-mono font-bold text-slate-700">{isoStr}</span>
          </div>
        </div>

        {/* 3. Payload block */}
        <div className="bg-[#1e293b] rounded-b-xl overflow-x-auto p-4 border-t border-slate-800">
          <pre
            className="text-[12px] font-mono leading-relaxed text-slate-300 m-0 whitespace-pre"
            dangerouslySetInnerHTML={{ __html: syntaxHighlight(payload) }}
          />
        </div>
      </div>
    </div>
  );
}

// ── Left query panel ─────────────────────────────────────────
interface QueryForm {
  objectName: ObjectType;
  targetID: string;
  step: string;
  limit: number;
}

function QueryPanel({
  form,
  loading,
  resultCount,
  onChange,
  onFetch,
}: {
  form: QueryForm;
  loading: boolean;
  resultCount: number | null;
  onChange: (f: QueryForm) => void;
  onFetch: () => void;
}) {
  return (
    <>
      <div className="p-4 border-b border-slate-100 bg-slate-50/50">
        <h2 className="font-bold text-slate-700 flex items-center gap-2 text-sm">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
               className="text-indigo-500">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
          </svg>
          Historical RCA Query
        </h2>
      </div>

      <div className="p-5 space-y-5 overflow-y-auto flex-1 text-sm">
        {/* Object Type */}
        <div className="space-y-2">
          <label className="font-bold text-slate-500 text-[10px] uppercase tracking-wider block">
            Target Object Type
          </label>
          <select
            value={form.objectName}
            onChange={e => onChange({ ...form, objectName: e.target.value as ObjectType })}
            className="w-full border border-slate-300 rounded-md px-3 py-2 bg-slate-50 text-slate-700 font-bold text-sm focus:outline-none focus:border-indigo-500"
          >
            <option value="DC">DC (Data Collection)</option>
            <option value="APC">APC (Adv. Process Control)</option>
            <option value="SPC">SPC (Stat. Process Control)</option>
            <option value="RECIPE">RECIPE (Process Recipe)</option>
          </select>
        </div>

        {/* Context Filters */}
        <div className="space-y-3 pt-4 border-t border-slate-100">
          <label className="font-bold text-slate-500 text-[10px] uppercase tracking-wider block">
            Context Linkage
          </label>

          <div>
            <div className="text-[10px] text-slate-400 mb-1 font-bold">
              Target ID <span className="text-slate-300 font-normal">(LOT-xxxx or EQP-xx)</span>
            </div>
            <input
              type="text"
              value={form.targetID}
              onChange={e => onChange({ ...form, targetID: e.target.value })}
              placeholder="e.g. EQP-01"
              className="w-full border border-slate-300 rounded-md px-3 py-1.5 bg-white text-slate-700 font-mono text-xs focus:outline-none focus:border-indigo-500 placeholder:text-slate-300"
            />
          </div>

          <div>
            <div className="text-[10px] text-slate-400 mb-1 font-bold">
              Step <span className="text-slate-300 font-normal">(optional, e.g. STEP_007)</span>
            </div>
            <input
              type="text"
              value={form.step}
              onChange={e => onChange({ ...form, step: e.target.value })}
              placeholder="leave blank = all steps"
              className="w-full border border-slate-300 rounded-md px-3 py-1.5 bg-white text-slate-700 font-mono text-xs focus:outline-none focus:border-indigo-500 placeholder:text-slate-300"
            />
          </div>

          <div>
            <div className="text-[10px] text-slate-400 mb-1 font-bold">Limit</div>
            <select
              value={form.limit}
              onChange={e => onChange({ ...form, limit: Number(e.target.value) })}
              className="w-full border border-slate-300 rounded-md px-3 py-1.5 bg-slate-50 text-slate-700 font-bold text-sm focus:outline-none focus:border-indigo-500"
            >
              {[10, 20, 50, 100].map(n => (
                <option key={n} value={n}>Last {n} records</option>
              ))}
            </select>
          </div>
        </div>

        {/* Result count */}
        {resultCount !== null && (
          <div className="pt-2 border-t border-slate-100 text-[11px] text-slate-400 font-mono">
            {resultCount === 0
              ? "No records found."
              : `${resultCount} snapshot${resultCount === 1 ? "" : "s"} returned`}
          </div>
        )}
      </div>

      {/* Execute button */}
      <div className="p-4 border-t border-slate-100 bg-slate-50 shrink-0">
        <button
          onClick={onFetch}
          disabled={loading || !form.targetID.trim()}
          className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed
                     text-white font-bold py-2.5 px-4 rounded shadow-sm transition-colors
                     flex justify-center items-center gap-2 text-sm"
        >
          {loading ? (
            <>
              <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg"
                   fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
              </svg>
              Fetching…
            </>
          ) : (
            <>
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
                   fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>
              </svg>
              Fetch Historical Data
            </>
          )}
        </button>
      </div>
    </>
  );
}

// ── Main component ─────────────────────────────────────────────
export default function ObjectTraceExplorer() {
  const router = useRouter();

  const [form, setForm] = useState<QueryForm>({
    objectName: "DC",
    targetID:   "EQP-01",
    step:       "",
    limit:      20,
  });
  const [results,  setResults]  = useState<SnapshotDoc[] | null>(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  const handleFetch = useCallback(async () => {
    if (!form.targetID.trim()) return;
    setLoading(true);
    setError(null);

    const params = new URLSearchParams({
      targetID:   form.targetID.trim(),
      objectName: form.objectName,
      limit:      String(form.limit),
    });
    if (form.step.trim()) params.set("step", form.step.trim());

    const url = `${getApiUrl()}/analytics/history?${params}`;
    try {
      const res = await fetch(url);
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as Record<string, unknown>;
        throw new Error((body?.detail as string) ?? `HTTP ${res.status}`);
      }
      const docs = await res.json() as SnapshotDoc[];
      // history endpoint returns oldest-first; show newest-first in timeline
      setResults([...docs].reverse());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResults(null);
    } finally {
      setLoading(false);
    }
  }, [form]);

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-slate-50 no-select">

      {/* Header */}
      <header className="h-14 border-b border-slate-200 bg-white flex shrink-0 items-center justify-between px-6 shadow-sm z-20">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-6 h-6 rounded bg-indigo-100 text-indigo-600">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"
                 fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>
            </svg>
          </div>
          <h1 className="text-sm font-bold tracking-wide text-slate-800">
            Agentic OS · Digital Twin
            <span className="text-slate-400 font-medium ml-2 text-[12px]">| OBJECT TRACE EXPLORER</span>
          </h1>
        </div>

        <button
          onClick={() => router.push("/")}
          className="flex items-center gap-2 px-3 py-1.5 rounded bg-white border border-slate-300 text-slate-600 hover:bg-slate-50 transition shadow-sm font-semibold text-sm"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>
          </svg>
          Dashboard
        </button>
      </header>

      <main className="flex-1 flex overflow-hidden">

        {/* Left: query panel */}
        <aside className="w-[320px] border-r border-slate-200 bg-white flex flex-col shadow-[4px_0_15px_rgba(0,0,0,0.02)] z-10 shrink-0">
          <QueryPanel
            form={form}
            loading={loading}
            resultCount={results ? results.length : null}
            onChange={setForm}
            onFetch={handleFetch}
          />
        </aside>

        {/* Right: timeline feed */}
        <section className="flex-1 flex flex-col overflow-hidden">

          {/* Sub-header: context summary */}
          <div className="px-6 py-3 border-b border-slate-200 bg-white shadow-sm shrink-0 z-10 flex items-center justify-between">
            {results !== null ? (
              <div className="text-sm text-slate-600">
                Timeline for{" "}
                <span className={`px-2 py-0.5 rounded border font-mono font-bold text-xs ${TYPE_CONFIG[form.objectName].badge}`}>
                  {form.objectName}
                </span>{" "}
                on{" "}
                <span className="font-mono text-xs font-bold text-slate-800">{form.targetID}</span>
                {form.step && (
                  <> · step <span className="font-mono text-xs font-bold text-slate-800">{form.step}</span></>
                )}
              </div>
            ) : (
              <div className="text-sm text-slate-400">
                Configure a query and click <strong>Fetch Historical Data</strong>.
              </div>
            )}
            {results && results.length > 0 && (
              <span className="text-[11px] font-mono text-slate-400">
                newest → oldest
              </span>
            )}
          </div>

          {/* Timeline body */}
          <div className="flex-1 overflow-y-auto px-20 py-8 relative">

            {/* Error */}
            {error && (
              <div className="mb-6 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-700 font-mono">
                ⚠ {error}
              </div>
            )}

            {/* Empty state */}
            {!loading && !error && results === null && (
              <div className="flex flex-col items-center justify-center py-24 text-slate-300">
                <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24"
                     fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"
                     className="mb-4">
                  <path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>
                </svg>
                <p className="text-sm font-mono">Select filters and fetch to begin.</p>
              </div>
            )}

            {/* No results */}
            {!loading && results !== null && results.length === 0 && (
              <div className="text-center py-16 text-slate-400 font-mono text-sm">
                No snapshots found for the given query.
              </div>
            )}

            {/* Timeline cards */}
            {results && results.length > 0 && (
              <div>
                {results.map((doc, i) => (
                  <TimelineCard
                    key={i}
                    doc={doc}
                    objectName={form.objectName}
                    isLast={i === results.length - 1}
                  />
                ))}
                <div className="text-center mt-4 mb-2">
                  <span className="text-[11px] font-mono text-slate-300">
                    — end of results ({results.length} records) —
                  </span>
                </div>
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
