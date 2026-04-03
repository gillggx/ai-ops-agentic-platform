"use client";
import { useState, useCallback, useEffect, useRef } from "react";

function getApiBase() {
  if (typeof window === "undefined") return "/simulator-api";
  const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
  return `${window.location.origin}/simulator-api`;
}

// ── Scenario registry ─────────────────────────────────────────────────────────

type VisualizerType = "GRAPH" | "ORPHAN" | "DIFF";

interface Scenario {
  id: string;
  category: string;
  categoryColor: string;
  title: string;
  painPoint: string;  // 一句話說廠務痛點
  story: string;
  whatYouWillSee: string;
  buildUrl: (base: string) => string;
  visualizerType: VisualizerType;
}

const SCENARIOS: Scenario[] = [
  {
    id: "spc_ooc",
    category: "RCA",
    categoryColor: "bg-red-100 text-red-700",
    title: "SPC OOC 根因分析",
    painPoint: "PE 接到 OOC 警報，需要在 30 分鐘內找出是「設備問題」還是「配方問題」。",
    story: "過去工程師需要分別打開 SPC 系統、MES、APC 系統、配方管理系統，手動比對四個系統的資料。",
    whatYouWillSee: "點擊 Execute 後，系統瞬間展開 LOT-0001 / STEP_004 的完整關聯圖——設備、配方、APC、DC 感測資料、SPC 量測結果——5 個節點一次呈現，OOC 事件以紅色高亮標示。",
    buildUrl: (base) => `${base}/api/v2/ontology/context?lot_id=LOT-0001&step=STEP_004&ooc_only=true`,
    visualizerType: "GRAPH",
  },
  {
    id: "data_orphan",
    category: "EE",
    categoryColor: "bg-amber-100 text-amber-700",
    title: "Data Orphan 系統抓漏",
    painPoint: "夜間批次跑完，但部分站點的 APC / DC 資料「有索引、無實體」——資料黑洞在哪？",
    story: "索引（Index）記錄了「應該要有這筆資料」，但對應的 Snapshot 文件不存在。這代表資料在寫入途中遺失，且傳統系統完全無感知。",
    whatYouWillSee: "系統掃描最近的事件，列出所有孤兒（Orphan）記錄。健康系統回傳 total_orphans=0，並顯示綠色通過徽章。",
    buildUrl: (base) => `${base}/api/v2/ontology/orphans?limit=20`,
    visualizerType: "ORPHAN",
  },
  {
    id: "recipe_drift",
    category: "PI",
    categoryColor: "bg-blue-100 text-blue-700",
    title: "Recipe 版本漂移審計",
    painPoint: "良率突然下降 2%，但沒有人改過配方？——把最近兩筆 RECIPE 快照並排比較。",
    story: "每次批次完成，系統會對該時刻的配方參數拍下快照。把兩個批次的快照並排，紅色 = 數值上升、藍色 = 數值下降，微小漂移立刻可見。",
    whatYouWillSee: "撈出最近 2 筆 RECIPE 物件快照，20 個參數逐一比對，有差異的行以顏色高亮，Δ 欄顯示精確數值偏移。",
    buildUrl: (base) => `${base}/api/v2/ontology/indices/RECIPE?limit=2`,
    visualizerType: "DIFF",
  },
];

// ── Graph Context Visualizer (Scenario 1) ─────────────────────────────────────

type ContextData = {
  root?: Record<string, unknown>;
  tool?: Record<string, unknown>;
  recipe?: Record<string, unknown>;
  apc?: Record<string, unknown>;
  dc?: Record<string, unknown>;
  spc?: Record<string, unknown>;
};

const GRAPH_NODES = [
  { key: "tool",   label: "EQUIPMENT", color: "#64748b", textColor: "#f8fafc" },
  { key: "recipe", label: "RECIPE",    color: "#0284c7", textColor: "#f0f9ff" },
  { key: "apc",    label: "APC",       color: "#0d9488", textColor: "#f0fdfa" },
  { key: "dc",     label: "DC",        color: "#4f46e5", textColor: "#eef2ff" },
  { key: "spc",    label: "SPC",       color: "#d97706", textColor: "#fffbeb" },
];

