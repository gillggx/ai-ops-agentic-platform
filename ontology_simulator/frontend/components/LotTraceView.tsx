"use client";
import { useState, useCallback, useRef } from "react";
import { Search, ChevronRight } from "lucide-react";

function getApiBase() {
  if (typeof window === "undefined") return "http://localhost:8001";
  const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
  return isLocal
    ? `http://${window.location.hostname}:8001`
    : `${window.location.origin}/simulator-api`;
}

interface StepRecord {
  event_id: string;
  step: string;
  event_time: string;
  tool_id: string;
  recipe_id: string | null;
  apc_id: string | null;
  dc_snapshot_id: string | null;
  spc_snapshot_id: string | null;
  spc_status: string | null;
}

interface TrajectoryResponse {
  lot_id: string;
  total_steps: number;
  steps: StepRecord[];
}

const CARD_TYPES = ["TOOL", "RECIPE", "APC", "DC", "SPC"] as const;
type CardType = typeof CARD_TYPES[number];

const CARD_STYLE: Record<CardType, { bg: string; border: string; label: string; dot: string }> = {
  TOOL:   { bg: "bg-slate-50",  border: "border-slate-300", label: "text-slate-500",  dot: "bg-slate-400" },
  RECIPE: { bg: "bg-green-50",  border: "border-green-300", label: "text-green-700",  dot: "bg-green-400" },
  APC:    { bg: "bg-sky-50",    border: "border-sky-300",   label: "text-sky-700",    dot: "bg-sky-400"   },
  DC:     { bg: "bg-indigo-50", border: "border-indigo-300",label: "text-indigo-700", dot: "bg-indigo-400"},
  SPC:    { bg: "bg-amber-50",  border: "border-amber-300", label: "text-amber-700",  dot: "bg-amber-400" },
};

function cardValue(type: CardType, step: StepRecord): string | null {
  switch (type) {
    case "TOOL":   return step.tool_id;
    case "RECIPE": return step.recipe_id;
    case "APC":    return step.apc_id;
    case "DC":     return step.dc_snapshot_id ? `DC-${step.dc_snapshot_id.slice(-6)}` : null;
    case "SPC":    return step.spc_snapshot_id ? `SPC-${step.spc_snapshot_id.slice(-6)}` : null;
  }
}

