"use client";
import { useState, useCallback, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft, Play, RotateCcw, Copy, Check,
  Activity, Zap, GitBranch, Search, Database,
  ChevronRight, AlertTriangle, CheckCircle, Clock,
} from "lucide-react";

function getApiBase() {
  if (typeof window === "undefined") return "http://localhost:8001";
  const h = window.location.hostname;
  return h === "localhost" || h === "127.0.0.1"
    ? `http://${h}:8001`
    : `${window.location.origin}/simulator-api`;
}

// ── Pillar definitions ───────────────────────────────────────────────────────
const PILLARS = [
  { id: "P1", label: "Context",  color: "blue",   desc: "Point-in-Time snapshot",     path: (id="LOT-0001", step="STEP_003") => `/api/v2/ontology/context?lot_id=${id}&step=${step}` },
  { id: "P2", label: "Tool",     color: "cyan",   desc: "Tool-Centric trajectory",     path: (id="EQP-01") => `/api/v2/ontology/trajectory/tool/${id}?include_state_events=true` },
  { id: "P3", label: "Lot",      color: "green",  desc: "Lot-Centric trajectory",      path: (id="LOT-0001") => `/api/v2/ontology/trajectory/lot/${id}` },
  { id: "P4", label: "Object",   color: "purple", desc: "Object-Centric history",      path: (id="APC-003") => `/api/v2/ontology/history/APC/${id}` },
] as const;

type PillarId = "P1" | "P2" | "P3" | "P4";
type SkillId  = "APC_AUDIT" | "CHAMBER_MATCH" | "LOT_TRACE" | "OOC_RCA" | "TOOL_STATE" | PillarId;

const PILLAR_COLORS: Record<string, { bg: string; text: string; border: string; dot: string }> = {
  blue:   { bg: "bg-blue-950/60",   text: "text-blue-300",   border: "border-blue-800",   dot: "bg-blue-400"   },
  cyan:   { bg: "bg-cyan-950/60",   text: "text-cyan-300",   border: "border-cyan-800",   dot: "bg-cyan-400"   },
  green:  { bg: "bg-green-950/60",  text: "text-green-300",  border: "border-green-800",  dot: "bg-green-400"  },
  purple: { bg: "bg-purple-950/60", text: "text-purple-300", border: "border-purple-800", dot: "bg-purple-400" },
};

// ── Helper hooks / utils ─────────────────────────────────────────────────────
function useFetch() {
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const [data,     setData]     = useState<any>(null);
  const [elapsed,  setElapsed]  = useState<number | null>(null);
  const [url,      setUrl]      = useState<string>("");

  const run = useCallback(async (path: string) => {
    const full = getApiBase() + path;
    setUrl(full); setLoading(true); setError(null); setData(null);
    const t0 = performance.now();
    try {
      const res = await fetch(full);
      const json = await res.json();
      setElapsed(Math.round(performance.now() - t0));
      if (!res.ok) { setError(`HTTP ${res.status}: ${json?.detail ?? res.statusText}`); return null; }
      setData(json);
      return json;
    } catch (e: any) {
      setError(e.message ?? "Network error");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  return { loading, error, data, elapsed, url, run };
}

// ── Enumerate hook (lot_ids / tool_ids / steps from backend) ─────────────────
function useEnumerate() {
  const [lots,  setLots]  = useState<string[]>([]);
  const [tools, setTools] = useState<string[]>([]);
  const [steps, setSteps] = useState<string[]>([]);
  useEffect(() => {
    const base = getApiBase();
    fetch(`${base}/api/v2/ontology/enumerate`)
      .then(r => r.json())
      .then(d => {
        if (d.lot_ids?.length)  setLots(d.lot_ids);
        if (d.tool_ids?.length) setTools(d.tool_ids);
        if (d.steps?.length)    setSteps(d.steps);
      })
      .catch(() => {/* silent — fallback to empty */});
  }, []);
  return { lots, tools, steps };
}

const SEL_CLS = "bg-slate-800 border border-slate-600 text-slate-200 text-[12px] font-mono rounded px-2 py-1.5 focus:outline-none cursor-pointer";

// ── Syntax-highlighted JSON ──────────────────────────────────────────────────
function JsonViewer({ data }: { data: any }) {
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(data, null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 2000);
    });
  };

  const highlighted = text
    .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
      (m) => {
        let cls = "text-cyan-300"; // number
        if (/^"/.test(m)) cls = /:$/.test(m) ? "text-blue-300 font-semibold" : "text-green-300";
        else if (/true|false/.test(m)) cls = "text-yellow-300";
        else if (/null/.test(m)) cls = "text-slate-500";
        return `<span class="${cls}">${m}</span>`;
      });

  return (
    <div className="relative h-full flex flex-col">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-700 shrink-0">
        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">JSON Response</span>
        <button onClick={handleCopy} className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-slate-200 transition-colors">
          {copied ? <><Check size={10} className="text-green-400" /> Copied</> : <><Copy size={10} /> Copy</>}
        </button>
      </div>
      <div className="flex-1 overflow-auto p-3">
        <pre className="text-[11px] font-mono leading-relaxed whitespace-pre-wrap break-all"
             dangerouslySetInnerHTML={{ __html: highlighted }} />
      </div>
    </div>
  );
}

