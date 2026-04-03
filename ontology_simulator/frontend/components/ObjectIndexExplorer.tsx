"use client";
/**
 * ObjectIndexExplorer — Mode C (Object Index View)
 *
 * Exports three named panel components that Dashboard places in its
 * LEFT / CENTER / RIGHT columns via ObjIndexProvider:
 *   ObjIndexLeftPanel   — type switcher + load controls
 *   ObjIndexCenterPanel — data grid (newest-first)
 *   ObjIndexRightPanel  — JSON snapshot inspector
 */
import { useState, useCallback, createContext, useContext } from "react";

function getApiBase() {
  if (typeof window === "undefined") return "/simulator-api";
  const isLocal =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";
  return `${window.location.origin}/simulator-api`;
}

export const OBJ_TYPES = ["APC", "RECIPE", "DC", "SPC"] as const;
export type ObjType = (typeof OBJ_TYPES)[number];

export interface IndexRecord {
  index_id: string;
  object_id: string | null;
  event_time: string | null;
  lot_id: string | null;
  tool_id: string | null;
  step: string | null;
  payload: Record<string, unknown>;
}

export interface IndexResponse {
  object_type: ObjType;
  count: number;
  records: IndexRecord[];
}

export interface ObjIndexState {
  objType: ObjType;
  limit: number;
  loading: boolean;
  result: IndexResponse | null;
  error: string | null;
  selected: IndexRecord | null;
  setObjType: (t: ObjType) => void;
  setLimit: (n: number) => void;
  setSelected: (r: IndexRecord | null) => void;
  fetchIndex: (type: ObjType, lim: number) => Promise<void>;
}

const TYPE_COLOR: Record<ObjType, { badge: string; row: string; rowSelected: string }> = {
  APC:    { badge: "bg-sky-100 text-sky-700",       row: "hover:bg-sky-50",     rowSelected: "bg-sky-50 border-sky-200"     },
  RECIPE: { badge: "bg-green-100 text-green-700",   row: "hover:bg-green-50",   rowSelected: "bg-green-50 border-green-200" },
  DC:     { badge: "bg-indigo-100 text-indigo-700", row: "hover:bg-indigo-50",  rowSelected: "bg-indigo-50 border-indigo-200"},
  SPC:    { badge: "bg-amber-100 text-amber-700",   row: "hover:bg-amber-50",   rowSelected: "bg-amber-50 border-amber-200" },
};

// ── Context ─────────────────────────────────────────────────────
const ObjIndexCtx = createContext<ObjIndexState | null>(null);

function useObjIndexCtx(): ObjIndexState {
  const ctx = useContext(ObjIndexCtx);
  if (!ctx) throw new Error("useObjIndexCtx must be inside ObjIndexProvider");
  return ctx;
}

