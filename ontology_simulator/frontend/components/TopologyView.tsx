"use client";
import { useEffect, useMemo, useState } from "react";
import { MachineState } from "@/lib/types";

// ── Object-API Registry ───────────────────────────────────────────────────────
// Each entry registers the display label and optional query endpoint per type.
// New object types can be added here; layout logic auto-adapts without hardcoding.
export const OBJECT_API_REGISTRY: Record<string, {
  label: string;
  isCircle?: boolean;
  queryEndpoint?: (id: string) => string;
}> = {
  TOOL:   { label: "EQUIPMENT" },
  LOT:    { label: "WIP",    isCircle: true, queryEndpoint: id => `/api/v2/ontology/trajectory/${id}` },
  RECIPE: { label: "RECIPE", queryEndpoint: _id => `/api/v2/ontology/indices/RECIPE` },
  APC:    { label: "APC",    queryEndpoint: _id => `/api/v2/ontology/indices/APC` },
  DC:     { label: "DC",     queryEndpoint: _id => `/api/v2/ontology/indices/DC` },
  SPC:    { label: "SPC",    queryEndpoint: _id => `/api/v2/ontology/indices/SPC` },
  EC:     { label: "EC",     queryEndpoint: id => `/api/v2/ontology/equipment/${id}/constants` },
  FDC:    { label: "FDC" },
  OCAP:   { label: "OCAP" },
};

// ── 100-Color Ordered Palette (golden-angle HSL) ──────────────────────────────
// Assigned by node discovery order, NOT hardcoded per type.
// ~100 visually distinct colors optimised for dark backgrounds.
const _GA = 137.508;
const PALETTE: string[] = Array.from({ length: 100 }, (_, i) => {
  const h = (i * _GA) % 360;
  const s = 65 + (i % 3) * 10;   // 65 | 75 | 85%
  const l = 58 + (i % 4) * 4;    // 58 | 62 | 66 | 70%
  return `hsl(${h.toFixed(0)},${s}%,${l}%)`;
});

// ── Layout constants ──────────────────────────────────────────────────────────
const VW = 640, VH = 420;
const NODE_W = 148, NODE_H = 58, NODE_R = 10;
const TOOL_POS = { x: 100, y: VH / 2 };
const LOT_POS  = { x: 320, y: VH / 2 };
const LOT_R    = 46;
const RIGHT_X  = 540;

// ── Equipment display names ───────────────────────────────────────────────────
const DISPLAY_NAME: Record<string, string> = {
  "EQP-01": "ETCH-LAM-01", "EQP-02": "ETCH-LAM-02",
  "EQP-03": "ETCH-LAM-03", "EQP-04": "ETCH-LAM-04",
  "EQP-05": "PHO-ASML-01", "EQP-06": "PHO-ASML-02",
  "EQP-07": "CVD-AMAT-01", "EQP-08": "CVD-AMAT-02",
  "EQP-09": "IMP-VARIAN-01", "EQP-10": "IMP-VARIAN-02",
};

// ── Context API types ─────────────────────────────────────────────────────────
interface CtxRoot {
  lot_id: string; step: string; event_id: string; event_time: string;
  spc_status: string | null; recipe_id: string | null; apc_id: string | null; tool_id: string | null;
  in_progress?: boolean;
}
interface CtxResponse {
  root: CtxRoot;
  tool:   Record<string, unknown> | null;
  recipe: Record<string, unknown> | null;
  apc:    Record<string, unknown> | null;
  dc:     Record<string, unknown> | null;
  spc:    Record<string, unknown> | null;
  ec:     Record<string, unknown> | null;
  fdc:    Record<string, unknown> | null;
  ocap:   Record<string, unknown> | null;
}

// ── Graph types ───────────────────────────────────────────────────────────────
interface GraphNode {
  id: string; type: string; label: string; value: string;
  subtext?: string; isOOC?: boolean; isCircle?: boolean;
  pos: { x: number; y: number }; paletteIdx: number;
}
interface GraphEdge { from: string; to: string; }

// ── API base URL ──────────────────────────────────────────────────────────────
function getApiBase() {
  if (typeof window === "undefined") return "/simulator-api";
  const local = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
  return `${window.location.origin}/simulator-api`;
}

