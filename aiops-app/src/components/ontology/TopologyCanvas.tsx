"use client";

/**
 * @deprecated Replaced by `topology-v2/TopologyWorkbench`. The new workbench
 * uses 28-day windowed RUNS aggregation + multi-lane trace + 9 view kinds +
 * fullscreen, instead of single-snapshot React Flow + Dagre. Kept around for
 * one release as fallback; remove after no callers reference it.
 */

import { useState, useMemo, useCallback } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeTypes,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Dagre from "@dagrejs/dagre";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ParamLabel { name: string; unit: string; group: string; }

export interface TopologySnapshot {
  lot_id:    string;
  step:      string;
  eventTime: string;
  tool:   { equipment_id: string; name: string; status: string } | null;
  dc:     { parameters: Record<string, number>; labels?: Record<string, ParamLabel>; toolID?: string; lotID?: string } | null;
  spc:    { charts: Record<string, { value: number; ucl: number; lcl: number }>; spc_status: string; chart_labels?: Record<string, { name: string; sensor: string }>; toolID?: string } | null;
  apc:    { parameters: Record<string, number>; labels?: Record<string, ParamLabel>; objectID?: string } | null;
  recipe: { objectID?: string; parameters?: Record<string, unknown>; labels?: Record<string, ParamLabel> } | null;
  ec:     {
    pm_count: number; wafers_since_pm: number; chamber_age_hrs: number;
    seasoning_status: string; last_pm_time?: string;
    component_health: Record<string, number>;
    health_labels?: Record<string, { name: string }>;
  } | null;
  fdc:    {
    fault_class: string; fault_code: string; confidence: number;
    severity: string; triggered_sensors: string[];
    model_version?: string; fault_description?: string;
  } | null;
  ocap:   {
    triggered_by: string; priority: string; action_code: string;
    description: string; auto_hold: boolean; status: string;
    triggered_sensors?: string[];
  } | null;
}

export type CenterType = "LOT" | "TOOL" | "RECIPE" | "APC";

interface Props {
  snapshot:    TopologySnapshot | null;
  centerType?: CenterType;
  centerId?:   string;
  loading?:    boolean;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

type NodeId = "LOT" | "TOOL" | "RECIPE" | "APC" | "DC" | "SPC" | "EC" | "FDC" | "OCAP";

const TOOL_BOUND = new Set<NodeId>(["RECIPE", "EC", "FDC"]);
const LOT_BOUND  = new Set<NodeId>(["APC", "DC", "SPC", "OCAP"]);

const NODE_COLORS: Record<string, string> = {
  LOT:       "#2b6cb0",
  TOOL:      "#e53e3e",
  RECIPE:    "#2c7a7b",
  APC:       "#b83280",
  DC:        "#276749",
  SPC_PASS:  "#276749",
  SPC_OOC:   "#c53030",
  EC:        "#744210",
  FDC_NORM:  "#276749",
  FDC_WARN:  "#d69e2e",
  FDC_FAULT: "#c53030",
  OCAP_P1:   "#c53030",
  OCAP_P2:   "#d69e2e",
  OCAP_NONE: "#a0aec0",
};

const NODE_W      = 168;
const NODE_H      = 60;
const CENTER_SIZE = 108; // circle diameter

// ---------------------------------------------------------------------------
// Node data type
// ---------------------------------------------------------------------------

type FlowNodeData = {
  nodeId:      NodeId;
  label:       string;
  subtitle:    string;
  step?:       string;
  accentColor: string;
  isCenter:    boolean;
  dimmed:      boolean;
  isSelected:  boolean;
};

// ---------------------------------------------------------------------------
// Custom React Flow nodes
// ---------------------------------------------------------------------------

function CenterNodeComp({ data }: NodeProps) {
  const d = data as FlowNodeData;
  return (
    <>
      <Handle type="target" position={Position.Left}  isConnectable={false} style={{ opacity: 0, width: 1, height: 1 }} />
      <Handle type="source" position={Position.Right} isConnectable={false} style={{ opacity: 0, width: 1, height: 1 }} />
      <div style={{
        width: CENTER_SIZE, height: CENTER_SIZE, borderRadius: "50%",
        background: "#ebf4ff",
        border: `2.5px solid ${d.accentColor}`,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        boxShadow: d.isSelected ? `0 0 0 4px ${d.accentColor}30, 0 2px 10px #0000001a` : "0 2px 8px #0000001a",
        cursor: "pointer",
      }}>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: 1.5, color: d.accentColor, textTransform: "uppercase", marginBottom: 2 }}>
          {d.label}
        </div>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#1a202c", fontFamily: "monospace", maxWidth: 90, textAlign: "center", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {d.subtitle}
        </div>
        {d.step && (
          <div style={{ fontSize: 10, color: "#718096", fontFamily: "monospace", marginTop: 2 }}>{d.step}</div>
        )}
      </div>
    </>
  );
}