// ── Hook (instantiate in Dashboard) ────────────────────────────
export function useObjIndex(): ObjIndexState {
  const [objType,  setObjTypeRaw] = useState<ObjType>("APC");
  const [limit,    setLimitRaw]   = useState(50);
  const [loading,  setLoading]    = useState(false);
  const [result,   setResult]     = useState<IndexResponse | null>(null);
  const [error,    setError]      = useState<string | null>(null);
  const [selected, setSelected]   = useState<IndexRecord | null>(null);

  const fetchIndex = useCallback(async (type: ObjType, lim: number) => {
    setLoading(true);
    setError(null);
    setSelected(null);
    try {
      const res = await fetch(
        `${getApiBase()}/api/v2/ontology/indices/${type}?limit=${lim}`
      );
      if (!res.ok) {
        const msg = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(msg.detail ?? res.statusText);
      }
      const data: IndexResponse = await res.json();
      setResult(data);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  const setObjType = useCallback((t: ObjType) => {
    setObjTypeRaw(t);
    setResult(null);
    setSelected(null);
    setError(null);
  }, []);

  const setLimit = useCallback((n: number) => setLimitRaw(n), []);

  return {
    objType, limit, loading, result, error, selected,
    setObjType, setLimit, setSelected, fetchIndex,
  };
}

// ── Provider ─────────────────────────────────────────────────────
export function ObjIndexProvider({
  state,
  children,
}: {
  state: ObjIndexState;
  children: React.ReactNode;
}) {
  return <ObjIndexCtx.Provider value={state}>{children}</ObjIndexCtx.Provider>;
}

// ── LEFT panel: type switcher + load controls ───────────────────
export function ObjIndexLeftPanel() {
  const { objType, setObjType, limit, setLimit, loading, result, fetchIndex } =
    useObjIndexCtx();

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="shrink-0 px-3 py-2.5 border-b border-slate-200 bg-white">
        <p className="text-[9px] font-bold text-slate-400 uppercase tracking-widest mb-2">
          Object Type
        </p>
        <div className="flex flex-col gap-1">
          {OBJ_TYPES.map(t => (
            <button
              key={t}
              onClick={() => setObjType(t)}
              className={[
                "w-full text-left text-[11px] font-bold px-3 py-2 rounded-md border transition-colors",
                t === objType
                  ? `${TYPE_COLOR[t].badge} border-transparent shadow-sm`
                  : "bg-white text-slate-400 border-slate-200 hover:text-slate-600",
              ].join(" ")}
            >
              {t}
              {result && result.object_type === t && (
                <span className="ml-2 text-[9px] font-normal opacity-70">
                  ({result.count})
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      <div className="shrink-0 px-3 py-2.5 border-b border-slate-200 bg-white">
        <p className="text-[9px] font-bold text-slate-400 uppercase tracking-widest mb-2">
          Limit
        </p>
        <select
          value={limit}
          onChange={e => setLimit(Number(e.target.value))}
          className="w-full text-[11px] border border-slate-200 rounded px-2 py-1.5 outline-none bg-white"
        >
          {[10, 25, 50, 100, 200].map(n => (
            <option key={n} value={n}>{n} records</option>
          ))}
        </select>
      </div>

      <div className="shrink-0 px-3 py-2.5">
        <button
          onClick={() => fetchIndex(objType, limit)}
          disabled={loading}
          className="w-full text-[12px] font-bold py-2 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {loading ? "Loading…" : "LOAD"}
        </button>
      </div>

      <div className="flex-1 px-3 py-2">
        <p className="text-[10px] text-slate-400 leading-relaxed">
          Fetch the latest snapshots by type.
          <br />
          Click a row in the grid to inspect its JSON.
        </p>
      </div>
    </div>
  );
}

// ── CENTER panel: data grid ─────────────────────────────────────
export function ObjIndexCenterPanel() {
  const { objType, loading, result, error, selected, setSelected } =
    useObjIndexCtx();
  const colors = TYPE_COLOR[objType];

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-[12px] text-slate-400 animate-pulse">Loading…</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="h-full flex items-center justify-center px-6">
        <p className="text-[12px] text-red-500">{error}</p>
      </div>
    );
  }
  if (!result) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-[12px] text-slate-400">Select a type and press LOAD</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="shrink-0 flex items-center justify-between px-4 py-2.5 border-b border-slate-200 bg-white">
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${colors.badge}`}>
          {result.object_type}
        </span>
        <span className="text-[10px] text-slate-400">
          {result.count} records · newest first
        </span>
      </div>

      <div className="shrink-0 grid grid-cols-[1.2fr_1fr_1fr_1fr] px-4 py-1.5 border-b border-slate-100 bg-slate-50">
        {["eventTime", "lotID", "toolID", "step"].map(h => (
          <span key={h} className="text-[9px] font-bold text-slate-400 uppercase tracking-wider">
            {h}
          </span>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {result.records.map(rec => {
          const isSelected = selected?.index_id === rec.index_id;
          const ts = rec.event_time
            ? new Date(rec.event_time).toLocaleTimeString()
            : "—";
          return (
            <div
              key={rec.index_id}
              onClick={() => setSelected(isSelected ? null : rec)}
              className={[
                "grid grid-cols-[1.2fr_1fr_1fr_1fr] px-4 py-1.5 cursor-pointer border-b border-slate-100 transition-colors",
                isSelected ? colors.rowSelected + " border" : colors.row,
              ].join(" ")}
            >
              <span className="text-[10px] font-mono text-slate-600 truncate">{ts}</span>
              <span className="text-[10px] font-mono text-slate-600 truncate">{rec.lot_id ?? "—"}</span>
              <span className="text-[10px] font-mono text-slate-500 truncate">{rec.tool_id ?? "—"}</span>
              <span className="text-[10px] font-mono text-slate-500 truncate">{rec.step ?? "—"}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── RIGHT panel: JSON inspector ─────────────────────────────────
export function ObjIndexRightPanel() {
  const { selected, objType } = useObjIndexCtx();
  const colors = TYPE_COLOR[objType];

  return (
    <div className="h-full flex flex-col overflow-hidden bg-slate-900">
      <div className="shrink-0 px-3 py-2.5 border-b border-slate-700 flex items-center justify-between">
        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">
          JSON Inspector
        </span>
        {selected && (
          <span className={`text-[9px] font-bold px-2 py-0.5 rounded ${colors.badge}`}>
            {selected.object_id ?? selected.index_id.slice(-8)}
          </span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        {selected ? (
          <pre className="text-[10px] text-green-300 font-mono whitespace-pre-wrap leading-relaxed">
            {JSON.stringify(selected.payload, null, 2)}
          </pre>
        ) : (
          <p className="text-[11px] text-slate-500">
            Click a row to inspect its JSON snapshot
          </p>
        )}
      </div>
    </div>
  );
}

// ── Standalone default export ───────────────────────────────────
export default function ObjectIndexExplorer() {
  const state = useObjIndex();
  return (
    <ObjIndexProvider state={state}>
      <div className="h-full flex flex-col overflow-hidden">
        <div className="shrink-0 px-4 py-2.5 border-b border-slate-200 bg-white flex items-center gap-3">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
            Object Type
          </span>
          <div className="flex gap-1">
            {OBJ_TYPES.map(t => (
              <button key={t} onClick={() => state.setObjType(t)}
                className={[
                  "text-[10px] font-bold px-2.5 py-1 rounded-md border transition-colors",
                  t === state.objType
                    ? `${TYPE_COLOR[t].badge} border-transparent shadow-sm`
                    : "bg-white text-slate-400 border-slate-200 hover:text-slate-600",
                ].join(" ")}
              >{t}</button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <select value={state.limit} onChange={e => state.setLimit(Number(e.target.value))}
              className="text-[11px] border border-slate-200 rounded px-1.5 py-0.5 outline-none">
              {[10, 25, 50, 100].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
            <button onClick={() => state.fetchIndex(state.objType, state.limit)}
              disabled={state.loading}
              className="text-[11px] font-bold px-3 py-1 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">
              {state.loading ? "…" : "LOAD"}
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-hidden flex">
          <div className="flex-1 overflow-hidden border-r border-slate-200"><ObjIndexCenterPanel /></div>
          <div className="w-[360px] shrink-0"><ObjIndexRightPanel /></div>
        </div>
      </div>
    </ObjIndexProvider>
  );
}