// ── APC Model Audit ──────────────────────────────────────────────────────────
function ApcAuditPanel() {
  const [apcId, setApcId] = useState("APC-003");
  const { loading, error, data, elapsed, run } = useFetch();

  const handleRun = () => run(`/api/v2/ontology/history/APC/${apcId}`);

  // Agent logic: scan for 3 consecutive OOC with high offset variance
  const auditResult = (() => {
    if (!data?.history) return null;
    const pairs: { offset: number | null; status: string; eventTime: string }[] =
      data.history.map((r: any) => ({
        offset: r.parameters?.etch_time_offset ?? null,
        status: r.spc_status ?? "UNKNOWN",
        eventTime: r.event_time,
      }));
    const oocCount = pairs.filter(p => p.status === "OOC").length;
    const total = pairs.length;
    // Check for 3 consecutive OOC
    let oscillating = false;
    for (let i = 0; i <= pairs.length - 3; i++) {
      const window = pairs.slice(i, i + 3);
      if (window.every(p => p.status === "OOC")) {
        const validOffsets = window.map(p => p.offset).filter(o => o !== null) as number[];
        if (validOffsets.length >= 2) {
          const mean = validOffsets.reduce((a, b) => a + b, 0) / validOffsets.length;
          const variance = validOffsets.reduce((a, b) => a + (b - mean) ** 2, 0) / validOffsets.length;
          if (variance > 0.25) { oscillating = true; break; }
        } else {
          oscillating = true; break;
        }
      }
    }
    return { pairs, oocCount, total, oscillating, oocRate: total ? (oocCount / total * 100).toFixed(1) : "0" };
  })();

  const barMaxH = 80;
  const hasOffsets = auditResult?.pairs.some(p => p.offset !== null);

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto p-1">
      {/* Query row */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-slate-400 font-semibold uppercase tracking-widest">APC Object ID</label>
          <select
            value={apcId}
            onChange={e => setApcId(e.target.value)}
            className="bg-slate-800 border border-slate-600 text-slate-200 text-[12px] font-mono rounded px-2 py-1.5 focus:outline-none focus:border-purple-500"
          >
            {Array.from({ length: 20 }, (_, i) => `APC-${String(i+1).padStart(3,"0")}`).map(id => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </div>
        <button
          onClick={handleRun}
          disabled={loading}
          className="mt-5 flex items-center gap-1.5 px-4 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:bg-slate-700 text-white text-[11px] font-bold rounded transition-colors"
        >
          {loading ? <RotateCcw size={12} className="animate-spin" /> : <Play size={12} />}
          {loading ? "Running…" : "Run Audit"}
        </button>
        {elapsed != null && (
          <span className="mt-5 text-[10px] text-slate-500 flex items-center gap-1">
            <Clock size={9} /> {elapsed}ms · {auditResult?.total ?? 0} records
          </span>
        )}
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700 rounded px-3 py-2 text-[11px] text-red-300">
          {error}
        </div>
      )}

      {auditResult && (
        <>
          {/* Agent decision banner */}
          {auditResult.oscillating ? (
            <div className="flex items-start gap-3 bg-red-900/40 border border-red-600 rounded-lg px-4 py-3">
              <AlertTriangle size={18} className="text-red-400 shrink-0 mt-0.5" />
              <div>
                <p className="text-[12px] font-bold text-red-300">[Agent 決策] 警告：{apcId} 模型發生震盪發散，建議立即停止補償。</p>
                <p className="text-[10px] text-red-400 mt-0.5">偵測到連續 3 次 OOC 且補償值變動劇烈。建議 Freeze APC 並通知 APC 工程師。</p>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-3 bg-green-900/30 border border-green-700 rounded-lg px-4 py-2.5">
              <CheckCircle size={16} className="text-green-400 shrink-0" />
              <p className="text-[12px] text-green-300 font-semibold">[Agent 決策] {apcId} 模型運作正常，未偵測到震盪發散。</p>
            </div>
          )}

          {/* Stats row */}
          <div className="flex gap-3 flex-wrap">
            {[
              { label: "總紀錄數", value: auditResult.total, color: "text-slate-300" },
              { label: "OOC 次數", value: auditResult.oocCount, color: "text-red-300" },
              { label: "OOC 率",   value: `${auditResult.oocRate}%`, color: auditResult.oscillating ? "text-red-300 font-bold" : "text-slate-300" },
            ].map(s => (
              <div key={s.label} className="bg-slate-800/60 border border-slate-700 rounded-lg px-4 py-2.5 min-w-[100px]">
                <p className="text-[10px] text-slate-500 uppercase tracking-wide">{s.label}</p>
                <p className={`text-[18px] font-bold mt-0.5 ${s.color}`}>{s.value}</p>
              </div>
            ))}
          </div>

          {/* Bar chart */}
          <div className="bg-slate-900/80 border border-slate-700 rounded-lg p-4">
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-3">
              {hasOffsets ? "etch_time_offset × spc_status" : "spc_status 分佈（etch_time_offset 不存在）"}
            </p>
            {hasOffsets ? (
              <div className="flex items-end gap-0.5 h-24 overflow-x-auto pb-1">
                {auditResult.pairs.map((p, i) => {
                  const h = p.offset !== null ? Math.max(4, Math.min(barMaxH, Math.abs(p.offset) * 30)) : 8;
                  const color = p.status === "OOC" ? "bg-red-500" : p.status === "IN_CTRL" ? "bg-green-500" : "bg-slate-600";
                  return (
                    <div key={i} title={`[${i}] offset=${p.offset?.toFixed(3) ?? "N/A"} spc=${p.status}`}
                         className={`shrink-0 w-3 rounded-t transition-colors ${color}`} style={{ height: `${h}px` }} />
                  );
                })}
              </div>
            ) : (
              <div className="flex gap-2 flex-wrap">
                {(["OOC", "IN_CTRL", "UNKNOWN"] as const).map(s => {
                  const cnt = auditResult.pairs.filter(p => p.status === s).length;
                  if (cnt === 0) return null;
                  const color = s === "OOC" ? "bg-red-500" : s === "IN_CTRL" ? "bg-green-500" : "bg-slate-600";
                  return (
                    <div key={s} className="flex items-center gap-2">
                      <div className={`w-3 h-3 rounded-sm ${color}`} />
                      <span className="text-[11px] text-slate-300">{s}: <strong>{cnt}</strong></span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}

      {!data && !loading && !error && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-slate-500">
            <Database size={32} className="mx-auto mb-3 opacity-30" />
            <p className="text-[12px]">選擇 APC ID 後點擊 Run Audit</p>
            <p className="text-[10px] mt-1 text-slate-600">呼叫 Pillar 4: GET /history/APC/{"{id}"}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Chamber Matching ─────────────────────────────────────────────────────────
function ChamberMatchPanel() {
  const [toolA, setToolA] = useState("EQP-01");
  const [toolB, setToolB] = useState("EQP-02");
  const fetchA = useFetch();
  const fetchB = useFetch();

  const handleCompare = async () => {
    await Promise.all([
      fetchA.run(`/api/v2/ontology/trajectory/tool/${toolA}`),
      fetchB.run(`/api/v2/ontology/trajectory/tool/${toolB}`),
    ]);
  };

  const loading = fetchA.loading || fetchB.loading;

  const stats = (data: any, id: string) => {
    if (!data?.batches) return null;
    const b = data.batches as any[];
    const ooc = b.filter(x => x.spc_status === "OOC").length;
    const recipes = [...new Set(b.map(x => x.recipe_id).filter(Boolean))];
    return { id, total: b.length, ooc, oocRate: b.length ? (ooc/b.length*100).toFixed(1) : "0", recipes };
  };

  const sA = stats(fetchA.data, toolA);
  const sB = stats(fetchB.data, toolB);

  const ToolSelect = ({ value, onChange, label }: { value: string; onChange: (v:string)=>void; label: string }) => (
    <div className="flex flex-col gap-0.5">
      <label className="text-[10px] text-slate-400 font-semibold uppercase tracking-widest">{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)}
        className="bg-slate-800 border border-slate-600 text-slate-200 text-[12px] font-mono rounded px-2 py-1.5 focus:outline-none focus:border-cyan-500">
        {Array.from({ length: 10 }, (_, i) => `EQP-${String(i+1).padStart(2,"0")}`).map(id => (
          <option key={id} value={id}>{id}</option>
        ))}
      </select>
    </div>
  );

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto p-1">
      <div className="flex items-center gap-3 flex-wrap">
        <ToolSelect value={toolA} onChange={setToolA} label="Chamber A" />
        <div className="mt-5 text-slate-500 font-bold">VS</div>
        <ToolSelect value={toolB} onChange={setToolB} label="Chamber B" />
        <button onClick={handleCompare} disabled={loading}
          className="mt-5 flex items-center gap-1.5 px-4 py-1.5 bg-cyan-700 hover:bg-cyan-600 disabled:bg-slate-700 text-white text-[11px] font-bold rounded transition-colors">
          {loading ? <RotateCcw size={12} className="animate-spin" /> : <GitBranch size={12} />}
          {loading ? "Comparing…" : "Compare"}
        </button>
      </div>

      {(fetchA.error || fetchB.error) && (
        <div className="bg-red-900/30 border border-red-700 rounded px-3 py-2 text-[11px] text-red-300">
          {fetchA.error || fetchB.error}
        </div>
      )}

      {sA && sB && (
        <div className="grid grid-cols-2 gap-4">
          {[sA, sB].map((s, idx) => {
            const color = idx === 0 ? "border-cyan-700 bg-cyan-950/30" : "border-green-700 bg-green-950/30";
            const textColor = idx === 0 ? "text-cyan-300" : "text-green-300";
            const diff = Math.abs(parseFloat(sA.oocRate) - parseFloat(sB.oocRate));
            const isHighDiff = diff > 5;
            return (
              <div key={s.id} className={`border rounded-lg p-4 ${color}`}>
                <p className={`text-[13px] font-bold font-mono mb-3 ${textColor}`}>{s.id}</p>
                <div className="space-y-2">
                  {[
                    { l: "批次總數", v: s.total },
                    { l: "OOC 次數", v: s.ooc },
                    { l: "OOC 率", v: `${s.oocRate}%`, highlight: isHighDiff },
                    { l: "使用配方數", v: s.recipes.length },
                  ].map(r => (
                    <div key={r.l} className="flex justify-between items-center">
                      <span className="text-[10px] text-slate-400">{r.l}</span>
                      <span className={`text-[12px] font-semibold font-mono ${r.highlight ? "text-amber-300" : "text-slate-200"}`}>
                        {r.v}
                        {r.highlight && <AlertTriangle size={10} className="inline ml-1 text-amber-400" />}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {sA && sB && (
        <div className={`border rounded-lg px-4 py-3 ${
          Math.abs(parseFloat(sA.oocRate) - parseFloat(sB.oocRate)) > 5
            ? "border-amber-700 bg-amber-950/30"
            : "border-green-700 bg-green-950/30"
        }`}>
          <p className={`text-[11px] font-semibold ${
            Math.abs(parseFloat(sA.oocRate) - parseFloat(sB.oocRate)) > 5
              ? "text-amber-300" : "text-green-300"
          }`}>
            {Math.abs(parseFloat(sA.oocRate) - parseFloat(sB.oocRate)) > 5
              ? `[Agent 決策] ${toolA} vs ${toolB} OOC 率差異超過 5%，建議進行 Chamber Matching 校正`
              : `[Agent 決策] ${toolA} vs ${toolB} 兩台機台表現一致，無需 Chamber Matching`}
          </p>
        </div>
      )}

      {!sA && !sB && !loading && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-slate-500">
            <GitBranch size={32} className="mx-auto mb-3 opacity-30" />
            <p className="text-[12px]">選擇兩台機台後點擊 Compare</p>
            <p className="text-[10px] mt-1 text-slate-600">呼叫 Pillar 2 × 2: GET /trajectory/tool/{"{id}"}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Lot Trace ────────────────────────────────────────────────────────────────
function LotTracePanel() {
  const [lotId, setLotId] = useState("LOT-0001");
  const { loading, error, data, elapsed, run } = useFetch();
  const { lots } = useEnumerate();

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto p-1">
      <div className="flex items-center gap-3">
        <div className="flex flex-col gap-0.5 flex-1 max-w-[200px]">
          <label className="text-[10px] text-slate-400 font-semibold uppercase tracking-widest">Lot ID</label>
          <select value={lotId} onChange={e => setLotId(e.target.value)} className={`${SEL_CLS} focus:border-green-500`}>
            {lots.map(l => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>
        <button onClick={() => run(`/api/v2/ontology/trajectory/lot/${lotId}`)} disabled={loading}
          className="mt-5 flex items-center gap-1.5 px-4 py-1.5 bg-green-700 hover:bg-green-600 disabled:bg-slate-700 text-white text-[11px] font-bold rounded transition-colors">
          {loading ? <RotateCcw size={12} className="animate-spin" /> : <Search size={12} />}
          {loading ? "Tracing…" : "Trace"}
        </button>
        {elapsed != null && <span className="mt-5 text-[10px] text-slate-500 flex items-center gap-1"><Clock size={9}/> {elapsed}ms · {data?.total_steps ?? 0} steps</span>}
      </div>

      {error && <div className="bg-red-900/30 border border-red-700 rounded px-3 py-2 text-[11px] text-red-300">{error}</div>}

      {data?.steps && (
        <div className="space-y-0 relative border-l-2 border-slate-700 ml-4 pl-4">
          {(data.steps as any[]).map((step, i) => {
            const isOOC = step.spc_status === "OOC";
            return (
              <div key={i} className="relative pb-3">
                <div className={`absolute -left-[22px] top-1.5 w-3 h-3 rounded-full border-2 ${
                  isOOC ? "bg-red-900 border-red-500" : "bg-slate-800 border-slate-500"
                }`} />
                <div className={`rounded-lg border px-3 py-2 text-[11px] ${
                  isOOC ? "border-red-800 bg-red-950/30" : "border-slate-700 bg-slate-800/40"
                }`}>
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-slate-300">{step.step}</span>
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                      isOOC ? "bg-red-900/60 text-red-300" : "bg-green-900/40 text-green-400"
                    }`}>{step.spc_status ?? "–"}</span>
                  </div>
                  <div className="flex gap-3 mt-1 text-[10px] text-slate-400">
                    <span>🔧 {step.tool_id}</span>
                    <span>📋 {step.recipe_id ?? "–"}</span>
                    <span>🕐 {step.event_time?.slice(11,19)}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {!data && !loading && !error && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-slate-500">
            <Activity size={32} className="mx-auto mb-3 opacity-30" />
            <p className="text-[12px]">輸入 Lot ID 後點擊 Trace</p>
            <p className="text-[10px] mt-1 text-slate-600">呼叫 Pillar 3: GET /trajectory/lot/{"{id}"}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── OOC Root Cause (Pillar 1) ────────────────────────────────────────────────
function OOCRootCausePanel() {
  const [lotId, setLotId] = useState("LOT-0001");
  const [step,  setStep]  = useState("STEP_003");
  const { loading, error, data, elapsed, run } = useFetch();
  const { lots, steps: stepOpts } = useEnumerate();

  const SubCard = ({ title, obj, color }: { title: string; obj: any; color: string }) => (
    <div className={`border rounded-lg p-3 ${color}`}>
      <p className="text-[10px] font-bold uppercase tracking-widest mb-2 text-slate-400">{title}</p>
      {obj ? (
        <div className="space-y-1">
          {Object.entries(obj).slice(0, 6).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2">
              <span className="text-[10px] text-slate-500 truncate">{k}</span>
              <span className="text-[10px] font-mono text-slate-300 truncate max-w-[120px]" title={String(v)}>{String(v)}</span>
            </div>
          ))}
        </div>
      ) : <p className="text-[10px] text-slate-600">No data</p>}
    </div>
  );

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto p-1">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-slate-400 font-semibold uppercase tracking-widest">Lot ID</label>
          <select value={lotId} onChange={e => setLotId(e.target.value)} className={`${SEL_CLS} w-28 focus:border-blue-500`}>
            {lots.map(l => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-slate-400 font-semibold uppercase tracking-widest">Step</label>
          <select value={step} onChange={e => setStep(e.target.value)} className={`${SEL_CLS} focus:border-blue-500`}>
            {(stepOpts.length ? stepOpts : Array.from({ length: 10 }, (_, i) => `STEP_${String(i+1).padStart(3,"0")}`)).map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <button onClick={() => run(`/api/v2/ontology/context?lot_id=${lotId}&step=${step}`)} disabled={loading}
          className="mt-5 flex items-center gap-1.5 px-4 py-1.5 bg-blue-700 hover:bg-blue-600 disabled:bg-slate-700 text-white text-[11px] font-bold rounded transition-colors">
          {loading ? <RotateCcw size={12} className="animate-spin" /> : <Zap size={12} />}
          {loading ? "Loading…" : "Get Context"}
        </button>
        {elapsed != null && <span className="mt-5 text-[10px] text-slate-500"><Clock size={9} className="inline mr-1"/>{elapsed}ms</span>}
      </div>

      {error && <div className="bg-red-900/30 border border-red-700 rounded px-3 py-2 text-[11px] text-red-300">{error}</div>}

      {data && (
        <>
          <div className={`flex items-center gap-3 border rounded-lg px-4 py-2.5 ${
            data.root?.spc_status === "OOC"
              ? "border-red-700 bg-red-950/30"
              : "border-green-700 bg-green-950/30"
          }`}>
            <div className={`w-2 h-2 rounded-full ${data.root?.spc_status === "OOC" ? "bg-red-400" : "bg-green-400"}`} />
            <span className="text-[11px] font-bold text-slate-200">{lotId} / {step}</span>
            <span className={`ml-auto text-[11px] font-bold ${data.root?.spc_status === "OOC" ? "text-red-300" : "text-green-300"}`}>
              SPC: {data.root?.spc_status ?? "–"}
            </span>
          </div>
          <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
            <SubCard title="TOOL"   obj={data.tool}   color="border-blue-900 bg-blue-950/20" />
            <SubCard title="RECIPE" obj={data.recipe?.parameters ?? data.recipe} color="border-cyan-900 bg-cyan-950/20" />
            <SubCard title="APC"    obj={data.apc?.parameters ?? data.apc}    color="border-purple-900 bg-purple-950/20" />
            <SubCard title="DC"     obj={data.dc?.parameters ?? data.dc}     color="border-orange-900 bg-orange-950/20" />
            <SubCard title="SPC"    obj={data.spc?.parameters ?? data.spc}   color="border-red-900 bg-red-950/20" />
          </div>
        </>
      )}

      {!data && !loading && !error && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-slate-500">
            <Zap size={32} className="mx-auto mb-3 opacity-30" />
            <p className="text-[12px]">輸入 Lot + Step 後點擊 Get Context</p>
            <p className="text-[10px] mt-1 text-slate-600">呼叫 Pillar 1: GET /context?lot_id={"{id}"}&step={"{step}"}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Tool State Machine Panel (v2.4) ──────────────────────────────────────────
function ToolStatePanel() {
  const [toolId, setToolId] = useState("EQP-01");
  const { loading, error, data, elapsed, run } = useFetch();

  const EVENT_STYLE: Record<string, { bg: string; text: string; icon: string }> = {
    PM_START: { bg: "border-amber-700 bg-amber-950/30", text: "text-amber-300", icon: "🔧" },
    PM_DONE:  { bg: "border-green-700 bg-green-950/30", text: "text-green-300",  icon: "✅" },
    ALARM:    { bg: "border-red-700 bg-red-950/30",     text: "text-red-300",    icon: "🚨" },
    default:  { bg: "border-slate-700 bg-slate-800/40", text: "text-slate-400",  icon: "📋" },
  };

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto p-1">
      <div className="flex items-center gap-2 p-2 bg-amber-950/30 border border-amber-800/50 rounded-lg">
        <span className="text-amber-400 text-[11px]">⚡</span>
        <span className="text-[10px] text-amber-300 font-semibold">v2.4 Feature — State Machine Events (PM_START / PM_DONE / ALARM)</span>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-slate-400 font-semibold uppercase tracking-widest">Tool ID</label>
          <select value={toolId} onChange={e => setToolId(e.target.value)}
            className="bg-slate-800 border border-slate-600 text-slate-200 text-[12px] font-mono rounded px-2 py-1.5 focus:outline-none focus:border-cyan-500">
            {Array.from({ length: 10 }, (_, i) => `EQP-${String(i+1).padStart(2,"0")}`).map(id => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </div>
        <button onClick={() => run(`/api/v2/ontology/trajectory/tool/${toolId}?include_state_events=true`)} disabled={loading}
          className="mt-5 flex items-center gap-1.5 px-4 py-1.5 bg-cyan-700 hover:bg-cyan-600 disabled:bg-slate-700 text-white text-[11px] font-bold rounded transition-colors">
          {loading ? <RotateCcw size={12} className="animate-spin" /> : <Activity size={12} />}
          {loading ? "Loading…" : "Load State Timeline"}
        </button>
        {elapsed != null && <span className="mt-5 text-[10px] text-slate-500"><Clock size={9} className="inline mr-1"/>{elapsed}ms</span>}
      </div>

      {error && <div className="bg-red-900/30 border border-red-700 rounded px-3 py-2 text-[11px] text-red-300">{error}</div>}

      {data && (
        <>
          <div className="flex gap-3 flex-wrap">
            {[
              { l: "批次總數", v: data.total_batches ?? 0, c: "text-cyan-300" },
              { l: "PM 事件", v: (data.state_events ?? []).filter((e:any) => e.event_type?.includes("PM")).length, c: "text-amber-300" },
              { l: "ALARM 事件", v: (data.state_events ?? []).filter((e:any) => e.event_type === "ALARM").length, c: "text-red-300" },
            ].map(s => (
              <div key={s.l} className="bg-slate-800/60 border border-slate-700 rounded-lg px-4 py-2.5 min-w-[100px]">
                <p className="text-[10px] text-slate-500 uppercase tracking-wide">{s.l}</p>
                <p className={`text-[18px] font-bold mt-0.5 ${s.c}`}>{s.v}</p>
              </div>
            ))}
          </div>

          {(data.state_events ?? []).length === 0 ? (
            <div className="border border-dashed border-slate-700 rounded-lg p-6 text-center">
              <p className="text-[11px] text-slate-500">尚無狀態機事件。模擬器每 8-12 批次會自動觸發 PM 事件。</p>
              <p className="text-[10px] text-slate-600 mt-1">請等待 Simulator 執行一段時間後再查詢。</p>
            </div>
          ) : (
            <div className="space-y-1.5 border-l-2 border-slate-700 ml-4 pl-4">
              {(data.state_events as any[]).map((evt, i) => {
                const style = EVENT_STYLE[evt.event_type] ?? EVENT_STYLE.default;
                return (
                  <div key={i} className={`relative rounded-lg border px-3 py-2 text-[11px] ${style.bg}`}>
                    <div className="absolute -left-[22px] top-2 w-3 h-3 rounded-full bg-slate-800 border-2 border-slate-600" />
                    <div className="flex items-center justify-between">
                      <span className={`font-bold font-mono ${style.text}`}>{style.icon} {evt.event_type}</span>
                      <span className="text-[10px] text-slate-500">{evt.event_time?.slice(11,19)}</span>
                    </div>
                    {evt.metadata && (
                      <div className="mt-1 flex gap-3 text-[10px] text-slate-400 flex-wrap">
                        {Object.entries(evt.metadata).map(([k, v]) => (
                          <span key={k}>{k}={String(v)}</span>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

      {!data && !loading && !error && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-slate-500">
            <Activity size={32} className="mx-auto mb-3 opacity-30" />
            <p className="text-[12px]">選擇機台後點擊 Load State Timeline</p>
            <p className="text-[10px] mt-1 text-slate-600">呼叫 Pillar 2: GET /trajectory/tool/{"{id}"}?include_state_events=true</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Object History Panel (P4) — type+id selector + table view ────────────────
const HIST_TYPES = ["APC", "RECIPE", "DC", "SPC"] as const;
type HistType = typeof HIST_TYPES[number];

function ObjectHistoryPanel() {
  const [objType,     setObjType]     = useState<HistType>("APC");
  const [objId,       setObjId]       = useState("");
  const [objList,     setObjList]     = useState<string[]>([]);
  const [loadingIds,  setLoadingIds]  = useState(false);
  const { loading, error, data, elapsed, run } = useFetch();

  // Fetch unique object IDs whenever type changes
  useEffect(() => {
    setObjId(""); setObjList([]); setLoadingIds(true);
    fetch(`${getApiBase()}/api/v2/ontology/indices/${objType}`)
      .then(r => r.json())
      .then(d => {
        const ids = [...new Set(
          (d.records ?? []).map((r: any) => r.object_id).filter(Boolean)
        )].sort() as string[];
        setObjList(ids);
        if (ids.length) setObjId(ids[0]);
      })
      .catch(() => {})
      .finally(() => setLoadingIds(false));
  }, [objType]);

  const history = (data?.history ?? []) as any[];

  // Auto-detect parameter columns from first record that has them
  const paramKeys = (() => {
    const first = history.find(r => r.parameters && Object.keys(r.parameters).length > 0);
    return first ? Object.keys(first.parameters).slice(0, 5) : [];
  })();

  return (
    <div className="flex flex-col gap-3 h-full overflow-hidden">
      {/* URL preview */}
      <div className="shrink-0 border border-purple-800 bg-purple-950/60 rounded-lg px-4 py-2.5">
        <p className="text-[11px] font-bold font-mono text-purple-300">P4 — Object-Centric history</p>
        <p className="text-[10px] text-slate-400 mt-0.5 font-mono">
          {getApiBase()}/api/v2/ontology/history/{objType}/{objId || "…"}
        </p>
      </div>

      {/* Controls */}
      <div className="shrink-0 flex items-end gap-3 flex-wrap">
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-slate-400 font-semibold uppercase tracking-widest">Object Type</label>
          <select value={objType} onChange={e => setObjType(e.target.value as HistType)}
            className="bg-slate-800 border border-slate-600 text-slate-200 text-[12px] font-mono rounded px-2 py-1.5 focus:outline-none focus:border-purple-500">
            {HIST_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>

        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-slate-400 font-semibold uppercase tracking-widest">Object ID</label>
          <select value={objId} onChange={e => setObjId(e.target.value)}
            disabled={loadingIds || objList.length === 0}
            className="bg-slate-800 border border-slate-600 text-slate-200 text-[12px] font-mono rounded px-2 py-1.5 focus:outline-none focus:border-purple-500 w-36 disabled:opacity-50">
            {loadingIds
              ? <option value="">Loading…</option>
              : objList.length === 0
              ? <option value="">No data</option>
              : objList.map(id => <option key={id} value={id}>{id}</option>)}
          </select>
        </div>

        <button
          onClick={() => objId && run(`/api/v2/ontology/history/${objType}/${objId}`)}
          disabled={loading || !objId}
          className="flex items-center gap-1.5 px-4 py-1.5 bg-purple-700 hover:bg-purple-600 disabled:bg-slate-700 text-white text-[11px] font-bold rounded transition-colors"
        >
          {loading ? <RotateCcw size={12} className="animate-spin" /> : <Play size={12} />}
          {loading ? "Fetching…" : "Call P4"}
        </button>

        {elapsed != null && (
          <span className="text-[10px] text-slate-500 flex items-center gap-1">
            <Clock size={9} /> {elapsed}ms · {history.length} records
          </span>
        )}
      </div>

      {error && (
        <div className="shrink-0 bg-red-900/30 border border-red-700 rounded px-3 py-2 text-[11px] text-red-300">{error}</div>
      )}

      {/* Event list table */}
      {history.length > 0 && (
        <div className="flex-1 overflow-auto border border-slate-700 rounded-lg">
          <table className="w-full text-[11px] font-mono border-collapse">
            <thead className="sticky top-0 bg-slate-900 z-10">
              <tr>
                {(["#", "Time", "Lot", "Step", "SPC", ...paramKeys] as string[]).map(col => (
                  <th key={col} className="text-left px-2.5 py-2 text-[10px] font-bold text-slate-400 uppercase tracking-wider border-b border-slate-700 whitespace-nowrap">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.map((r, i) => {
                const isOOC   = r.spc_status === "OOC";
                const isCtrl  = r.spc_status === "IN_CTRL";
                return (
                  <tr key={i} className={`border-b border-slate-800/60 transition-colors ${
                    isOOC ? "bg-red-950/25 hover:bg-red-950/40" : "hover:bg-slate-800/40"
                  }`}>
                    <td className="px-2.5 py-1.5 text-slate-600">{i + 1}</td>
                    <td className="px-2.5 py-1.5 text-slate-400 whitespace-nowrap">{r.event_time?.slice(11, 19) ?? "–"}</td>
                    <td className="px-2.5 py-1.5 text-amber-300/80 whitespace-nowrap">{r.lot_id ?? "–"}</td>
                    <td className="px-2.5 py-1.5 text-slate-300 whitespace-nowrap">{r.step ?? "–"}</td>
                    <td className="px-2.5 py-1.5">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                        isOOC  ? "bg-red-900/60 text-red-300"   :
                        isCtrl ? "bg-green-900/40 text-green-400" :
                                  "bg-slate-700 text-slate-400"
                      }`}>{r.spc_status ?? "–"}</span>
                    </td>
                    {paramKeys.map(k => (
                      <td key={k} className="px-2.5 py-1.5 text-cyan-300/80 whitespace-nowrap">
                        {r.parameters?.[k] !== undefined
                          ? (typeof r.parameters[k] === "number"
                              ? r.parameters[k].toFixed(4)
                              : String(r.parameters[k]))
                          : "–"}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!data && !loading && !error && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-slate-500">
            <Database size={32} className="mx-auto mb-3 opacity-30" />
            <p className="text-[12px]">選擇 Object Type + ID 後點擊 Call P4</p>
            <p className="text-[10px] mt-1 text-slate-600">GET /history/{"{type}"}/{"{id}"}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Pillar Raw Panel (P1/P2/P3) ───────────────────────────────────────────────
function PillarRawPanel({ pillarId }: { pillarId: PillarId }) {
  const p = PILLARS.find(x => x.id === pillarId)!;
  const [param, setParam] = useState(pillarId === "P1" ? "LOT-0001" : pillarId === "P2" ? "EQP-01" : pillarId === "P3" ? "LOT-0001" : "APC-003");
  const [step,  setStep]  = useState("STEP_003");
  const { loading, error, data, elapsed, run } = useFetch();
  const { lots, tools, steps: stepOpts } = useEnumerate();

  const buildPath = () => {
    if (pillarId === "P1") return `/api/v2/ontology/context?lot_id=${param}&step=${step}`;
    if (pillarId === "P2") return `/api/v2/ontology/trajectory/tool/${param}?include_state_events=true`;
    if (pillarId === "P3") return `/api/v2/ontology/trajectory/lot/${param}`;
    return `/api/v2/ontology/history/APC/${param}`;
  };

  const clr = PILLAR_COLORS[p.color];

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto p-1">
      <div className={`border rounded-lg px-4 py-3 ${clr.border} ${clr.bg}`}>
        <p className={`text-[11px] font-bold font-mono ${clr.text}`}>{p.id} — {p.desc}</p>
        <p className="text-[10px] text-slate-400 mt-0.5 font-mono">{getApiBase()}{buildPath()}</p>
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] text-slate-400 font-semibold uppercase tracking-widest">
            {pillarId === "P2" ? "Tool ID" : pillarId === "P1" || pillarId === "P3" ? "Lot ID" : "Object ID"}
          </label>
          {pillarId === "P2" ? (
            <select value={param} onChange={e => setParam(e.target.value)} className={`${SEL_CLS} w-28`}>
              {tools.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          ) : pillarId === "P4" ? (
            <input value={param} onChange={e => setParam(e.target.value)}
              className={`bg-slate-800 border border-slate-600 text-slate-200 text-[12px] font-mono rounded px-2 py-1.5 w-32 focus:outline-none`} />
          ) : (
            <select value={param} onChange={e => setParam(e.target.value)} className={`${SEL_CLS} w-28`}>
              {lots.map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          )}
        </div>
        {pillarId === "P1" && (
          <div className="flex flex-col gap-0.5">
            <label className="text-[10px] text-slate-400 font-semibold uppercase tracking-widest">Step</label>
            <select value={step} onChange={e => setStep(e.target.value)} className={`${SEL_CLS} w-28`}>
              {(stepOpts.length ? stepOpts : Array.from({ length: 10 }, (_, i) => `STEP_${String(i+1).padStart(3,"0")}`)).map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        )}
        <button onClick={() => run(buildPath())} disabled={loading}
          className={`mt-5 flex items-center gap-1.5 px-4 py-1.5 text-white text-[11px] font-bold rounded transition-colors disabled:bg-slate-700 ${
            p.color === "blue" ? "bg-blue-700 hover:bg-blue-600" :
            p.color === "cyan" ? "bg-cyan-700 hover:bg-cyan-600" :
            p.color === "green" ? "bg-green-700 hover:bg-green-600" :
            "bg-purple-700 hover:bg-purple-600"
          }`}>
          {loading ? <RotateCcw size={12} className="animate-spin" /> : <Play size={12} />}
          {loading ? "Fetching…" : `Call ${p.id}`}
        </button>
        {elapsed != null && <span className="mt-5 text-[10px] text-slate-500 flex items-center gap-1"><Clock size={9}/> {elapsed}ms</span>}
      </div>
      {error && <div className="bg-red-900/30 border border-red-700 rounded px-3 py-2 text-[11px] text-red-300">{error}</div>}
      {data && <JsonViewer data={data} />}
    </div>
  );
}

// ── Main AIOpsLab ────────────────────────────────────────────────────────────
export default function AIOpsLab() {
  const router = useRouter();
  const [activeSkill, setActiveSkill] = useState<SkillId>("APC_AUDIT");
  const [pillarStatus, setPillarStatus] = useState<Record<PillarId, "ok"|"err"|"unknown">>({ P1:"unknown", P2:"unknown", P3:"unknown", P4:"unknown" });

  // Quick health check on mount
  const checkHealth = useCallback(async () => {
    const base = getApiBase();
    const checks: [PillarId, string][] = [
      ["P1", `/api/v2/ontology/context?lot_id=LOT-0001&step=STEP_001`],
      ["P2", `/api/v2/ontology/trajectory/tool/EQP-01`],
      ["P3", `/api/v2/ontology/trajectory/lot/LOT-0001`],
      ["P4", `/api/v2/ontology/history/APC/APC-003`],
    ];
    const results = await Promise.all(checks.map(async ([id, path]) => {
      try {
        const r = await fetch(base + path, { signal: AbortSignal.timeout(5000) });
        return [id, r.ok ? "ok" : "err"] as [PillarId, "ok"|"err"];
      } catch {
        return [id, "err"] as [PillarId, "err"];
      }
    }));
    const next: Record<PillarId, "ok"|"err"|"unknown"> = { P1:"unknown", P2:"unknown", P3:"unknown", P4:"unknown" };
    results.forEach(([id, s]) => { next[id] = s; });
    setPillarStatus(next);
  }, []);

  // Run health check once
  useState(() => { checkHealth(); });

  const SKILLS = [
    { id: "APC_AUDIT"      as SkillId, label: "APC Model Audit",    icon: "📊", category: "Pillar 4", color: "purple", sprint: "v2.3a" },
    { id: "CHAMBER_MATCH"  as SkillId, label: "Chamber Matching",   icon: "🔬", category: "Pillar 2", color: "cyan",   sprint: "v2.3a" },
    { id: "LOT_TRACE"      as SkillId, label: "Lot Trace",          icon: "🗺️", category: "Pillar 3", color: "green",  sprint: "v2.3b" },
    { id: "OOC_RCA"        as SkillId, label: "OOC Root Cause",     icon: "⚡", category: "Pillar 1", color: "blue",   sprint: "v2.3a" },
    { id: "TOOL_STATE"     as SkillId, label: "Tool State Machine", icon: "🔧", category: "Pillar 2", color: "amber",  sprint: "v2.4"  },
  ] as const;

  const pillarDot = (s: "ok"|"err"|"unknown") =>
    s === "ok" ? "bg-green-400" : s === "err" ? "bg-red-400 animate-pulse" : "bg-slate-600";

  return (
    <div className="h-screen bg-[#0b1120] flex flex-col overflow-hidden text-slate-200">

      {/* ── Header ────────────────────────────────────────────────── */}
      <header className="shrink-0 h-12 border-b border-slate-800 flex items-center px-5 gap-4 bg-slate-900/80 backdrop-blur-sm">
        <button onClick={() => router.push("/")} className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-slate-200 transition-colors">
          <ArrowLeft size={12} /> Main
        </button>
        <div className="w-px h-4 bg-slate-700" />
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-sm bg-purple-500" />
          <h1 className="text-[13px] font-bold text-slate-100">AIOps Skill Lab</h1>
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-purple-900/60 text-purple-300 border border-purple-700 font-bold">SANDBOX</span>
        </div>

        {/* Sprint badges */}
        <div className="flex items-center gap-1.5 ml-2">
          <span className="text-[9px] px-2 py-0.5 rounded-full bg-green-900/50 text-green-300 border border-green-700 font-semibold">v2.3 ✓</span>
          <span className="text-[9px] px-2 py-0.5 rounded-full bg-amber-900/50 text-amber-300 border border-amber-700 font-semibold">v2.4 RC</span>
        </div>

        {/* Pillar health */}
        <div className="ml-auto flex items-center gap-3">
          <span className="text-[10px] text-slate-500 font-semibold">PILLARS:</span>
          {(["P1","P2","P3","P4"] as PillarId[]).map(id => (
            <div key={id} className="flex items-center gap-1.5">
              <div className={`w-2 h-2 rounded-full ${pillarDot(pillarStatus[id])}`} />
              <span className="text-[10px] text-slate-400 font-mono">{id}</span>
            </div>
          ))}
          <button onClick={checkHealth} className="ml-1 text-[10px] text-slate-500 hover:text-slate-300 flex items-center gap-1 transition-colors">
            <RotateCcw size={9} /> recheck
          </button>
        </div>
      </header>

      {/* ── Body ──────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden flex">

        {/* ── LEFT sidebar ──────────────────────────────────────── */}
        <aside className="w-56 shrink-0 border-r border-slate-800 bg-slate-900/50 flex flex-col overflow-y-auto">

          {/* Pillar cards */}
          <div className="px-3 pt-3 pb-1">
            <p className="text-[9px] font-bold text-slate-500 uppercase tracking-widest mb-2">The 4 Pillars</p>
            <div className="space-y-1">
              {PILLARS.map(p => {
                const clr = PILLAR_COLORS[p.color];
                const s   = pillarStatus[p.id];
                return (
                  <button
                    key={p.id}
                    onClick={() => setActiveSkill(p.id as SkillId)}
                    className={[
                      "w-full text-left px-2.5 py-2 rounded-lg border transition-all text-[10px]",
                      activeSkill === p.id
                        ? `${clr.bg} ${clr.border} ${clr.text}`
                        : "border-transparent hover:border-slate-700 hover:bg-slate-800/40 text-slate-400",
                    ].join(" ")}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold">{p.id} · {p.label}</span>
                      <div className={`w-1.5 h-1.5 rounded-full ${pillarDot(s)}`} />
                    </div>
                    <p className="text-[9px] text-slate-500 mt-0.5">{p.desc}</p>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="px-3 my-2"><div className="border-t border-slate-800" /></div>

          {/* Skills */}
          <div className="px-3 pb-3">
            <p className="text-[9px] font-bold text-slate-500 uppercase tracking-widest mb-2">AIOps Skills</p>
            <div className="space-y-0.5">
              {SKILLS.map(sk => (
                <button
                  key={sk.id}
                  onClick={() => setActiveSkill(sk.id)}
                  className={[
                    "w-full text-left px-2.5 py-2 rounded-lg border transition-all",
                    activeSkill === sk.id
                      ? "border-slate-600 bg-slate-800 text-slate-200"
                      : "border-transparent hover:border-slate-700 hover:bg-slate-800/40 text-slate-400",
                  ].join(" ")}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[11px]">{sk.icon} {sk.label}</span>
                    <span className={`text-[8px] px-1 py-0.5 rounded font-bold ${
                      sk.sprint === "v2.4" ? "bg-amber-900/60 text-amber-400" : "bg-slate-700 text-slate-400"
                    }`}>{sk.sprint}</span>
                  </div>
                  <p className="text-[9px] text-slate-600 mt-0.5">{sk.category}</p>
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* ── CENTER ────────────────────────────────────────────── */}
        <main className="flex-1 overflow-hidden flex flex-col">
          {/* Skill header */}
          <div className="shrink-0 border-b border-slate-800 px-6 py-3 bg-slate-900/30 flex items-center gap-3">
            {(() => {
              const sk = SKILLS.find(s => s.id === activeSkill);
              const pl = PILLARS.find(p => p.id === activeSkill);
              if (sk) return (
                <>
                  <span className="text-lg">{sk.icon}</span>
                  <div>
                    <h2 className="text-[13px] font-bold text-slate-100">{sk.label}</h2>
                    <p className="text-[10px] text-slate-500">{sk.category} · {sk.sprint}</p>
                  </div>
                  <ChevronRight size={12} className="text-slate-600" />
                  <span className="text-[10px] text-slate-500 font-mono">
                    {sk.id === "APC_AUDIT"     ? "GET /history/APC/{id}" :
                     sk.id === "CHAMBER_MATCH" ? "GET /trajectory/tool/{id} × 2" :
                     sk.id === "LOT_TRACE"     ? "GET /trajectory/lot/{id}" :
                     sk.id === "OOC_RCA"       ? "GET /context?lot_id=&step=" :
                     "GET /trajectory/tool/{id}?include_state_events=true"}
                  </span>
                </>
              );
              if (pl) return (
                <>
                  <span className={`text-[13px] font-bold font-mono ${PILLAR_COLORS[pl.color].text}`}>{pl.id}</span>
                  <div>
                    <h2 className="text-[13px] font-bold text-slate-100">{pl.label} — Raw Query</h2>
                    <p className="text-[10px] text-slate-500">{pl.desc}</p>
                  </div>
                </>
              );
              return null;
            })()}
          </div>

          {/* Content */}
          <div className="flex-1 overflow-hidden p-5">
            {activeSkill === "APC_AUDIT"     && <ApcAuditPanel />}
            {activeSkill === "CHAMBER_MATCH" && <ChamberMatchPanel />}
            {activeSkill === "LOT_TRACE"     && <LotTracePanel />}
            {activeSkill === "OOC_RCA"       && <OOCRootCausePanel />}
            {activeSkill === "TOOL_STATE"    && <ToolStatePanel />}
            {activeSkill === "P4" && <ObjectHistoryPanel />}
            {(["P1","P2","P3"] as PillarId[]).includes(activeSkill as PillarId) && (
              <PillarRawPanel pillarId={activeSkill as PillarId} />
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
