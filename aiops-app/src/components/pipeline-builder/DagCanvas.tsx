"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Connection,
  type Edge,
  type EdgeChange,
  type EdgeTypes,
  type Node,
  type NodeChange,
  type NodeTypes,
  ReactFlowProvider,
  useReactFlow,
  useStore,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Dagre from "@dagrejs/dagre";

import { useBuilder } from "@/context/pipeline-builder/BuilderContext";
import type { BlockSpec, NodeResult, PipelineEdge, PipelineNode } from "@/lib/pipeline-builder/types";
import {
  CANVAS_BG,
  CANVAS_DOT,
  EDGE_COLOR,
  blockDisplayName,
} from "@/lib/pipeline-builder/style";
import { CustomNode, type PBNodeData } from "./CustomNode";
import DeletableEdge from "./DeletableEdge";

/** v1.3.3: Ghost block dims at 1x zoom — measured to match CustomNode exactly.
 *  Process History node renders at 133 × 40 px with current CSS. Ghost scales
 *  with React Flow zoom via useStore subscription. */
const GHOST_W_1X = 133;
const GHOST_H_1X = 40;

interface Props {
  blockCatalog: BlockSpec[];
  readOnly?: boolean;
  runStatuses?: Record<string, "success" | "failed" | "skipped" | null>;
  onPortError?: (message: string) => void;
  /** PR-D2: per-node agent pin callback (focuses copilot on the node) */
  onAgentPin?: (nodeId: string) => void;
  /** Bumped by parent (BuilderLayout) after every successful agent build to
   *  force a deterministic Dagre LR layout + fitView. Avoids depending on
   *  server-side layout_node positions or LLM behaviour. */
  autoLayoutNonce?: number;
}

/** PR-D1: short monospace summary of node params for node detail line. Heuristic. */
function summarizeNodeParams(
  blockId: string,
  params: Record<string, unknown> | undefined,
): string | null {
  if (!params || Object.keys(params).length === 0) return null;
  const keys = Object.keys(params).filter((k) => params[k] != null && params[k] !== "");
  if (keys.length === 0) return null;
  // Prefer showing semantically-meaningful keys first.
  const priority = [
    "column", "value_column", "operator", "target", "bound_type",
    "upper_bound", "lower_bound", "count", "flag_column", "sort_by",
    "group_by", "chart_type", "rules", "severity", "mcp_name",
    "tool_id", "lot_id",
  ];
  const ordered = [
    ...priority.filter((k) => keys.includes(k)),
    ...keys.filter((k) => !priority.includes(k)),
  ].slice(0, 4);
  return ordered
    .map((k) => {
      const v = params[k];
      const str = Array.isArray(v)
        ? `[${v.length}]`
        : typeof v === "object"
        ? "{…}"
        : typeof v === "string"
        ? v.length > 18
          ? `"${v.slice(0, 16)}…"`
          : `"${v}"`
        : String(v);
      return `${k}=${str}`;
    })
    .join(", ");
}

const NODE_TYPES: NodeTypes = { pb: CustomNode };
const EDGE_TYPES: EdgeTypes = { deletable: DeletableEdge };

function toReactFlowNodes(
  nodes: PipelineNode[],
  catalog: Map<string, BlockSpec>,
  selected: string | null,
  runStatuses: Record<string, "success" | "failed" | "skipped" | null> = {},
  nodeResults: Record<string, NodeResult> = {},
  density: "compact" | "full" = "full",
  onAgentPin: ((nodeId: string) => void) | null = null,
): Node[] {
  return nodes.map((n) => {
    const key = `${n.block_id}@${n.block_version}`;
    const spec = catalog.get(key) ?? catalog.get(n.block_id) ?? null;
    const result = nodeResults[n.id];
    const data: PBNodeData = {
      label: n.display_label ?? blockDisplayName(n.block_id),
      category: spec?.category ?? "custom",
      blockName: n.block_id,
      inputPorts: spec?.input_schema?.map((p) => p.port) ?? [],
      outputPorts: spec?.output_schema?.map((p) => p.port) ?? [],
      runStatus: runStatuses[n.id] ?? result?.status ?? null,
      runRows: result?.rows ?? null,
      runError: result?.error ?? null,
      runDurationMs: result?.duration_ms ?? null,
      isCustom: spec?.is_custom ?? false,
      density,
      paramsSummary: summarizeNodeParams(n.block_id, n.params),
      onAgentPin,
      nodeId: n.id,
    };
    return {
      id: n.id,
      type: "pb",
      position: n.position,
      data: data as unknown as Record<string, unknown>,
      selected: n.id === selected,
    };
  });
}

