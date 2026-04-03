"use client";
import { MachineState } from "@/lib/types";

const DISPLAY_NAME: Record<string, string> = {
  "EQP-01": "ETCH-LAM-01", "EQP-02": "ETCH-LAM-02",
  "EQP-03": "ETCH-LAM-03", "EQP-04": "ETCH-LAM-04",
  "EQP-05": "PHO-ASML-01", "EQP-06": "PHO-ASML-02",
  "EQP-07": "CVD-AMAT-01", "EQP-08": "CVD-AMAT-02",
  "EQP-09": "IMP-VARIAN-01","EQP-10": "IMP-VARIAN-02",
};

const STAGE_LABEL: Record<string, string> = {
  STAGE_IDLE:      "STANDBY",
  STAGE_LOAD:      "LOADING",
  STAGE_PROCESS:   "PROCESSING",
  STAGE_ANALYSIS:  "ANALYSIS",
  STAGE_DONE_PASS: "PASS",
  STAGE_DONE_OOC:  "HOLD",
};

export default function MachineCard({
  machine, isSelected, onClick, onAcknowledge,
}: {
  machine: MachineState;
  isSelected: boolean;
  onClick: (m: MachineState) => void;
  onAcknowledge: (id: string) => void;
}) {
  const displayName = DISPLAY_NAME[machine.id] ?? machine.id;
  const isHold    = machine.stage === "STAGE_DONE_OOC";
  const isRunning = machine.stage !== "STAGE_IDLE" && !isHold;
  const stageLabel = STAGE_LABEL[machine.stage] ?? machine.stage;

  return (
    <div
      onClick={() => onClick(machine)}
      className={[
        "rounded-lg border p-3 cursor-pointer shadow-sm select-none",
        isHold
          ? "border-2 border-amber-300 bg-amber-50 transition-colors duration-150"
          : isSelected
            ? "border-blue-400 bg-blue-50 transition-colors duration-150"
            : "border-slate-200 bg-white opacity-90 hover:opacity-100 hover:border-slate-300 hover:bg-slate-50 transition-all duration-150",
        !isRunning && !isHold ? "opacity-70 hover:opacity-100" : "",
      ].join(" ")}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-slate-800 text-[13px] font-mono tracking-wide">
          {displayName}
        </span>
        <span className={[
          "text-[10px] font-bold tracking-widest px-1.5 py-0.5 rounded border",
          isHold
            ? "bg-amber-100 text-amber-700 border-amber-300"
            : isRunning
              ? "bg-blue-100 text-blue-600 border-blue-200"
              : "bg-slate-100 text-slate-400 border-slate-200",
        ].join(" ")}>
          {stageLabel}
        </span>
      </div>

      {/* HOLD details */}
      {isHold && (
        <div className="space-y-1.5">
          {/* Hold type label */}
          <p className="text-[11px] text-amber-600 font-medium">
            {machine.holdType === "EQUIPMENT"
              ? "⚠ Equipment fault — awaiting engineer"
              : "⚠ SPC Out of Control"}
          </p>
          <div className="flex justify-between text-[12px]">
            <span className="text-slate-400">Lot</span>
            <span className="font-mono text-amber-700">{machine.lotId ?? "—"}</span>
          </div>
          {machine.step && (
            <div className="flex justify-between text-[12px]">
              <span className="text-slate-400">Step</span>
              <span className="font-mono text-slate-600">{machine.step}</span>
            </div>
          )}
          {machine.bias !== null && (
            <div className="flex justify-between text-[12px]">
              <span className="text-slate-400">Bias</span>
              <span className="font-mono text-amber-600">
                {machine.bias.toFixed(4)} nm {machine.biasTrend === "UP" ? "↑" : "↓"}
              </span>
            </div>
          )}
          <button
            onClick={e => { e.stopPropagation(); onAcknowledge(machine.id); }}
            className="w-full mt-1 text-[11px] font-semibold text-amber-700 border border-amber-400
                       bg-white hover:bg-amber-50 rounded px-2 py-1 transition-colors"
          >
            {machine.holdType === "EQUIPMENT" ? "➔ ACKNOWLEDGE · RESUME" : "➔ ACKNOWLEDGE · RESET"}
          </button>
        </div>
      )}

      {/* RUNNING details */}
      {isRunning && (
        <div className="space-y-0.5">
          <div className="flex justify-between text-[12px]">
            <span className="text-slate-400">Lot</span>
            <span className="font-mono text-slate-700">{machine.lotId ?? "—"}</span>
          </div>
          <div className="flex justify-between text-[12px]">
            <span className="text-slate-400">Recipe</span>
            <span className="font-mono text-blue-600">{machine.recipe ?? "—"}</span>
          </div>
          {machine.step && (
            <div className="flex justify-between text-[12px]">
              <span className="text-slate-400">Step</span>
              <span className="font-mono text-slate-600">{machine.step}</span>
            </div>
          )}
          {machine.bias !== null && (
            <div className="flex justify-between text-[12px]">
              <span className="text-slate-400">Bias</span>
              <span className={`font-mono ${machine.biasAlert ? "text-amber-600" : "text-slate-600"}`}>
                {machine.bias.toFixed(4)} nm {machine.biasTrend === "UP" ? "↑" : "↓"}
              </span>
            </div>
          )}
        </div>
      )}

      {/* STANDBY */}
      {!isRunning && !isHold && (
        <p className="text-[12px] text-slate-400">Waiting for dispatch</p>
      )}
    </div>
  );
}