// ── Build dynamic graph from context response ─────────────────────────────────
// machineId: when provided, the EQUIPMENT display uses this ID (not ctx.root.tool_id).
// This prevents simulator data races where the same (lot_id, step) appears under
// multiple machines — the caller always knows the authoritative machine.
function buildGraph(ctx: CtxResponse, machineId?: string, machineStage?: string): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  let pi = 0; // palette index — discovery order assigns color

  const root  = ctx.root;
  const isOOC = root.spc_status === "OOC";

  // Root: TOOL (always guaranteed from event)
  const toolId    = root.tool_id ?? "UNKNOWN";
  const displayId = machineId ?? toolId;  // caller's machine.id takes precedence
  nodes.push({ id: toolId, type: "TOOL", label: "EQUIPMENT",
    value: DISPLAY_NAME[displayId] ?? displayId, pos: TOOL_POS, paletteIdx: pi++ });

  // Layer 2: LOT (circle — it has children)
  const lotId = root.lot_id;
  nodes.push({ id: lotId, type: "LOT", label: "WIP",
    value: lotId, isCircle: true, pos: LOT_POS, paletteIdx: pi++ });
  edges.push({ from: toolId, to: lotId });

  // ── Machine-side objects (EC, FDC): anchor below TOOL on the LEFT ───────────
  // EC above TOOL, FDC below TOOL — fixed positions, no zigzag
  const MACHINE_LAYOUT: Record<string, { x: number; y: number }> = {
    EC:  { x: TOOL_POS.x, y: TOOL_POS.y - 80 },
    FDC: { x: TOOL_POS.x, y: TOOL_POS.y + 80 },
  };

  const machineSide: Array<{ type: string; data: Record<string, unknown> | null; defaultId: string }> = [
    { type: "EC",  data: ctx.ec,  defaultId: `EC-${toolId}` },
    { type: "FDC", data: ctx.fdc, defaultId: `FDC-${toolId}` },
  ].filter(d => d.data !== null);

  machineSide.forEach(({ type, data, defaultId }) => {
    const reg = OBJECT_API_REGISTRY[type];
    const rawId = (data?.objectID as string) ?? defaultId;
    const value = rawId.length > 14 ? rawId.slice(0, 13) + "…" : rawId;
    let subtext: string | undefined;
    if (type === "EC") {
      const driftCount = data?.drift_count as number | undefined;
      subtext = driftCount !== undefined ? (driftCount > 0 ? `${driftCount} DRIFT` : "ALL OK") : undefined;
    } else if (type === "FDC") {
      const oocCount = data?.ooc_count as number | undefined;
      const total = (data?.uchart as unknown[])?.length;
      if (oocCount !== undefined && total !== undefined) subtext = `OOC ${oocCount}/${total}`;
    }
    const pos = MACHINE_LAYOUT[type] ?? { x: TOOL_POS.x, y: TOOL_POS.y + 80 };
    nodes.push({
      id: rawId, type, label: reg?.label ?? type, value,
      subtext, isOOC: false, isCircle: reg?.isCircle,
      pos, paletteIdx: pi++,
    });
    edges.push({ from: toolId, to: rawId });
  });

  // ── Lot-side objects: RECIPE → TOOL, others → LOT, laid out on RIGHT ─────────
  // DC / SPC / OCAP are post-process measurements — hide them while the lot is still being processed
  const isInProgress = machineStage === "STAGE_PROCESS";
  const lotSide: Array<{ type: string; data: Record<string, unknown> | null; defaultId: string; edgeFrom: string }> = [
    { type: "RECIPE", data: ctx.recipe, defaultId: root.recipe_id ?? "—", edgeFrom: toolId },
    { type: "APC",    data: ctx.apc,    defaultId: root.apc_id    ?? "—", edgeFrom: lotId  },
    { type: "DC",     data: ctx.dc,     defaultId: "DC",                  edgeFrom: lotId  },
    { type: "SPC",    data: ctx.spc,    defaultId: "SPC",                 edgeFrom: lotId  },
    { type: "OCAP",   data: ctx.ocap,   defaultId: "OCAP",                edgeFrom: lotId  },
  ].filter(d => d.data !== null && !(isInProgress && ["DC", "SPC", "OCAP"].includes(d.type)));

  const N  = lotSide.length;
  const y0 = N <= 1 ? VH / 2 : 50;
  const dy = N <= 1 ? 0 : (VH - 100) / (N - 1);

  lotSide.forEach(({ type, data, defaultId, edgeFrom }, i) => {
    const reg = OBJECT_API_REGISTRY[type];
    const rawId = (data?.objectID as string) ?? defaultId;
    const value = rawId.length > 14 ? rawId.slice(0, 13) + "…" : rawId;

    let subtext: string | undefined;
    if (type === "SPC") {
      subtext = isOOC ? "OOC" : "IN_CTRL";
    } else if (type === "APC") {
      const params = data?.parameters as Record<string, unknown> | undefined;
      const bias = params?.current_bias as number | undefined;
      if (bias !== undefined) subtext = `${bias >= 0 ? "+" : ""}${bias.toFixed(4)} nm`;
    } else if (type === "OCAP") {
      const severity = data?.severity as string | undefined;
      subtext = severity ?? undefined;
    }

    nodes.push({
      id: rawId, type, label: reg?.label ?? type, value,
      subtext, isOOC: type === "SPC" && isOOC, isCircle: reg?.isCircle,
      pos: { x: RIGHT_X, y: y0 + i * dy }, paletteIdx: pi++,
    });
    edges.push({ from: edgeFrom, to: rawId });
  });

  return { nodes, edges };
}