function toReactFlowEdges(edges: PipelineEdge[], selectedEdgeId: string | null): Edge[] {
  return edges.map((e) => ({
    id: e.id,
    source: e.from.node,
    sourceHandle: e.from.port,
    target: e.to.node,
    targetHandle: e.to.port,
    type: "deletable",
    animated: false,
    selected: e.id === selectedEdgeId,
    style: { stroke: EDGE_COLOR, strokeWidth: 1.5 },
  }));
}

function findBlock(catalog: BlockSpec[], name: string, version: string): BlockSpec | null {
  return (
    catalog.find((b) => b.name === name && b.version === version) ??
    catalog.find((b) => b.name === name) ??
    null
  );
}

function portType(block: BlockSpec | null, port: string, kind: "input" | "output"): string | null {
  if (!block) return null;
  const list = kind === "input" ? block.input_schema : block.output_schema;
  return list?.find((p) => p.port === port)?.type ?? null;
}

function DagCanvasInner({ blockCatalog, readOnly, runStatuses, onPortError, onAgentPin, autoLayoutNonce }: Props) {
  const { state, actions } = useBuilder();
  const rf = useReactFlow();
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const ghostRef = useRef<HTMLDivElement | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const [initialFitDone, setInitialFitDone] = useState(false);
  // v1.3 A2: ghost visibility flag. Actual position is written to DOM via ref
  // to avoid re-rendering the whole canvas on every mouse move.
  const [ghostVisible, setGhostVisible] = useState(false);
  // v1.3.1: whether a node is currently being dragged — while true, wrapper's
  // onMouseMove keeps ghost pinned to cursor.
  const [isNodeDragging, setIsNodeDragging] = useState(false);
  // v1.3.2: subscribe to React Flow's zoom so ghost scales with canvas.
  const rfZoom = useStore((s) => s.transform[2]);

  const catalogMap = useMemo(() => {
    const m = new Map<string, BlockSpec>();
    for (const b of blockCatalog) m.set(`${b.name}@${b.version}`, b);
    return m;
  }, [blockCatalog]);

  const rfNodes = useMemo(
    () =>
      toReactFlowNodes(
        state.pipeline.nodes,
        catalogMap,
        state.selectedNodeId,
        runStatuses ?? {},
        state.nodeResults,
        state.density,
        onAgentPin ?? null,
      ),
    [state.pipeline.nodes, catalogMap, state.selectedNodeId, runStatuses, state.nodeResults, state.density, onAgentPin]
  );
  const rfEdges = useMemo(
    () => toReactFlowEdges(state.pipeline.edges, state.selectedEdgeId),
    [state.pipeline.edges, state.selectedEdgeId]
  );

  // v1.3.3: No auto-fitView on load. Previously we did this for existing
  // pipelines, but it meant fresh-drop and reload rendered at different visual
  // sizes (new → zoom 1.0 ; reload → zoom ≈ 2). Users can click the "Auto Layout"
  // button if they want to re-fit. Keeps zoom at 1.0 always → consistent look.
  useEffect(() => {
    if (!initialFitDone) setInitialFitDone(true);
  }, [initialFitDone]);

  /**
   * v1.1 P4 FIX: drag-end-only persistence.
   * We intentionally IGNORE `position` changes while dragging; React Flow keeps
   * its own internal drag state so the node follows the cursor smoothly. Only
   * when the user releases the mouse (`onNodeDragStop`) do we write the final
   * position to our context — which is what triggers re-render.
   *
   * v1.3: Previously we tracked `select: false` events to clear selection, but
   * React Flow emits spurious deselect events during reconciliation after state
   * updates. We now only react to `select: true` — deselection happens only via
   * explicit pane click (handled by onPaneClick below) or selecting another node.
   */
  const onNodesChangeFiltered = useCallback(
    (changes: NodeChange[]) => {
      if (readOnly) return;
      for (const c of changes) {
        if (c.type === "position") continue;
        if (c.type === "select" && c.selected) {
          actions.select(c.id);
        } else if (c.type === "remove") {
          actions.removeNode(c.id);
        }
      }
    },
    [readOnly, actions]
  );

  const onPaneClick = useCallback(() => {
    actions.select(null);
    actions.selectEdge(null);
  }, [actions]);

  const onEdgeClick = useCallback(
    (_e: React.MouseEvent, edge: Edge) => {
      actions.selectEdge(edge.id);
    },
    [actions]
  );

  /** v1.3.2: Position the ghost overlay directly via DOM ref — NOT via React
   *  state — so ~60fps mouse tracking never triggers re-renders of the canvas
   *  (which would compete with React Flow's internal drag updates and cause
   *  visible stutter). */
  const updateGhostDOM = useCallback(
    (clientX: number, clientY: number) => {
      const bounds = wrapperRef.current?.getBoundingClientRect();
      const el = ghostRef.current;
      if (!bounds || !el) return;
      const w = GHOST_W_1X * rfZoom;
      const h = GHOST_H_1X * rfZoom;
      el.style.left = `${clientX - bounds.left - w / 2}px`;
      el.style.top = `${clientY - bounds.top - h / 2}px`;
      el.style.width = `${w}px`;
      el.style.height = `${h}px`;
    },
    [rfZoom]
  );

  const scheduleGhostUpdate = useCallback(
    (clientX: number, clientY: number) => {
      if (rafIdRef.current != null) cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = requestAnimationFrame(() => {
        rafIdRef.current = null;
        updateGhostDOM(clientX, clientY);
      });
    },
    [updateGhostDOM]
  );

  const handleNodeDragStart = useCallback(
    (e: React.MouseEvent | MouseEvent) => {
      if (readOnly) return;
      setIsNodeDragging(true);
      setGhostVisible(true);
      updateGhostDOM(e.clientX, e.clientY);
    },
    [readOnly, updateGhostDOM]
  );

  /** v1.3.4: React Flow's d3-drag stops propagation on mousemove, so
   *  document listeners don't fire reliably. Use React Flow's own onNodeDrag
   *  event — guaranteed to fire on every drag tick. */
  const handleNodeDrag = useCallback(
    (e: React.MouseEvent | MouseEvent) => {
      if (readOnly) return;
      updateGhostDOM(e.clientX, e.clientY);
    },
    [readOnly, updateGhostDOM]
  );

  const handleNodeDragStop = useCallback(
    (_e: React.MouseEvent | MouseEvent, node: Node) => {
      setIsNodeDragging(false);
      setGhostVisible(false);
      if (readOnly) return;
      actions.moveNode(node.id, node.position);
    },
    [readOnly, actions]
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      if (readOnly) return;
      for (const c of changes) {
        if (c.type === "remove") actions.disconnect(c.id);
      }
    },
    [readOnly, actions]
  );

  const onConnect = useCallback(
    (conn: Connection) => {
      if (readOnly) return;
      if (!conn.source || !conn.target || !conn.sourceHandle || !conn.targetHandle) return;
      const srcNode = state.pipeline.nodes.find((n) => n.id === conn.source);
      const tgtNode = state.pipeline.nodes.find((n) => n.id === conn.target);
      const srcBlock = srcNode ? findBlock(blockCatalog, srcNode.block_id, srcNode.block_version) : null;
      const tgtBlock = tgtNode ? findBlock(blockCatalog, tgtNode.block_id, tgtNode.block_version) : null;
      const srcType = portType(srcBlock, conn.sourceHandle, "output");
      const tgtType = portType(tgtBlock, conn.targetHandle, "input");
      if (srcType && tgtType && srcType !== tgtType) {
        onPortError?.(`Port type mismatch: '${srcType}' → '${tgtType}'`);
        return;
      }

      actions.connect({
        id: "",
        from: { node: conn.source, port: conn.sourceHandle },
        to: { node: conn.target, port: conn.targetHandle },
      });
    },
    [readOnly, state.pipeline.nodes, blockCatalog, actions, onPortError]
  );

  /** Reconnect: drag an edge endpoint to a different handle.
   *  We run the same port-type validation as onConnect. On success we
   *  disconnect the old edge and connect the new one. On type mismatch we
   *  reject and keep the original edge. */
  const onReconnect = useCallback(
    (oldEdge: Edge, newConn: Connection) => {
      if (readOnly) return;
      if (!newConn.source || !newConn.target || !newConn.sourceHandle || !newConn.targetHandle) return;
      const srcNode = state.pipeline.nodes.find((n) => n.id === newConn.source);
      const tgtNode = state.pipeline.nodes.find((n) => n.id === newConn.target);
      const srcBlock = srcNode ? findBlock(blockCatalog, srcNode.block_id, srcNode.block_version) : null;
      const tgtBlock = tgtNode ? findBlock(blockCatalog, tgtNode.block_id, tgtNode.block_version) : null;
      const srcType = portType(srcBlock, newConn.sourceHandle, "output");
      const tgtType = portType(tgtBlock, newConn.targetHandle, "input");
      if (srcType && tgtType && srcType !== tgtType) {
        onPortError?.(`Port type mismatch: '${srcType}' → '${tgtType}'`);
        return;
      }
      actions.disconnect(oldEdge.id);
      actions.connect({
        id: "",
        from: { node: newConn.source, port: newConn.sourceHandle },
        to: { node: newConn.target, port: newConn.targetHandle },
      });
    },
    [readOnly, state.pipeline.nodes, blockCatalog, actions, onPortError]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setGhostVisible(false);
      if (readOnly) return;
      const payload = e.dataTransfer.getData("application/x-pb-block");
      if (!payload) return;
      let block: BlockSpec;
      try {
        block = JSON.parse(payload) as BlockSpec;
      } catch {
        return;
      }
      // v1.3 A1: screenToFlowPosition takes raw client coords. The earlier version
      // subtracted wrapper bounds, causing a double-offset — nodes clustered at a
      // wrong location regardless of drop target. Pass clientX/clientY directly.
      const pos = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      // Center the node on cursor (node ≈ 130×32 after v1.3.1 shrink)
      // Center on cursor — size is independent of zoom (pos is already in flow coords)
      const adjusted = { x: Math.round(pos.x - GHOST_W_1X / 2), y: Math.round(pos.y - GHOST_H_1X / 2) };
      actions.addNode(block, adjusted);
    },
    [readOnly, rf, actions]
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    scheduleGhostUpdate(e.clientX, e.clientY);
  }, [scheduleGhostUpdate]);

  const onDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setGhostVisible(true);
    updateGhostDOM(e.clientX, e.clientY);
  }, [updateGhostDOM]);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    // Only clear when pointer exits the wrapper entirely, not when entering children
    const related = e.relatedTarget as Element | null;
    if (!related || !(wrapperRef.current?.contains(related) ?? false)) {
      setGhostVisible(false);
    }
  }, []);

  const autoLayout = useCallback(() => {
    const g = new Dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({ rankdir: "LR", nodesep: 50, ranksep: 90 });
    for (const n of state.pipeline.nodes) g.setNode(n.id, { width: 180, height: 60 });
    for (const e of state.pipeline.edges) g.setEdge(e.from.node, e.to.node);
    Dagre.layout(g);
    const newNodes = state.pipeline.nodes.map((n) => {
      const pos = g.node(n.id);
      return { ...n, position: { x: Math.round(pos.x - 90), y: Math.round(pos.y - 30) } };
    });
    actions.setNodesAndEdges(newNodes, state.pipeline.edges);
    setTimeout(() => rf.fitView({ padding: 0.2 }), 50);
  }, [state.pipeline.nodes, state.pipeline.edges, actions, rf]);

  // 2026-05-12 — re-run Dagre LR layout when BuilderLayout bumps the nonce
  // (after every successful agent build). Skip the initial 0 so a fresh
  // pipeline_json load doesn't clobber the saved positions. Deferred 30ms
  // so the final SSE add_node / connect ops have landed in state first.
  useEffect(() => {
    if (!autoLayoutNonce) return;
    if (state.pipeline.nodes.length === 0) return;
    const t = setTimeout(() => { autoLayout(); }, 30);
    return () => clearTimeout(t);
  // Intentionally exclude state.pipeline.* — we only react to explicit nonce
  // bumps, not every canvas edit.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoLayoutNonce]);

  const isEmpty = state.pipeline.nodes.length === 0;

  return (
    <div
      ref={wrapperRef}
      style={{ width: "100%", height: "100%", position: "relative", background: CANVAS_BG }}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
    >
      {/* PR-E2: arrow marker defs injected once for all edges. Three variants
          (neutral / ok / err) match upstream status colors used by DeletableEdge. */}
      <svg style={{ position: "absolute", width: 0, height: 0 }}>
        <defs>
          <marker
            id="pb-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--pb-edge)" />
          </marker>
          <marker
            id="pb-arrow-ok"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--pb-ok)" />
          </marker>
          <marker
            id="pb-arrow-err"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--pb-err)" />
          </marker>
        </defs>
      </svg>

      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        onNodesChange={onNodesChangeFiltered}
        onNodeDragStart={handleNodeDragStart}
        onNodeDrag={handleNodeDrag}
        onNodeDragStop={handleNodeDragStop}
        onEdgesChange={onEdgesChange}
        onEdgeClick={onEdgeClick}
        onConnect={onConnect}
        onReconnect={onReconnect}
        reconnectRadius={30}
        onPaneClick={onPaneClick}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        nodesConnectable={!readOnly}
        nodesDraggable={!readOnly}
        edgesReconnectable={!readOnly}
        elementsSelectable
        deleteKeyCode={readOnly ? null : ["Delete", "Backspace"]}
        fitView={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color={CANVAS_DOT} />
        <Controls showInteractive={false} style={{ border: "1px solid #E2E8F0", boxShadow: "none" }} />
        <MiniMap
          pannable
          zoomable
          ariaLabel="Pipeline minimap"
          maskColor="rgba(99,102,241,0.08)"
          style={{
            height: 110,
            width: 180,
            border: "1px solid var(--pb-panel-border)",
            boxShadow: "0 1px 3px rgba(15,23,42,0.08)",
            background: "var(--pb-panel-bg)",
          }}
          nodeBorderRadius={3}
          nodeStrokeWidth={2}
          nodeColor={(n) => {
            const d = n.data as PBNodeData | undefined;
            switch (d?.category) {
              case "source": return "#0EA5E9";
              case "transform": return "#8B5CF6";
              case "logic": return "#F59E0B";
              case "output": return "#EC4899";
              case "custom": return "#F97316";
              default: return "#94A3B8";
            }
          }}
          nodeStrokeColor={(n) => {
            const d = n.data as PBNodeData | undefined;
            return d?.runStatus === "failed" ? "#DC2626" : "transparent";
          }}
        />
      </ReactFlow>

      {/* Auto-layout button */}
      <button
        onClick={autoLayout}
        disabled={readOnly || isEmpty}
        style={{
          position: "absolute",
          top: 8,
          right: 8,
          zIndex: 10,
          background: "#fff",
          border: "1px solid #E2E8F0",
          padding: "4px 10px",
          fontSize: 11,
          borderRadius: 4,
          cursor: readOnly || isEmpty ? "not-allowed" : "pointer",
          opacity: readOnly || isEmpty ? 0.5 : 1,
          color: "#334155",
          letterSpacing: "0.02em",
          fontWeight: 500,
        }}
      >
        Auto Layout
      </button>

      {/* v1.3.3 Ghost block — always in DOM. Position/size managed imperatively
          via ghostRef (NOT in JSX style) so React re-renders don't clobber the
          rAF-driven cursor tracking. Display toggled via state. */}
      <div
        ref={ghostRef}
        data-testid="drop-ghost"
        style={{
          position: "absolute",
          border: "2px dashed #94A3B8",
          borderRadius: 4,
          background: "rgba(148, 163, 184, 0.08)",
          pointerEvents: "none",
          zIndex: 5,
          display: ghostVisible && !readOnly ? "block" : "none",
        }}
      />

      {/* Empty canvas pill */}
      {isEmpty && !readOnly && (
        <div
          data-testid="empty-canvas-pill"
          style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            padding: "8px 20px",
            border: "1px solid #CBD5E1",
            borderRadius: 20,
            background: "#fff",
            color: "#64748B",
            fontSize: 11,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            fontWeight: 600,
            pointerEvents: "none",
            boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
          }}
        >
          Drag blocks from library to begin
        </div>
      )}
    </div>
  );
}

export default function DagCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <DagCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
