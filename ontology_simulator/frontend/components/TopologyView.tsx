"use client";
import { MachineState } from "@/lib/types";

export type TopoNode = "LOT" | "TOOL" | "RECIPE" | "APC" | "DC" | "SPC";

const DISPLAY_NAME: Record<string, string> = {
  "EQP-01": "ETCH-LAM-01", "EQP-02": "ETCH-LAM-02",
  "EQP-03": "ETCH-LAM-03", "EQP-04": "ETCH-LAM-04",
  "EQP-05": "PHO-ASML-01", "EQP-06": "PHO-ASML-02",
  "EQP-07": "CVD-AMAT-01", "EQP-08": "CVD-AMAT-02",
  "EQP-09": "IMP-VARIAN-01","EQP-10": "IMP-VARIAN-02",
};

// Positions for rect nodes (center x, y)
const RECT_POSITIONS = {
  TOOL:   { x: 100, y: 100 },
  RECIPE: { x: 540, y: 100 },
  APC:    { x: 540, y: 210 },
  DC:     { x: 540, y: 320 },
  SPC:    { x: 100, y: 320 },
} as const;

// LOT is a circle at center
const LOT_POS = { x: 320, y: 210 };
const LOT_R   = 42;

const NODE_W = 130, NODE_H = 54;

const NODE_STYLE: Record<TopoNode, { bg: string; border: string; label: string; labelColor: string }> = {
  TOOL:   { bg: "#F8FAFC", border: "#94A3B8", label: "EQUIPMENT",  labelColor: "#64748B" },
  LOT:    { bg: "#EFF6FF", border: "#3B82F6", label: "WIP",        labelColor: "#2563EB" },
  RECIPE: { bg: "#F0FDF4", border: "#22C55E", label: "RECIPE",     labelColor: "#16A34A" },
  APC:    { bg: "#F0F9FF", border: "#0EA5E9", label: "APC",        labelColor: "#0284C7" },
  DC:     { bg: "#EEF2FF", border: "#818CF8", label: "DC",         labelColor: "#4F46E5" },
  SPC:    { bg: "#FFFBEB", border: "#F59E0B", label: "SPC",        labelColor: "#D97706" },
};

const EDGES: [TopoNode, TopoNode][] = [
  ["TOOL",   "LOT"],
  ["LOT",    "RECIPE"],
  ["LOT",    "APC"],
  ["LOT",    "DC"],
  ["LOT",    "SPC"],
];

function getCenter(node: TopoNode): { x: number; y: number } {
  if (node === "LOT") return LOT_POS;
  return RECT_POSITIONS[node as keyof typeof RECT_POSITIONS];
}

function nodeValue(type: TopoNode, machine: MachineState): string {
  switch (type) {
    case "TOOL":   return DISPLAY_NAME[machine.id] ?? machine.id;
    case "LOT":    return machine.lotId   ?? "NO WAFER";
    case "RECIPE": return machine.recipe  ?? "—";
    case "APC":    return machine.apcId   ?? "—";
    case "DC":     return machine.lotId ? `DC-${machine.lotId.slice(-4)}-${(machine.step ?? "").slice(-3)}` : "—";
    case "SPC":    return machine.lotId ? `SPC-${machine.lotId.slice(-4)}` : "SPC CHARTS";
  }
}

function nodeSub(type: TopoNode, machine: MachineState): string | null {
  if (type === "APC" && machine.bias !== null) {
    const sign = machine.bias >= 0 ? "+" : "";
    return `${sign}${machine.bias.toFixed(4)} nm Bias`;
  }
  return null;
}