// ── Exported type alias (backward compat for Dashboard/ForensicHall) ──────────
export type TopoNode = string;

// ── Background style ──────────────────────────────────────────────────────────
const BG: React.CSSProperties = {
  background: "#0b1120",
  backgroundImage: "radial-gradient(#1e293b 1px, transparent 1px)",
  backgroundSize: "24px 24px",
};

// ── Component ─────────────────────────────────────────────────────────────────
export default function TopologyView({
  machine,
  activeNode,
  onNodeClick,
}: {
  machine: MachineState | null;
  activeNode?: string | null;
  onNodeClick?: (nodeId: string) => void;
}) {
  const [ctx,     setCtx]     = useState<CtxResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const lotId = machine?.lotId ?? null;
  const step  = machine?.step  ?? null;

  // Fetch context graph whenever lot+step+lastEvent changes.
  // Pass event_time so the API anchors to this specific process run,
  // not a previous cycle's ProcessEnd for the same lot+step.
  const anchor = machine?.lastEvent ?? null;
  useEffect(() => {
    if (!lotId || !step) { setCtx(null); return; }
    const params = new URLSearchParams({ lot_id: lotId, step });
    if (anchor) params.set("event_time", anchor);
    const url = `${getApiBase()}/api/v2/ontology/context?${params}`;
    setLoading(true);
    fetch(url)
      .then(r => r.ok ? r.json() : null)
      .then(d => setCtx(d ?? null))
      .catch(() => setCtx(null))
      .finally(() => setLoading(false));
  }, [lotId, step, anchor]);

  const graph = useMemo(
    () => ctx ? buildGraph(ctx, machine?.id ?? undefined, machine?.stage ?? undefined) : null,
    [ctx, machine?.id, machine?.stage]
  );

  const clickable = !!onNodeClick;

  // ── Empty state ──────────────────────────────────────────────────────────────
  if (!machine || !machine.lotId) {
    return (
      <div className="h-full flex items-center justify-center rounded-lg" style={BG}>
        <div className="text-center opacity-40">
          <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24"
            fill="none" stroke="#94a3b8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
            className="mx-auto mb-4">
            <rect width="18" height="18" x="3" y="3" rx="2"/>
            <circle cx="9" cy="9" r="2"/>
            <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>
          </svg>
          <p className="text-slate-400 text-sm">Select a machine or OOC alert</p>
          <p className="text-slate-600 text-xs mt-1">to reconstruct the scene</p>
        </div>
      </div>
    );
  }

  // ── Loading ───────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="h-full flex items-center justify-center rounded-lg" style={BG}>
        <span className="text-slate-500 text-xs animate-pulse font-mono">
          Fetching context graph…
        </span>
      </div>
    );
  }

  // ── Fallback to minimal graph (TOOL + LOT only) if context fetch failed ───────
  const nodes: GraphNode[] = graph?.nodes ?? [
    { id: machine.id, type: "TOOL", label: "EQUIPMENT",
      value: DISPLAY_NAME[machine.id] ?? machine.id, pos: TOOL_POS, paletteIdx: 0 },
    { id: machine.lotId!, type: "LOT", label: "WIP",
      value: machine.lotId!, isCircle: true, pos: LOT_POS, paletteIdx: 1 },
  ];
  const edges: GraphEdge[] = graph?.edges ?? [{ from: machine.id, to: machine.lotId! }];

  const center  = (id: string) => nodes.find(n => n.id === id)?.pos ?? { x: 0, y: 0 };
  // activeNode stores the node TYPE (e.g. "TOOL", "APC") for RightInspector compat
  const typeOf  = (id: string) => nodes.find(n => n.id === id)?.type ?? id;

  // ── SVG render ────────────────────────────────────────────────────────────────
  return (
    <div className="h-full w-full relative overflow-hidden rounded-lg" style={BG}>
      <svg viewBox={`0 0 ${VW} ${VH}`} className="w-full h-full" style={{ overflow: "visible" }}>
        <defs>
          <style>{`
            @keyframes dashMove { to { stroke-dashoffset: -60; } }
            .topo-edge        { fill:none; stroke:#334155; stroke-width:2;   stroke-dasharray:6 4; animation:dashMove 3s linear infinite; }
            .topo-edge-active { fill:none; stroke:#64748b; stroke-width:2.5; stroke-dasharray:6 4; animation:dashMove 1.8s linear infinite; }
            @keyframes pulseRed { 0%,100%{filter:drop-shadow(0 0 0px rgba(239,68,68,0))} 50%{filter:drop-shadow(0 0 10px rgba(239,68,68,0.9))} }
            .node-ooc { animation: pulseRed 2s ease-in-out infinite; }
            @keyframes lotPulse { 0%,100%{opacity:0.55} 50%{opacity:1} }
            .lot-ring { animation: lotPulse 2.5s ease-in-out infinite; }
            @keyframes objPulse { 0%,100%{opacity:0.4} 50%{opacity:0.85} }
            .obj-ring { animation: objPulse 3s ease-in-out infinite; }
          `}</style>
          <filter id="blue-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="5" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="pal-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="4" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>

        {/* Edges */}
        {edges.map(({ from, to }) => {
          const a = center(from), b = center(to);
          const active = activeNode === typeOf(from) || activeNode === typeOf(to);
          return (
            <line key={`${from}→${to}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              className={active ? "topo-edge-active" : "topo-edge"} />
          );
        })}

        {/* Nodes */}
        {nodes.map(node => {
          // Compare by type so RightInspector receives "APC" / "RECIPE" etc.
          const isActive = activeNode === node.type;
          const pal = PALETTE[node.paletteIdx] ?? PALETTE[0];

          // Circle nodes: LOT uses blue glow; EC/FDC/OCAP use palette glow
          if (node.isCircle) {
            const isLot = node.type === "LOT";
            const CR = isLot ? LOT_R : 32;
            const circleFill   = isLot ? "#1e3a8a55" : `${pal}18`;
            const circleStroke = isActive ? "#38bdf8" : (isLot ? "#3b82f6" : pal);
            const ringFill     = isLot ? "#1e3a8a22" : `${pal}12`;
            const ringStroke   = isLot ? "#1d4ed844" : `${pal}30`;
            const labelColor   = isLot ? "#60a5fa" : pal;

            return (
              <g key={node.id} onClick={() => onNodeClick?.(node.type)}
                style={{ cursor: clickable ? "pointer" : "default" }}>
                <circle cx={node.pos.x} cy={node.pos.y} r={CR + 14}
                  fill={ringFill} stroke={ringStroke} strokeWidth={1}
                  className={isLot ? "lot-ring" : "obj-ring"}/>
                {isActive && (
                  <circle cx={node.pos.x} cy={node.pos.y} r={CR + 7}
                    fill="none" stroke="#38bdf8" strokeWidth={2} opacity={0.7}/>
                )}
                <circle cx={node.pos.x} cy={node.pos.y} r={CR}
                  fill={circleFill} stroke={circleStroke}
                  strokeWidth={isActive ? 3 : 2.5}
                  filter={isLot ? "url(#blue-glow)" : "url(#pal-glow)"}/>
                <text x={node.pos.x} y={node.pos.y - (node.subtext ? 12 : 6)} textAnchor="middle"
                  fill={labelColor} fontSize={9} fontWeight={700}
                  fontFamily="Inter,system-ui" letterSpacing="0.12em">
                  {node.label}
                </text>
                <text x={node.pos.x} y={node.pos.y + (node.subtext ? 5 : 9)} textAnchor="middle"
                  fill="#ffffff" fontSize={isLot ? 12 : 10} fontWeight={700}
                  fontFamily="'JetBrains Mono',monospace">
                  {node.value.length > 10 ? node.value.slice(0, 9) + "…" : node.value}
                </text>
                {node.subtext && (
                  <text x={node.pos.x} y={node.pos.y + 18} textAnchor="middle"
                    fill={node.isOOC ? "#ef4444" : pal}
                    fontSize={8} fontWeight={500} fontFamily="'JetBrains Mono',monospace">
                    {node.subtext}
                  </text>
                )}
              </g>
            );
          }

          // Rect node: fill/stroke/label derived from palette (or red for OOC)
          const rectFill  = node.isOOC ? "#450a0a55" : "#1e293b";
          const stroke    = node.isOOC ? "#ef4444" : pal;
          const labelFill = node.isOOC ? "#fca5a5" : pal;
          const valueFill = node.isOOC ? "#fee2e2" : "#f1f5f9";
          const rx = node.pos.x - NODE_W / 2;
          const ry = node.pos.y - NODE_H / 2;

          const glowColor = node.isOOC ? "#ef4444" : pal;
          return (
            <g key={node.id} onClick={() => onNodeClick?.(node.type)}
              style={{
                cursor: clickable ? "pointer" : "default",
                filter: `drop-shadow(0 0 6px ${glowColor}70)`,
              }}
              className={node.isOOC ? "node-ooc" : ""}>
              {isActive && (
                <rect x={rx - 5} y={ry - 5} width={NODE_W + 10} height={NODE_H + 10} rx={NODE_R + 3}
                  fill="none" stroke="#38bdf8" strokeWidth={2} opacity={0.6}/>
              )}
              <rect x={rx} y={ry} width={NODE_W} height={NODE_H} rx={NODE_R}
                fill={rectFill} stroke={isActive ? "#38bdf8" : stroke}
                strokeWidth={isActive ? 2.5 : 1.5}/>
              <text x={node.pos.x} y={ry + 17} textAnchor="middle" fill={labelFill}
                fontSize={9} fontWeight={700} fontFamily="Inter,system-ui" letterSpacing="0.12em">
                {node.label}
              </text>
              <text x={node.pos.x} y={ry + (node.subtext ? 33 : 37)} textAnchor="middle" fill={valueFill}
                fontSize={11} fontWeight={600} fontFamily="'JetBrains Mono',monospace">
                {node.value}
              </text>
              {node.subtext && (
                <text x={node.pos.x} y={ry + 47} textAnchor="middle"
                  fill={node.isOOC ? "#ef4444" : pal}
                  fontSize={9} fontWeight={500} fontFamily="'JetBrains Mono',monospace">
                  {node.subtext}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* Footer status line */}
      <div className="absolute bottom-2 left-0 right-0 text-center pointer-events-none">
        <span className="text-[10px] font-mono text-slate-600">
          {machine.lotId
            ? `${DISPLAY_NAME[machine.id] ?? machine.id} · ${machine.lotId} · ${machine.step ?? ""}`
            : `${DISPLAY_NAME[machine.id] ?? machine.id} · Idle`}
        </span>
        {!ctx && !loading && machine.lotId && (
          <span className="ml-2 text-[10px] font-mono text-amber-700">· fallback</span>
        )}
      </div>
    </div>
  );
}