function CardNodeComp({ data }: NodeProps) {
  const d = data as FlowNodeData;
  return (
    <>
      <Handle type="target" position={Position.Left}  isConnectable={false} style={{ opacity: 0, width: 1, height: 1 }} />
      <Handle type="source" position={Position.Right} isConnectable={false} style={{ opacity: 0, width: 1, height: 1 }} />
      <div style={{
        width: NODE_W, height: NODE_H,
        background: d.dimmed ? "#f7f8fc" : "#ffffff",
        border: `1px solid ${d.isSelected ? d.accentColor : "#e2e8f0"}`,
        borderRadius: 8,
        boxShadow: d.isSelected ? `0 0 0 2px ${d.accentColor}40, 0 2px 6px #0000001a` : "0 1px 4px #0000001a",
        display: "flex", alignItems: "stretch",
        cursor: "pointer",
        opacity: d.dimmed ? 0.45 : 1,
      }}>
        <div style={{ width: 4, background: d.accentColor, borderRadius: "8px 0 0 8px", flexShrink: 0 }} />
        <div style={{ padding: "0 12px", display: "flex", flexDirection: "column", justifyContent: "center", flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", color: d.accentColor, marginBottom: 2 }}>
            {d.label}
          </div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#1a202c", fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {d.subtitle}
          </div>
        </div>
      </div>
    </>
  );
}

const NODE_TYPES: NodeTypes = {
  centerNode: CenterNodeComp,
  cardNode:   CardNodeComp,
};

// ---------------------------------------------------------------------------
// Graph builder
// ---------------------------------------------------------------------------

function buildGraph(
  snapshot: TopologySnapshot,
  centerType: CenterType,
  selectedId: NodeId | null,
): { nodes: Node<FlowNodeData>[]; edges: Edge[] } {
  const spcStatus  = snapshot.spc?.spc_status ?? "";
  const fdcClass   = snapshot.fdc?.fault_class ?? "Normal";
  const ocapExists = snapshot.ocap != null;

  function accentColor(id: NodeId): string {
    switch (id) {
      case "SPC":  return spcStatus === "OOC"    ? NODE_COLORS.SPC_OOC   : NODE_COLORS.SPC_PASS;
      case "FDC":  return fdcClass  === "Fault"  ? NODE_COLORS.FDC_FAULT
                       : fdcClass  === "Warning" ? NODE_COLORS.FDC_WARN  : NODE_COLORS.FDC_NORM;
      case "OCAP": return !ocapExists            ? NODE_COLORS.OCAP_NONE
                       : snapshot.ocap?.priority === "P1" ? NODE_COLORS.OCAP_P1 : NODE_COLORS.OCAP_P2;
      default:     return NODE_COLORS[id] ?? "#718096";
    }
  }

  function subtitle(id: NodeId): string {
    switch (id) {
      case "LOT":    return snapshot.lot_id;
      case "TOOL":   return snapshot.tool?.equipment_id ?? snapshot.dc?.toolID ?? "—";
      case "RECIPE": return snapshot.recipe?.objectID?.slice(0, 14) ?? "—";
      case "APC":    return snapshot.apc?.objectID?.slice(0, 14) ?? "—";
      case "DC":     return `${Object.keys(snapshot.dc?.parameters ?? {}).length} sensors`;
      case "SPC":    return spcStatus || "—";
      case "EC":     return snapshot.ec?.seasoning_status ?? "—";
      case "FDC":    return fdcClass;
      case "OCAP":   return snapshot.ocap ? `${snapshot.ocap.priority} · ${snapshot.ocap.action_code}` : "未觸發";
    }
  }

  const ALL_IDS: NodeId[] = ["LOT", "TOOL", "RECIPE", "APC", "DC", "SPC", "EC", "FDC", "OCAP"];

  const nodes: Node<FlowNodeData>[] = ALL_IDS.map((id) => {
    const isCenter = id === centerType;
    return {
      id,
      type:     isCenter ? "centerNode" : "cardNode",
      position: { x: 0, y: 0 },         // Dagre will set real positions
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      data: {
        nodeId:      id,
        label:       id,
        subtitle:    isCenter ? (centerType === "LOT" ? snapshot.lot_id : snapshot.tool?.equipment_id ?? "—") : subtitle(id),
        step:        isCenter ? snapshot.step : undefined,
        accentColor: accentColor(id),
        isCenter,
        dimmed:      id === "OCAP" && !ocapExists,
        isSelected:  id === selectedId,
      },
    };
  });

  // Edge palette
  const TRUNK_STYLE  = { stroke: "#94a3b8", strokeWidth: 2.5 };
  const TOOL_STYLE   = { stroke: "#e53e3e60", strokeWidth: 1.5 };
  const LOT_STYLE    = { stroke: "#2b6cb060", strokeWidth: 1.5 };

  const edges: Edge[] = [
    // Main trunk
    { id: "trunk", source: "LOT", target: "TOOL", type: "smoothstep", style: TRUNK_STYLE },
    // Tool-bound
    ...Array.from(TOOL_BOUND).map((id) => ({
      id: `tool-${id}`, source: "TOOL", target: id, type: "smoothstep", style: TOOL_STYLE,
    })),
    // Lot-bound — reversed so Dagre places these nodes LEFT of LOT, making LOT the true center
    ...Array.from(LOT_BOUND).map((id) => ({
      id: `lot-${id}`, source: id, target: "LOT", type: "smoothstep", style: LOT_STYLE,
    })),
  ];

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Dagre auto-layout
// ---------------------------------------------------------------------------

function applyDagre(nodes: Node<FlowNodeData>[], edges: Edge[]): Node<FlowNodeData>[] {
  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 70, ranksep: 140, marginx: 30, marginy: 30 });

  nodes.forEach((n) => {
    const w = n.data.isCenter ? CENTER_SIZE : NODE_W;
    const h = n.data.isCenter ? CENTER_SIZE : NODE_H;
    g.setNode(n.id, { width: w, height: h });
  });
  edges.forEach((e) => g.setEdge(e.source, e.target));

  Dagre.layout(g);

  return nodes.map((n) => {
    const w = n.data.isCenter ? CENTER_SIZE : NODE_W;
    const h = n.data.isCenter ? CENTER_SIZE : NODE_H;
    const { x, y } = g.node(n.id);
    return { ...n, position: { x: x - w / 2, y: y - h / 2 } };
  });
}

// ---------------------------------------------------------------------------
// Detail panel helpers
// ---------------------------------------------------------------------------

interface GroupedEntry { key: string; value: unknown; name: string; unit: string; group: string; }

function buildGroups(
  params: Record<string, unknown>,
  labels?: Record<string, ParamLabel>,
): Record<string, GroupedEntry[]> {
  const result: Record<string, GroupedEntry[]> = {};
  for (const [key, value] of Object.entries(params)) {
    const lbl   = labels?.[key];
    const group = lbl?.group ?? "Other";
    const name  = lbl?.name  ?? key;
    const unit  = lbl?.unit  ?? "";
    if (!result[group]) result[group] = [];
    result[group].push({ key, value, name, unit, group });
  }
  return result;
}

function DetailRow({ label, value, badge }: { label: string; value: string; badge?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "5px 0", borderBottom: "1px solid #f7f8fc", fontSize: 12 }}>
      <span style={{ color: "#718096" }}>{label}</span>
      {badge
        ? <span style={{ padding: "1px 8px", borderRadius: 8, fontSize: 10, fontWeight: 700, background: "#f0fff4", color: "#276749", border: "1px solid #c6f6d5" }}>{value}</span>
        : <span style={{ color: "#1a202c", fontFamily: "monospace", fontWeight: 600 }}>{value}</span>}
    </div>
  );
}

