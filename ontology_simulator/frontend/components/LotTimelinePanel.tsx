"use client";
/**
 * LotTimelinePanel — Mode B (Lot View) LEFT column
 *
 * Renders the Lot ID search box + vertical timeline.
 * When a step is clicked it converts the StepRecord → EventDoc
 * and calls onStepSelect, which Dashboard wires to handleTraceSelect
 * so the center TopologyView updates automatically.
 */
import { useState, useCallback } from "react";
import { Search, ChevronRight } from "lucide-react";

function getApiBase() {
  if (typeof window === "undefined") return "http://localhost:8001";
  const isLocal =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";
  return isLocal
    ? `http://${window.location.hostname}:8001`
    : `${window.location.origin}/simulator-api`;
}

export interface LotStepEvent {
  eventTime: string;
  eventType: string;
  lotID: string;
  toolID: string;
  step: string;
  recipeID?: string | null;
  spc_status?: string | null;
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

interface Props {
  onStepSelect: (evt: LotStepEvent) => void;
  selectedTime: string | null;
}

export default function LotTimelinePanel({ onStepSelect, selectedTime }: Props) {
  const [inputLot,   setInputLot]   = useState("LOT-0001");
  const [loading,    setLoading]    = useState(false);
  const [trajectory, setTrajectory] = useState<TrajectoryResponse | null>(null);
  const [error,      setError]      = useState<string | null>(null);

  const fetchTrajectory = useCallback(async (lotId: string) => {
    setLoading(true);
    setError(null);
    setTrajectory(null);
    try {
      const res = await fetch(
        `${getApiBase()}/api/v2/ontology/trajectory/${encodeURIComponent(lotId)}`
      );
      if (!res.ok) {
        const msg = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(msg.detail ?? res.statusText);
      }
      const data: TrajectoryResponse = await res.json();
      setTrajectory(data);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Deduplicate steps by step name (keep latest per step)
  const steps: StepRecord[] = (() => {
    if (!trajectory) return [];
    const seen = new Map<string, StepRecord>();
    for (const s of trajectory.steps) seen.set(s.step, s);
    return Array.from(seen.values());
  })();

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* ── Search bar ──────────────────────────────────────────── */}
      <div className="shrink-0 px-3 py-2 border-b border-slate-200 bg-white flex items-center gap-1.5">
        <Search size={12} className="text-slate-400 shrink-0" />
        <input
          className="flex-1 min-w-0 text-[11px] font-mono border border-slate-200 rounded px-2 py-1 outline-none focus:border-blue-400"
          placeholder="LOT-XXXX"
          value={inputLot}
          onChange={e => setInputLot(e.target.value)}
          onKeyDown={e => e.key === "Enter" && fetchTrajectory(inputLot.trim())}
        />
        <button
          onClick={() => fetchTrajectory(inputLot.trim())}
          disabled={loading}
          className="shrink-0 text-[10px] font-bold px-2 py-1 rounded bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50 transition-colors"
        >
          {loading ? "…" : "GO"}
        </button>
      </div>

      {error && (
        <div className="shrink-0 px-3 py-1.5 text-[10px] text-red-600 bg-red-50 border-b border-red-200">
          {error}
        </div>
      )}

      {!trajectory ? (
        <div className="flex-1 flex items-center justify-center px-3">
          <p className="text-[11px] text-slate-400 text-center">
            Enter a Lot ID and press GO
          </p>
        </div>
      ) : (
        <>
          {/* Lot label + step count */}
          <div className="shrink-0 px-3 py-1.5 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
            <span className="text-[10px] font-bold text-purple-600 font-mono">
              {trajectory.lot_id}
            </span>
            <span className="text-[9px] text-slate-400">{steps.length} steps</span>
          </div>

          {/* Vertical timeline */}
          <div className="flex-1 overflow-y-auto">
            <div className="relative border-l-2 border-slate-200 ml-5 pl-3 py-2 space-y-1">
              {steps.map((s) => {
                const isOOC      = s.spc_status === "OOC";
                const isSelected = selectedTime === s.event_time;
                return (
                  <div
                    key={s.step}
                    onClick={() => {
                      const stepNum = parseInt(s.step.split("_")[1]);
                      onStepSelect({
                        eventTime:  s.event_time,
                        eventType:  "TOOL_EVENT",
                        lotID:      trajectory.lot_id,
                        toolID:     s.tool_id,
                        step:       s.step,
                        recipeID:   s.recipe_id,
                        spc_status: s.spc_status,
                      });
                    }}
                    className={[
                      "relative cursor-pointer rounded px-2 py-1.5 transition-colors",
                      isSelected
                        ? "bg-purple-50 border border-purple-200"
                        : "hover:bg-slate-100",
                    ].join(" ")}
                  >
                    {/* Timeline dot */}
                    <div
                      className={[
                        "absolute -left-[18px] top-2 w-2.5 h-2.5 rounded-full border-2",
                        isSelected
                          ? "bg-purple-100 border-purple-500"
                          : isOOC
                          ? "bg-amber-50 border-amber-400"
                          : "bg-white border-slate-300",
                      ].join(" ")}
                    />

                    <div
                      className={`text-[11px] font-mono font-bold flex items-center gap-1 ${
                        isSelected ? "text-purple-700" : "text-slate-700"
                      }`}
                    >
                      {s.step.replace("STEP_", "S")}
                      {isOOC && (
                        <span className="text-[8px] bg-amber-100 text-amber-700 px-1 rounded font-normal">
                          OOC
                        </span>
                      )}
                      {isSelected && (
                        <ChevronRight size={9} className="ml-auto text-purple-400" />
                      )}
                    </div>
                    <div className="text-[9px] text-slate-400 truncate">{s.tool_id}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