function GraphVisualizer({ data }: { data: ContextData | null }) {
  if (!data?.root) return (
    <div className="h-full flex items-center justify-center">
      <p className="text-[13px] text-slate-400">按下 Execute 展開關聯圖</p>
    </div>
  );

  const root = data.root;
  const isOOC = root.spc_status === "OOC";

  return (
    <div className="h-full overflow-y-auto p-5 space-y-4">
      {/* Root event banner */}
      <div className={[
        "rounded-xl border-2 px-5 py-3 flex items-center justify-between",
        isOOC ? "bg-red-50 border-red-400" : "bg-emerald-50 border-emerald-400",
      ].join(" ")}>
        <div>
          <div className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-0.5">PROCESS EVENT</div>
          <div className="text-[15px] font-bold font-mono text-slate-800">
            {String(root.lot_id)} · {String(root.step)}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            {String(root.event_time ?? "").slice(0, 19)} · Tool: {String(root.tool_id)}
          </div>
        </div>
        <div className={[
          "text-[13px] font-bold px-4 py-2 rounded-lg border-2",
          isOOC
            ? "bg-red-500 text-white border-red-600"
            : "bg-emerald-500 text-white border-emerald-600",
        ].join(" ")}>
          SPC {isOOC ? "⚡ OOC" : "✓ PASS"}
        </div>
      </div>

      {/* Connected nodes grid */}
      <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">↓ 關聯節點 (5 subsystems)</div>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
        {GRAPH_NODES.map(n => {
          const nodeData = data[n.key as keyof ContextData] as Record<string, unknown> | null | undefined;
          const isOrphan = nodeData?.orphan === true;
          const params   = nodeData?.parameters as Record<string, unknown> | null | undefined;
          const paramCount = params ? Object.keys(params).length : 0;
          const mainVal = nodeData?.objectID ?? nodeData?.tool_id ?? nodeData?.object_id ?? "—";

          return (
            <div
              key={n.key}
              className={[
                "rounded-xl border-2 px-4 py-3",
                isOrphan ? "border-red-400 bg-red-50" : "bg-white",
              ].join(" ")}
              style={{ borderColor: isOrphan ? "#dc2626" : n.color }}
            >
              <div className="flex items-center justify-between mb-1.5">
                <span
                  className="text-[9px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full"
                  style={{ background: n.color, color: n.textColor }}
                >
                  {n.label}
                </span>
                {isOrphan
                  ? <span className="text-[10px] text-red-600 font-bold animate-pulse">⚡ ORPHAN</span>
                  : <span className="text-[10px] text-emerald-600 font-semibold">✓ OK</span>
                }
              </div>
              <div className="text-[12px] font-mono font-bold text-slate-800 truncate">
                {String(mainVal)}
              </div>
              {paramCount > 0 && (
                <div className="text-[9px] text-slate-400 mt-1">{paramCount} parameters captured</div>
              )}
              {n.key === "spc" && typeof nodeData?.spc_status === "string" && (
                <div className={`text-[10px] font-bold mt-1 ${nodeData.spc_status === "OOC" ? "text-red-600" : "text-emerald-600"}`}>
                  {nodeData.spc_status}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Orphan Visualizer (Scenario 2) ────────────────────────────────────────────

type OrphanData = { total_orphans: number; orphans: Array<{ lotID: string; step: string; broken_links: Array<{ subsystem: string }> }> };

function OrphanVisualizer({ data }: { data: OrphanData | null }) {
  if (!data) return (
    <div className="h-full flex items-center justify-center">
      <p className="text-[13px] text-slate-400">按下 Execute 掃描孤兒資料</p>
    </div>
  );

  const healthy = data.total_orphans === 0;

  return (
    <div className="h-full overflow-y-auto p-5 space-y-4">
      {/* Health badge */}
      <div className={[
        "rounded-xl border-2 px-5 py-4 flex items-center gap-4",
        healthy ? "bg-emerald-50 border-emerald-300" : "bg-red-50 border-red-400",
      ].join(" ")}>
        <div className={`text-4xl ${healthy ? "" : "animate-pulse"}`}>
          {healthy ? "✅" : "⚡"}
        </div>
        <div>
          <div className={`text-[18px] font-bold ${healthy ? "text-emerald-700" : "text-red-700"}`}>
            {healthy ? "系統資料完整性健康" : `發現 ${data.total_orphans} 筆孤兒資料`}
          </div>
          <div className="text-[12px] text-slate-500 mt-0.5">
            {healthy
              ? "所有快照索引均對應到實際資料文件，無遺失。"
              : "以下事件的子系統 Payload 遺失，需要工程師確認。"}
          </div>
        </div>
      </div>

      {/* Orphan list */}
      {data.orphans.length > 0 && (
        <div className="space-y-2">
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">異常記錄</div>
          {data.orphans.slice(0, 10).map((o, i) => (
            <div key={i} className="bg-red-50 border border-red-200 rounded-lg px-4 py-2.5 flex items-center justify-between">
              <div>
                <span className="text-[12px] font-mono font-bold text-red-700">{o.lotID}</span>
                <span className="text-[11px] text-slate-500 ml-2">{o.step}</span>
              </div>
              <div className="flex gap-1">
                {o.broken_links.map((l, j) => (
                  <span key={j} className="text-[9px] font-bold bg-red-200 text-red-800 px-2 py-0.5 rounded">
                    {l.subsystem}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Recipe Diff Visualizer (Scenario 3) ──────────────────────────────────────

type RecipeRecord = { object_id: string; event_time: string; payload: { parameters: Record<string, number> } };
type IndexData = { records: RecipeRecord[] };

function DiffVisualizer({ data }: { data: IndexData | null }) {
  if (!data) return (
    <div className="h-full flex items-center justify-center">
      <p className="text-[13px] text-slate-400">按下 Execute 載入配方快照比對</p>
    </div>
  );

  const records = data.records ?? [];
  if (records.length < 2) return (
    <div className="p-5">
      <p className="text-[12px] text-slate-500">需要至少 2 筆記錄才能比對（目前 {records.length} 筆）。</p>
    </div>
  );

  const [a, b] = records;
  const paramsA = a.payload?.parameters ?? {};
  const paramsB = b.payload?.parameters ?? {};
  const allKeys = Array.from(new Set([...Object.keys(paramsA), ...Object.keys(paramsB)])).sort();
  const changedCount = allKeys.filter(k => {
    const va = paramsA[k] ?? null;
    const vb = paramsB[k] ?? null;
    return va !== null && vb !== null && Math.abs(va - vb) > 1e-6;
  }).length;

  return (
    <div className="h-full overflow-y-auto p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between bg-slate-50 border border-slate-200 rounded-xl px-4 py-3">
        <div>
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">Recipe Parameter Diff</div>
          <div className="flex items-center gap-3">
            <span className="text-[11px] font-mono bg-green-100 text-green-800 px-2 py-0.5 rounded">A: {a.object_id}</span>
            <span className="text-slate-400">vs</span>
            <span className="text-[11px] font-mono bg-blue-100 text-blue-800 px-2 py-0.5 rounded">B: {b.object_id}</span>
          </div>
        </div>
        <div className={[
          "text-[14px] font-bold px-3 py-1.5 rounded-lg border",
          changedCount > 0
            ? "bg-amber-50 border-amber-300 text-amber-700"
            : "bg-emerald-50 border-emerald-300 text-emerald-700",
        ].join(" ")}>
          {changedCount > 0 ? `${changedCount} 參數漂移` : "✓ 無漂移"}
        </div>
      </div>

      {/* Diff table */}
      <table className="w-full text-[11px] font-mono border-collapse">
        <thead>
          <tr className="bg-slate-100 text-[9px] font-bold uppercase tracking-wider text-slate-500">
            <th className="text-left px-3 py-2 border border-slate-200 w-28">Parameter</th>
            <th className="text-right px-3 py-2 border border-slate-200 text-green-700">A (新)</th>
            <th className="text-right px-3 py-2 border border-slate-200 text-blue-700">B (舊)</th>
            <th className="text-right px-3 py-2 border border-slate-200">Δ</th>
          </tr>
        </thead>
        <tbody>
          {allKeys.map(k => {
            const va      = paramsA[k] ?? null;
            const vb      = paramsB[k] ?? null;
            const diff    = va !== null && vb !== null ? va - vb : null;
            const changed = diff !== null && Math.abs(diff) > 1e-6;
            return (
              <tr key={k} className={changed ? "bg-amber-50" : ""}>
                <td className="px-3 py-1.5 border border-slate-100 text-slate-600">{k}</td>
                <td className="px-3 py-1.5 border border-slate-100 text-right text-slate-700">
                  {va !== null ? va.toFixed(4) : "—"}
                </td>
                <td className="px-3 py-1.5 border border-slate-100 text-right text-slate-700">
                  {vb !== null ? vb.toFixed(4) : "—"}
                </td>
                <td className={[
                  "px-3 py-1.5 border border-slate-100 text-right font-bold",
                  changed
                    ? diff! > 0 ? "text-red-600" : "text-blue-600"
                    : "text-slate-300",
                ].join(" ")}>
                  {diff !== null ? (diff > 0 ? "+" : "") + diff.toFixed(4) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Main ScenarioBrowser ──────────────────────────────────────────────────────

export default function ScenarioBrowser() {
  const [selectedId, setSelectedId] = useState<string>(SCENARIOS[0].id);
  const [executing,  setExecuting]  = useState(false);
  const [result,     setResult]     = useState<Record<string, unknown> | null>(null);
  const [error,      setError]      = useState<string | null>(null);
  const [apiUrl,     setApiUrl]     = useState<string>("");
  const baseRef = useRef<string>("");

  const selected = SCENARIOS.find(s => s.id === selectedId)!;

  useEffect(() => {
    baseRef.current = getApiBase();
    const url = selected.buildUrl(baseRef.current);
    setApiUrl(url);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSelect = useCallback((scenario: Scenario) => {
    setSelectedId(scenario.id);
    const url = scenario.buildUrl(baseRef.current || getApiBase());
    setApiUrl(url);
    setResult(null);
    setError(null);
  }, []);

  const handleExecute = useCallback(async () => {
    const url = selected.buildUrl(baseRef.current || getApiBase());
    setApiUrl(url);
    setExecuting(true);
    setError(null);
    try {
      const res = await fetch(url);
      if (!res.ok) {
        const msg = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(msg.detail ?? res.statusText);
      }
      setResult(await res.json());
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setExecuting(false);
    }
  }, [selected]);

  return (
    <div className="h-full flex overflow-hidden bg-white">

      {/* ── Left: Use Case List ──────────────────────────────────── */}
      <div className="w-[230px] shrink-0 border-r border-slate-200 flex flex-col overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200 bg-slate-50">
          <div className="text-[11px] font-bold text-slate-600 uppercase tracking-widest">Use Case Library</div>
          <div className="text-[10px] text-slate-400 mt-0.5">選擇情境 → Execute → 看結果</div>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
          {SCENARIOS.map(sc => (
            <button
              key={sc.id}
              onClick={() => handleSelect(sc)}
              className={[
                "w-full text-left p-3 rounded-xl border transition-all",
                sc.id === selectedId
                  ? "bg-violet-50 border-violet-300 shadow-sm"
                  : "bg-white border-slate-200 hover:bg-slate-50",
              ].join(" ")}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${sc.categoryColor}`}>
                  {sc.category}
                </span>
              </div>
              <div className={`text-[12px] font-semibold ${sc.id === selectedId ? "text-violet-800" : "text-slate-700"}`}>
                {sc.title}
              </div>
              <div className="text-[10px] text-slate-400 mt-1 leading-snug line-clamp-2">
                {sc.painPoint}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* ── Middle: Story + API ──────────────────────────────────── */}
      <div className="w-[280px] shrink-0 border-r border-slate-200 flex flex-col overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200 flex items-center gap-2">
          <span className={`text-[9px] font-bold px-2 py-0.5 rounded ${selected.categoryColor}`}>
            {selected.category}
          </span>
          <span className="text-[12px] font-bold text-slate-800">{selected.title}</span>
        </div>

        <div className="flex-1 overflow-y-auto">
          {/* Pain point */}
          <div className="px-4 py-3 border-b border-slate-100 bg-amber-50">
            <div className="text-[9px] font-bold text-amber-700 uppercase tracking-widest mb-1">🔥 廠務痛點</div>
            <p className="text-[11px] text-amber-900 leading-relaxed font-medium">{selected.painPoint}</p>
          </div>

          {/* Story */}
          <div className="px-4 py-3 border-b border-slate-100">
            <div className="text-[9px] font-bold text-slate-500 uppercase tracking-widest mb-1.5">📋 背景</div>
            <p className="text-[11px] text-slate-600 leading-relaxed">{selected.story}</p>
          </div>

          {/* What you will see */}
          <div className="px-4 py-3 border-b border-slate-100">
            <div className="text-[9px] font-bold text-violet-600 uppercase tracking-widest mb-1.5">👁 你將看到</div>
            <p className="text-[11px] text-slate-600 leading-relaxed">{selected.whatYouWillSee}</p>
          </div>

          {/* API URL */}
          <div className="px-4 py-3">
            <div className="text-[9px] font-bold text-blue-600 uppercase tracking-widest mb-1.5">🔗 API</div>
            <div className="bg-slate-900 rounded-lg p-2.5">
              <code className="text-[9px] text-green-300 font-mono leading-relaxed break-all">{apiUrl}</code>
            </div>
          </div>
        </div>

        {/* Execute button */}
        <div className="shrink-0 px-4 py-3 border-t border-slate-200">
          <button
            onClick={handleExecute}
            disabled={executing}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white font-bold text-[13px] transition-colors shadow-sm"
          >
            {executing
              ? <><span className="animate-spin">⟳</span> 查詢中…</>
              : <>▶ Execute — 立即查詢</>
            }
          </button>
          {error && (
            <p className="text-[11px] text-red-600 mt-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
        </div>
      </div>

      {/* ── Right: Dynamic Visualizer ───────────────────────────── */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <div className="shrink-0 px-4 py-2.5 border-b border-slate-200 bg-slate-50 flex items-center gap-3">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
            Dynamic Visualizer
          </span>
          <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full ${
            selected.visualizerType === "GRAPH"  ? "bg-violet-100 text-violet-700" :
            selected.visualizerType === "ORPHAN" ? "bg-amber-100 text-amber-700" :
                                                    "bg-blue-100 text-blue-700"
          }`}>
            {selected.visualizerType === "GRAPH" ? "關聯圖 (Graph Context)" :
             selected.visualizerType === "ORPHAN" ? "孤兒掃描 (Orphan Scan)" :
                                                    "差異比較 (Param Diff)"}
          </span>
          {result && <span className="ml-auto text-[9px] text-emerald-600 font-semibold">✓ 資料已載入</span>}
        </div>
        <div className="flex-1 overflow-hidden">
          {selected.visualizerType === "GRAPH"  && <GraphVisualizer  data={result as ContextData | null} />}
          {selected.visualizerType === "ORPHAN" && <OrphanVisualizer data={result as OrphanData | null} />}
          {selected.visualizerType === "DIFF"   && <DiffVisualizer   data={result as IndexData | null} />}
        </div>
      </div>

    </div>
  );
}
