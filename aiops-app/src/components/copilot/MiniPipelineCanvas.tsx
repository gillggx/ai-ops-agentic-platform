"use client";

/**
 * MiniPipelineCanvas — read-only ReactFlow snapshot used by the dashboard
 * Pipeline Workspace. The chat-driven Glass Box agent emits pb_glass_op
 * events; AppShell hands the latest pipeline_json + last-added node id to
 * this component so the user sees the build draw itself in real time.
 *
 * This is intentionally NOT the full DagCanvas — no BuilderContext, no
 * parameter editing, no port handles, no minimap. Goal: be visually
 * informative while the agent is building.
 */

import { useEffect, useMemo } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  type Edge,
  type Node,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Dagre from "@dagrejs/dagre";
import type { PipelineJSON } from "@/lib/pipeline-builder/types";

export type MiniCanvasStatus = "idle" | "building" | "done" | "error";

interface Props {
  pipelineJson: PipelineJSON | null;
  /** node id currently being added by Glass Box (gets pulse animation) */
  highlightNodeId?: string | null;
  /** per-node run status — coloured border after pb_run_done */
  runStatuses?: Record<string, "success" | "failed" | "skipped" | null>;
  /** drives the status pill at the top */
  status?: MiniCanvasStatus;
  height?: number | string;
}

const DEFAULT_HEIGHT = 280;

const CATEGORY_COLOR: Record<string, { bg: string; border: string; fg: string }> = {
  source:    { bg: "#EFF6FF", border: "#60A5FA", fg: "#1E3A8A" },
  transform: { bg: "#F5F3FF", border: "#A78BFA", fg: "#4C1D95" },
  logic:     { bg: "#FEFCE8", border: "#FACC15", fg: "#854D0E" },
  output:    { bg: "#ECFDF5", border: "#34D399", fg: "#065F46" },
  custom:    { bg: "#F1F5F9", border: "#94A3B8", fg: "#1E293B" },
};

function inferCategory(blockId: string): keyof typeof CATEGORY_COLOR {
  if (blockId.includes("alert"))  return "output";
  if (blockId.includes("chart"))  return "output";
  if (blockId.includes("data_view")) return "output";
  if (blockId.includes("history") || blockId.includes("source") || blockId === "block_process_history") return "source";
  if (blockId.includes("threshold") || blockId.includes("consecutive") || blockId.includes("weco") || blockId.includes("logic")) return "logic";
  return "transform";
}

function dagreLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new Dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 30, ranksep: 60, marginx: 12, marginy: 12 });
  g.setDefaultEdgeLabel(() => ({}));

  nodes.forEach((n) => g.setNode(n.id, { width: 150, height: 56 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  Dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - 75, y: pos.y - 28 } };
  });
}

interface MiniNodeData extends Record<string, unknown> {
  label: string;
  blockId: string;
  category: keyof typeof CATEGORY_COLOR;
  highlight: boolean;
  status: "success" | "failed" | "skipped" | null;
}

function MiniNode({ data }: { data: MiniNodeData }) {
  const palette = CATEGORY_COLOR[data.category] ?? CATEGORY_COLOR.custom;
  let borderStyle: "solid" | "dashed" = "solid";
  let borderColor = palette.border;
  let bgColor = palette.bg;
  if (data.highlight) {
    borderStyle = "dashed";
  }
  if (data.status === "failed") {
    borderColor = "#EF4444";
    bgColor = "#FEF2F2";
  } else if (data.status === "success") {
    borderColor = "#10B981";
  }
  return (
    <div
      style={{
        width: 150,
        padding: "8px 10px",
        background: bgColor,
        border: `2px ${borderStyle} ${borderColor}`,
        borderRadius: 8,
        boxShadow: "0 1px 2px rgba(15,23,42,0.06)",
        textAlign: "center",
        animation: data.highlight ? "mini-canvas-pulse 1.4s ease-in-out infinite" : undefined,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: palette.fg,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {data.label}
      </div>
      <div
        style={{
          fontSize: 9,
          color: "#64748B",
          marginTop: 2,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {data.blockId}
      </div>
    </div>
  );
}

const NODE_TYPES = { mini: MiniNode };

function CanvasInner({ pipelineJson, highlightNodeId, runStatuses, status, height }: Props) {
  const { fitView } = useReactFlow();

  const { nodes, edges } = useMemo(() => {
    if (!pipelineJson || pipelineJson.nodes.length === 0) {
      return { nodes: [] as Node[], edges: [] as Edge[] };
    }
    const rawNodes: Node[] = pipelineJson.nodes.map((n) => ({
      id: n.id,
      type: "mini",
      position: { x: 0, y: 0 },
      data: {
        label: n.display_label ?? n.block_id.replace(/^block_/, ""),
        blockId: n.block_id,
        category: inferCategory(n.block_id),
        highlight: n.id === highlightNodeId,
        status: (runStatuses ?? {})[n.id] ?? null,
      } satisfies MiniNodeData,
      draggable: false,
      selectable: false,
    }));
    const rawEdges: Edge[] = pipelineJson.edges.map((e) => ({
      id: e.id,
      source: e.from.node,
      target: e.to.node,
      animated: status === "building",
      style: { stroke: "#94A3B8", strokeWidth: 1.5 },
    }));
    return { nodes: dagreLayout(rawNodes, rawEdges), edges: rawEdges };
  }, [pipelineJson, highlightNodeId, runStatuses, status]);

  useEffect(() => {
    if (nodes.length === 0) return;
    const t = setTimeout(() => fitView({ padding: 0.18, duration: 250 }), 60);
    return () => clearTimeout(t);
  }, [nodes, fitView]);

  const isEmpty = nodes.length === 0;

  return (
    <div
      style={{
        position: "relative",
        height: typeof height === "number" ? `${height}px` : height ?? `${DEFAULT_HEIGHT}px`,
        width: "100%",
        background: "#FAFAFA",
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      <style>{`@keyframes mini-canvas-pulse {
        0%, 100% { opacity: .65; transform: scale(.97); }
        50%      { opacity: 1;   transform: scale(1); }
      }`}</style>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        zoomOnPinch={true}
        panOnDrag={true}
        proOptions={{ hideAttribution: true }}
        fitView
        minZoom={0.4}
        maxZoom={1.4}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#E2E8F0" />
      </ReactFlow>
      {isEmpty && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            color: "#94A3B8",
            fontSize: 12,
            pointerEvents: "none",
            textAlign: "center",
            padding: 24,
          }}
        >
          <div style={{ fontSize: 28, marginBottom: 6 }}>📐</div>
          <div>Agent 還沒開始繪製，輸入需求後會在這裡逐步畫出 pipeline。</div>
        </div>
      )}
    </div>
  );
}

export default function MiniPipelineCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  );
}