function GroupSection({ group, entries, accent }: { group: string; entries: GroupedEntry[]; accent: string }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", color: accent, borderBottom: `1px solid ${accent}30`, paddingBottom: 3, marginBottom: 4 }}>
        {group}
      </div>
      {entries.map(({ key, value, name, unit }) => (
        <div key={key} style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "3px 0", borderBottom: "1px solid #f7f8fc", fontSize: 11 }}>
          <span style={{ color: "#4a5568", flex: 1, marginRight: 8 }}>
            {name}{unit && <span style={{ color: "#a0aec0", marginLeft: 4 }}>{unit}</span>}
          </span>
          <span style={{ color: "#1a202c", fontFamily: "monospace", fontWeight: 600, flexShrink: 0 }}>
            {typeof value === "number" ? value.toFixed(3) : String(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function EmptyMsg({ children }: { children: React.ReactNode }) {
  return <div style={{ color: "#a0aec0", fontSize: 12, padding: "8px 0" }}>{children}</div>;
}

function DcDetail({ dc }: { dc: TopologySnapshot["dc"] }) {
  if (!dc) return <EmptyMsg>無 DC 資料</EmptyMsg>;
  const groups = buildGroups(dc.parameters ?? {}, dc.labels);
  return (
    <div style={{ maxHeight: 360, overflowY: "auto" }}>
      {Object.entries(groups).map(([g, entries]) => (
        <GroupSection key={g} group={g} entries={entries} accent={NODE_COLORS.DC} />
      ))}
    </div>
  );
}

function SpcDetail({ spc }: { spc: TopologySnapshot["spc"] }) {
  if (!spc) return <EmptyMsg>無 SPC 資料</EmptyMsg>;
  const chartLabels = spc.chart_labels ?? {};
  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
        <span style={{ fontSize: 12, color: "#718096" }}>總體狀態</span>
        <span style={{ padding: "2px 10px", borderRadius: 10, fontSize: 11, fontWeight: 700,
          background: spc.spc_status === "OOC" ? "#fff5f5" : "#f0fff4",
          color:      spc.spc_status === "OOC" ? "#c53030"  : "#276749",
          border:     `1px solid ${spc.spc_status === "OOC" ? "#fed7d7" : "#c6f6d5"}` }}>
          {spc.spc_status}
        </span>
      </div>
      {Object.entries(spc.charts ?? {}).map(([chartKey, c]) => {
        const ooc  = c.value > c.ucl || c.value < c.lcl;
        const pct  = Math.min(100, Math.max(0, ((c.value - c.lcl) / ((c.ucl - c.lcl) || 1)) * 100));
        const meta = chartLabels[chartKey];
        return (
          <div key={chartKey} style={{ marginBottom: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 3 }}>
              <div>
                <span style={{ color: "#4a5568", fontWeight: 600 }}>{meta?.name ?? chartKey}</span>
                <span style={{ color: "#a0aec0", fontSize: 9, marginLeft: 6, fontFamily: "monospace", textTransform: "uppercase" }}>{chartKey}</span>
              </div>
              <span style={{ color: ooc ? "#c53030" : "#276749", fontWeight: 600, fontFamily: "monospace" }}>
                {ooc ? "OOC" : "PASS"} ({c.value.toFixed(2)})
              </span>
            </div>
            <div style={{ position: "relative", height: 8, background: "#e2e8f0", borderRadius: 4 }}>
              <div style={{ position: "absolute", left: "10%", right: "10%", top: 1, bottom: 1, background: "#c6f6d5", borderRadius: 3 }} />
              <div style={{ position: "absolute", left: `${pct}%`, top: 0, width: 4, height: "100%", background: ooc ? "#c53030" : "#276749", borderRadius: 2, transform: "translateX(-50%)" }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#a0aec0", marginTop: 1 }}>
              <span>LCL {c.lcl}</span><span>UCL {c.ucl}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ApcDetail({ apc }: { apc: TopologySnapshot["apc"] }) {
  if (!apc) return <EmptyMsg>無 APC 資料</EmptyMsg>;
  const groups = buildGroups(apc.parameters ?? {}, apc.labels);
  return (
    <div>
      {apc.objectID && <div style={{ fontSize: 11, color: "#b83280", fontFamily: "monospace", marginBottom: 10 }}>{apc.objectID}</div>}
      <div style={{ maxHeight: 320, overflowY: "auto" }}>
        {Object.entries(groups).map(([g, entries]) => (
          <GroupSection key={g} group={g} entries={entries} accent={NODE_COLORS.APC} />
        ))}
      </div>
    </div>
  );
}

function RecipeDetail({ recipe }: { recipe: TopologySnapshot["recipe"] }) {
  if (!recipe) return <EmptyMsg>無 Recipe 資料</EmptyMsg>;
  const groups = buildGroups(recipe.parameters ?? {}, recipe.labels);
  return (
    <div>
      {recipe.objectID && <div style={{ fontSize: 11, color: "#2c7a7b", fontFamily: "monospace", marginBottom: 10 }}>{recipe.objectID}</div>}
      <div style={{ maxHeight: 320, overflowY: "auto" }}>
        {Object.entries(groups).map(([g, entries]) => (
          <GroupSection key={g} group={g} entries={entries} accent={NODE_COLORS.RECIPE} />
        ))}
      </div>
    </div>
  );
}

function ToolDetail({ tool }: { tool: TopologySnapshot["tool"] }) {
  if (!tool) return <EmptyMsg>無設備資料</EmptyMsg>;
  return (
    <div>
      <DetailRow label="ID"   value={tool.equipment_id} />
      <DetailRow label="名稱" value={tool.name} />
      <DetailRow label="狀態" value={tool.status} badge />
    </div>
  );
}

function EcDetail({ ec }: { ec: TopologySnapshot["ec"] }) {
  if (!ec) return <EmptyMsg>無 EC 資料</EmptyMsg>;
  const seasonColor = ec.seasoning_status === "Aging" ? "#c53030" : ec.seasoning_status === "Fresh" ? "#2b6cb0" : "#276749";
  const accent = NODE_COLORS.EC;
  return (
    <div>
      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", color: accent, borderBottom: `1px solid ${accent}30`, paddingBottom: 3, marginBottom: 6 }}>
          Maintenance
        </div>
        <DetailRow label="PM 次數"         value={String(ec.pm_count)} />
        <DetailRow label="Wafers Since PM" value={String(ec.wafers_since_pm)} />
        <DetailRow label="腔體使用時數"     value={`${ec.chamber_age_hrs} hrs`} />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderBottom: "1px solid #f0f0f0", fontSize: 12 }}>
          <span style={{ color: "#718096" }}>腔體狀態</span>
          <span style={{ padding: "1px 8px", borderRadius: 8, fontSize: 10, fontWeight: 700,
            background: `${seasonColor}15`, color: seasonColor, border: `1px solid ${seasonColor}40` }}>
            {ec.seasoning_status}
          </span>
        </div>
      </div>
      <div>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", color: accent, borderBottom: `1px solid ${accent}30`, paddingBottom: 3, marginBottom: 6 }}>
          Component Health
        </div>
        {Object.entries(ec.component_health ?? {}).map(([key, score]) => {
          const label  = ec.health_labels?.[key]?.name ?? key;
          const pct    = Math.round(score * 100);
          const color  = pct >= 90 ? "#276749" : pct >= 75 ? "#d69e2e" : "#c53030";
          return (
            <div key={key} style={{ marginBottom: 6 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 2 }}>
                <span style={{ color: "#4a5568" }}>{label}</span>
                <span style={{ color, fontWeight: 700, fontFamily: "monospace" }}>{pct}%</span>
              </div>
              <div style={{ height: 5, background: "#e2e8f0", borderRadius: 3, overflow: "hidden" }}>
                <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3 }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FdcDetail({ fdc }: { fdc: TopologySnapshot["fdc"] }) {
  if (!fdc) return <EmptyMsg>無 FDC 資料</EmptyMsg>;
  const classColor = fdc.fault_class === "Fault" ? "#c53030" : fdc.fault_class === "Warning" ? "#d69e2e" : "#276749";
  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
        <span style={{ padding: "2px 10px", borderRadius: 10, fontSize: 11, fontWeight: 700,
          background: `${classColor}15`, color: classColor, border: `1px solid ${classColor}40` }}>
          {fdc.fault_class}
        </span>
        <span style={{ padding: "2px 10px", borderRadius: 10, fontSize: 10, fontWeight: 600,
          background: "#f7f8fc", color: "#718096", border: "1px solid #e2e8f0" }}>
          {fdc.fault_code}
        </span>
      </div>
      {fdc.fault_description && (
        <div style={{ fontSize: 12, color: "#4a5568", marginBottom: 12, padding: "8px 10px", background: `${classColor}08`, borderRadius: 6, borderLeft: `3px solid ${classColor}` }}>
          {fdc.fault_description}
        </div>
      )}
      <DetailRow label="信心值"     value={`${Math.round(fdc.confidence * 100)}%`} />
      <DetailRow label="嚴重程度"   value={fdc.severity} badge />
      <DetailRow label="Model Ver." value={fdc.model_version ?? "—"} />
      {fdc.triggered_sensors.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: "#a0aec0", textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 }}>觸發感測器</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {fdc.triggered_sensors.map((s) => (
              <span key={s} style={{ fontFamily: "monospace", fontSize: 10, padding: "1px 7px", background: "#fff5f5", color: "#c53030", border: "1px solid #fed7d7", borderRadius: 8 }}>
                {s}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function OcapDetail({ ocap }: { ocap: TopologySnapshot["ocap"] }) {
  if (!ocap) return <EmptyMsg>本次事件未觸發 OCAP</EmptyMsg>;
  const priColor = ocap.priority === "P1" ? "#c53030" : "#d69e2e";
  const statusColor: Record<string, string> = { Open: "#c53030", InProgress: "#d69e2e", Closed: "#276749" };
  const sColor = statusColor[ocap.status] ?? "#718096";
  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
        <span style={{ padding: "2px 8px", borderRadius: 8, fontSize: 11, fontWeight: 700,
          background: `${priColor}15`, color: priColor, border: `1px solid ${priColor}40` }}>
          {ocap.priority}
        </span>
        <span style={{ padding: "2px 8px", borderRadius: 8, fontSize: 10, fontWeight: 600,
          background: `${sColor}15`, color: sColor, border: `1px solid ${sColor}40` }}>
          {ocap.status}
        </span>
        {ocap.auto_hold && (
          <span style={{ padding: "2px 8px", borderRadius: 8, fontSize: 10, fontWeight: 600,
            background: "#fff5f5", color: "#c53030", border: "1px solid #fed7d7" }}>
            Auto Hold
          </span>
        )}
      </div>
      <div style={{ fontSize: 11, fontFamily: "monospace", color: "#2b6cb0", marginBottom: 8 }}>{ocap.action_code}</div>
      <div style={{ fontSize: 12, color: "#4a5568", marginBottom: 10, lineHeight: 1.6 }}>{ocap.description}</div>
      <DetailRow label="觸發來源" value={ocap.triggered_by.toUpperCase()} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function TopologyCanvas({ snapshot, centerType = "LOT", centerId, loading }: Props) {
  const [selectedNodeId, setSelectedNodeId] = useState<NodeId | null>(null);

  const { nodes, edges } = useMemo(() => {
    if (!snapshot) return { nodes: [], edges: [] };
    const { nodes: raw, edges } = buildGraph(snapshot, centerType, selectedNodeId);
    return { nodes: applyDagre(raw, edges), edges };
  }, [snapshot, centerType, selectedNodeId]);

  const handleNodeClick = useCallback((_evt: React.MouseEvent, node: Node) => {
    setSelectedNodeId((prev) => (prev === node.id ? null : node.id as NodeId));
  }, []);

  // Detail panel content
  function renderDetail() {
    if (!snapshot || !selectedNodeId) return null;
    switch (selectedNodeId) {
      case "TOOL":   return <ToolDetail   tool={snapshot.tool} />;
      case "LOT":    return <div><DetailRow label="Lot ID" value={snapshot.lot_id} /><DetailRow label="Step" value={snapshot.step} /></div>;
      case "DC":     return <DcDetail     dc={snapshot.dc} />;
      case "SPC":    return <SpcDetail    spc={snapshot.spc} />;
      case "APC":    return <ApcDetail    apc={snapshot.apc} />;
      case "RECIPE": return <RecipeDetail recipe={snapshot.recipe} />;
      case "EC":     return <EcDetail     ec={snapshot.ec} />;
      case "FDC":    return <FdcDetail    fdc={snapshot.fdc} />;
      case "OCAP":   return <OcapDetail   ocap={snapshot.ocap} />;
    }
  }

  const accentForSelected = selectedNodeId ? (NODE_COLORS[selectedNodeId] ?? NODE_COLORS[`${selectedNodeId}_PASS`] ?? "#2b6cb0") : "#2b6cb0";

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0, background: "#f7f8fc" }}>
      {/* Override React Flow default node container styles so our custom HTML is fully visible */}
      <style>{`
        .react-flow__node { background: transparent !important; border: none !important; padding: 0 !important; border-radius: 0 !important; font-size: inherit !important; color: inherit !important; }
        .react-flow__node:focus, .react-flow__node:focus-visible { outline: none !important; box-shadow: none !important; }
        .react-flow__handle { width: 1px !important; height: 1px !important; min-width: 1px !important; min-height: 1px !important; background: transparent !important; border: none !important; }
        .react-flow__edge-path { stroke-linecap: round; }
      `}</style>

      {/* ── React Flow canvas ── */}
      <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
        {loading && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#a0aec0", fontSize: 13, zIndex: 10, background: "#f7f8fc" }}>
            載入製程快照...
          </div>
        )}
        {!loading && !snapshot && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#cbd5e0", fontSize: 13, zIndex: 10 }}>
            從左側選擇物件，或點擊底部 timeline 的事件
          </div>
        )}
        {snapshot && (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodeClick={handleNodeClick}
            fitView
            fitViewOptions={{ padding: 0.25 }}
            nodesDraggable={false}
            nodesConnectable={false}
            nodesFocusable={false}
            panOnDrag={true}
            zoomOnScroll={true}
            style={{ background: "#f7f8fc", width: "100%", height: "100%" }}
          >
            <Background variant={BackgroundVariant.Dots} gap={28} size={1} color="#cbd5e0" />
          </ReactFlow>
        )}
      </div>

      {/* ── Detail panel ── */}
      {selectedNodeId && snapshot && (
        <div style={{
          width: 280, flexShrink: 0,
          background: "#ffffff",
          borderLeft: `3px solid ${accentForSelected}`,
          display: "flex", flexDirection: "column",
          overflow: "hidden",
        }}>
          <div style={{
            padding: "10px 14px 8px",
            borderBottom: "1px solid #e2e8f0",
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}>
            <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", color: accentForSelected }}>
              {selectedNodeId}
            </span>
            <button
              onClick={() => setSelectedNodeId(null)}
              style={{ background: "none", border: "none", cursor: "pointer", color: "#a0aec0", fontSize: 16, lineHeight: 1, padding: "0 2px" }}
            >
              ×
            </button>
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "12px 14px" }}>
            {renderDetail()}
          </div>
        </div>
      )}
    </div>
  );
}