export default function LotTraceView() {
  const [inputLot,    setInputLot]    = useState("LOT-0001");
  const [loading,     setLoading]     = useState(false);
  const [trajectory,  setTrajectory]  = useState<TrajectoryResponse | null>(null);
  const [error,       setError]       = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [activeCard,  setActiveCard]  = useState<CardType | null>(null);
  const [inspecting,  setInspecting]  = useState<object | null>(null);
  const [inspectLoading, setInspectLoading] = useState(false);

  // Store lot_id for use in fetchSnapshot (avoids stale-closure on trajectory state)
  const lotIdRef = useRef<string>("");

  const fetchTrajectory = useCallback(async (lotId: string) => {
    setLoading(true);
    setError(null);
    setSelectedIdx(null);
    setActiveCard(null);
    setInspecting(null);
    try {
      const res = await fetch(`${getApiBase()}/api/v2/ontology/trajectory/${encodeURIComponent(lotId)}`);
      if (!res.ok) {
        const msg = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(msg.detail ?? res.statusText);
      }
      const data: TrajectoryResponse = await res.json();
      lotIdRef.current = data.lot_id;
      setTrajectory(data);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchSnapshot = useCallback(async (type: CardType, step: StepRecord) => {
    const base = getApiBase();
    let url: string | null = null;

    const et  = encodeURIComponent(step.event_time);
    const stp = encodeURIComponent(step.step ?? "STEP_001");

    switch (type) {
      case "TOOL":
        // TOOL: context/query queries tools master collection; step+eventTime are
        // required URL params even though the server ignores them for TOOL.
        url = `${base}/api/v1/context/query?objectName=TOOL&targetID=${encodeURIComponent(step.tool_id)}&step=${stp}&eventTime=${et}`;
        break;
      case "RECIPE":
        if (!step.recipe_id) return;
        url = `${base}/api/v1/context/query?objectName=RECIPE&targetID=${encodeURIComponent(step.recipe_id)}&step=${stp}&eventTime=${et}`;
        break;
      case "APC":
        if (!step.apc_id) return;
        url = `${base}/api/v1/context/query?objectName=APC&targetID=${encodeURIComponent(step.apc_id)}&step=${stp}&eventTime=${et}`;
        break;
      case "DC":
      case "SPC":
        // Use graph context — returns the full step including DC/SPC snapshots
        url = `${base}/api/v2/ontology/context?lot_id=${encodeURIComponent(lotIdRef.current)}&step=${stp}`;
        break;
    }

    if (!url) return;
    setInspectLoading(true);
    setInspecting(null);
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      // For DC/SPC, drill into the relevant node from the graph context response
      if (type === "DC" && data.dc) {
        setInspecting(data.dc);
      } else if (type === "SPC" && data.spc) {
        setInspecting(data.spc);
      } else {
        setInspecting(data);
      }
    } catch (e: unknown) {
      setInspecting({ error: (e as Error).message });
    } finally {
      setInspectLoading(false);
    }
  }, []);

  const handleCardClick = useCallback((type: CardType, step: StepRecord) => {
    setActiveCard(type);
    fetchSnapshot(type, step);
  }, [fetchSnapshot]);

  const steps = trajectory?.steps ?? [];
  // Deduplicate by step name (keep latest occurrence per step)
  const seenSteps = new Map<string, StepRecord>();
  for (const s of steps) seenSteps.set(s.step, s);
  const uniqueSteps = Array.from(seenSteps.values());

  const selectedStep = selectedIdx !== null ? uniqueSteps[selectedIdx] : null;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* ── Search bar ─────────────────────────────────────────── */}
      <div className="shrink-0 px-4 py-2.5 border-b border-slate-200 bg-white flex items-center gap-2">
        <Search size={13} className="text-slate-400" />
        <input
          className="flex-1 text-[12px] font-mono border border-slate-200 rounded-md px-2 py-1 outline-none focus:border-blue-400"
          placeholder="Lot ID (e.g. LOT-0007)"
          value={inputLot}
          onChange={e => setInputLot(e.target.value)}
          onKeyDown={e => e.key === "Enter" && fetchTrajectory(inputLot.trim())}
        />
        <button
          onClick={() => fetchTrajectory(inputLot.trim())}
          disabled={loading}
          className="text-[11px] font-bold px-3 py-1 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {loading ? "…" : "TRACE"}
        </button>
      </div>

      {error && (
        <div className="shrink-0 px-4 py-2 text-[11px] text-red-600 bg-red-50 border-b border-red-200">
          {error}
        </div>
      )}

      {/* ── Body ───────────────────────────────────────────────── */}
      {!trajectory ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-[12px] text-slate-400">Enter a Lot ID and press TRACE</p>
        </div>
      ) : (
        <div className="flex-1 overflow-hidden flex">

          {/* Left: vertical timeline */}
          <div className="w-[200px] shrink-0 overflow-y-auto border-r border-slate-200 bg-slate-50">
            <div className="px-3 py-2 border-b border-slate-200 bg-white">
              <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                {trajectory.lot_id}
              </span>
              <span className="text-[10px] text-slate-400 ml-1">
                · {uniqueSteps.length} steps
              </span>
            </div>
            <div className="relative border-l-2 border-slate-200 ml-5 pl-3 py-2 space-y-1">
              {uniqueSteps.map((s, i) => {
                const isOOC      = s.spc_status === "OOC";
                const isSelected = selectedIdx === i;
                return (
                  <div
                    key={s.step}
                    onClick={() => { setSelectedIdx(i); setActiveCard(null); setInspecting(null); }}
                    className={[
                      "relative cursor-pointer rounded px-2 py-1.5 transition-colors",
                      isSelected ? "bg-blue-50 border border-blue-200" : "hover:bg-slate-100",
                    ].join(" ")}
                  >
                    <div className={[
                      "absolute -left-[18px] top-2 w-2.5 h-2.5 rounded-full border-2",
                      isSelected ? "bg-blue-100 border-blue-500"
                        : isOOC ? "bg-amber-50 border-amber-400"
                        : "bg-white border-slate-300",
                    ].join(" ")} />
                    <div className={`text-[11px] font-mono font-bold flex items-center gap-1 ${isSelected ? "text-blue-700" : "text-slate-700"}`}>
                      {s.step.replace("STEP_", "S")}
                      {isOOC && (
                        <span className="text-[8px] bg-amber-100 text-amber-700 px-1 rounded font-normal">OOC</span>
                      )}
                      {isSelected && <ChevronRight size={9} className="ml-auto text-blue-400" />}
                    </div>
                    <div className="text-[9px] text-slate-400 truncate">{s.tool_id}</div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Middle: cards */}
          <div className="w-[200px] shrink-0 border-r border-slate-200 bg-white overflow-y-auto">
            {!selectedStep ? (
              <div className="flex items-center justify-center h-full">
                <p className="text-[11px] text-slate-400">Click a step →</p>
              </div>
            ) : (
              <div className="p-3 space-y-2">
                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">
                  {selectedStep.step}
                </div>
                <div className="text-[9px] text-slate-400 mb-2">
                  {new Date(selectedStep.event_time).toLocaleString()}
                </div>
                {CARD_TYPES.map(type => {
                  const val = cardValue(type, selectedStep);
                  const style = CARD_STYLE[type];
                  const isActive = activeCard === type;
                  return (
                    <button
                      key={type}
                      onClick={() => val && handleCardClick(type, selectedStep)}
                      disabled={!val}
                      className={[
                        "w-full text-left px-3 py-2 rounded-lg border transition-all",
                        style.bg, style.border,
                        val
                          ? isActive ? "ring-2 ring-blue-400 shadow-md" : "hover:shadow-sm cursor-pointer"
                          : "opacity-40 cursor-not-allowed",
                      ].join(" ")}
                    >
                      <div className={`text-[9px] font-bold uppercase tracking-widest flex items-center gap-1.5 ${style.label}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
                        {type}
                      </div>
                      <div className="text-[11px] font-mono text-slate-700 mt-0.5 truncate">
                        {val ?? "—"}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Right: JSON Inspector */}
          <div className="flex-1 overflow-hidden bg-slate-900 flex flex-col">
            <div className="shrink-0 px-3 py-2 border-b border-slate-700 flex items-center justify-between">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">
                JSON Inspector
              </span>
              {activeCard && (
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${CARD_STYLE[activeCard].label} ${CARD_STYLE[activeCard].bg}`}>
                  {activeCard}
                </span>
              )}
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              {inspectLoading ? (
                <p className="text-[11px] text-slate-400 animate-pulse">Loading…</p>
              ) : inspecting ? (
                <pre className="text-[10px] text-green-300 font-mono whitespace-pre-wrap leading-relaxed">
                  {JSON.stringify(inspecting, null, 2)}
                </pre>
              ) : (
                <p className="text-[11px] text-slate-500">
                  {selectedStep ? "Click a card to inspect its snapshot" : "Select a step first"}
                </p>
              )}
            </div>
          </div>

        </div>
      )}
    </div>
  );
}