export default function TopologyView({
  machine,
  activeNode,
  onNodeClick,
}: {
  machine: MachineState | null;
  activeNode?: TopoNode | null;
  onNodeClick?: (node: TopoNode) => void;
}) {
  if (!machine) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <p className="text-slate-400 text-sm">Select a machine from the left panel</p>
          <p className="text-slate-300 text-xs mt-1">to view its process topology</p>
        </div>
      </div>
    );
  }

  const clickable = !!onNodeClick;

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 flex items-center justify-center p-4">
        <svg
          viewBox="0 0 640 420"
          className="w-full max-w-[620px]"
          style={{ overflow: "visible" }}
        >
          {/* Connecting lines */}
          {EDGES.map(([from, to]) => {
            const a = getCenter(from);
            const b = getCenter(to);
            const isActiveLine = activeNode === from || activeNode === to;
            return (
              <line
                key={`${from}-${to}`}
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={isActiveLine ? "#94a3b8" : "#e2e8f0"}
                strokeWidth={isActiveLine ? 2.5 : 2}
              />
            );
          })}

          {/* Rect nodes (TOOL, RECIPE, APC, DC, SPC) */}
          {(Object.keys(RECT_POSITIONS) as (keyof typeof RECT_POSITIONS)[]).map(type => {
            const pos    = RECT_POSITIONS[type];
            const style  = NODE_STYLE[type];
            const value  = nodeValue(type, machine);
            const sub    = nodeSub(type, machine);
            const isActive = activeNode === type;
            const x = pos.x - NODE_W / 2;
            const y = pos.y - NODE_H / 2;

            return (
              <g
                key={type}
                onClick={() => onNodeClick?.(type)}
                style={{ cursor: clickable ? "pointer" : "default" }}
              >
                {isActive && (
                  <rect
                    x={x - 4} y={y - 4}
                    width={NODE_W + 8} height={NODE_H + 8}
                    rx={10} fill="none"
                    stroke={style.border} strokeWidth={2.5} opacity={0.5}
                  />
                )}
                <rect
                  x={x} y={y} width={NODE_W} height={NODE_H} rx={7}
                  fill={style.bg}
                  stroke={style.border}
                  strokeWidth={isActive ? 2.5 : 1.5}
                />
                <text
                  x={pos.x} y={y + 16}
                  textAnchor="middle"
                  fill={style.labelColor}
                  fontSize={9} fontWeight={700}
                  fontFamily="Inter, system-ui"
                  letterSpacing="0.1em"
                >
                  {style.label}
                </text>
                <text
                  x={pos.x} y={y + (sub ? 31 : 34)}
                  textAnchor="middle"
                  fill="#1E293B"
                  fontSize={11} fontWeight={500}
                  fontFamily="'JetBrains Mono', 'Courier New', monospace"
                >
                  {value.length > 13 ? value.slice(0, 12) + "…" : value}
                </text>
                {sub && (
                  <text
                    x={pos.x} y={y + 44}
                    textAnchor="middle"
                    fill={machine.biasAlert ? "#D97706" : "#0284C7"}
                    fontSize={9.5} fontWeight={500}
                    fontFamily="'JetBrains Mono', 'Courier New', monospace"
                  >
                    {sub}
                  </text>
                )}
              </g>
            );
          })}

          {/* LOT node — circle */}
          {(() => {
            const style    = NODE_STYLE["LOT"];
            const value    = nodeValue("LOT", machine);
            const isActive = activeNode === "LOT";
            return (
              <g
                onClick={() => onNodeClick?.("LOT")}
                style={{ cursor: clickable ? "pointer" : "default" }}
              >
                {isActive && (
                  <circle
                    cx={LOT_POS.x} cy={LOT_POS.y} r={LOT_R + 6}
                    fill="none"
                    stroke={style.border} strokeWidth={2.5} opacity={0.45}
                  />
                )}
                <circle
                  cx={LOT_POS.x} cy={LOT_POS.y} r={LOT_R}
                  fill={style.bg}
                  stroke={style.border}
                  strokeWidth={isActive ? 2.5 : 2}
                />
                <text
                  x={LOT_POS.x} y={LOT_POS.y - 10}
                  textAnchor="middle"
                  fill={style.labelColor}
                  fontSize={9} fontWeight={700}
                  fontFamily="Inter, system-ui"
                  letterSpacing="0.1em"
                >
                  {style.label}
                </text>
                <text
                  x={LOT_POS.x} y={LOT_POS.y + 8}
                  textAnchor="middle"
                  fill="#1E293B"
                  fontSize={11} fontWeight={600}
                  fontFamily="'JetBrains Mono', 'Courier New', monospace"
                >
                  {value.length > 10 ? value.slice(0, 9) + "…" : value}
                </text>
              </g>
            );
          })()}
        </svg>
      </div>

      {onNodeClick && (
        <p className="text-[10px] text-slate-400 text-center pb-1">
          Click a node to inspect its state
        </p>
      )}
      <p className="text-xs text-slate-400 text-center pb-3">
        {machine.lotId
          ? `${DISPLAY_NAME[machine.id] ?? machine.id} · ${machine.lotId} · ${machine.step ?? ""}`
          : `${DISPLAY_NAME[machine.id] ?? machine.id} · Idle`}
      </p>
    </div>
  );
}
