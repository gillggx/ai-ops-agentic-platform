"use client";

/**
 * BuilderContext — React Context + useReducer state for the Pipeline Builder editor.
 *
 * Responsibilities:
 *   - Hold current pipeline_json (draft-in-editor)
 *   - Track selected node
 *   - Maintain undo/redo stacks (max 50)
 *   - Expose action creators for adding/removing nodes, connecting, updating params
 *   - Emit "dirty" flag to enable Save warning dialog
 */

import React, { createContext, useContext, useEffect, useReducer, useCallback, useMemo } from "react";
import type {
  BlockSpec,
  NodeResult,
  PipelineEdge,
  PipelineInput,
  PipelineJSON,
  PipelineNode,
  PipelineRecord,
} from "@/lib/pipeline-builder/types";

const MAX_HISTORY = 50;

export type PbTheme = "light" | "dark";
export type PbDensity = "compact" | "full";

export interface BuilderState {
  pipeline: PipelineJSON;
  selectedNodeId: string | null;
  /** PR-A: edge selection (mutually exclusive with selectedNodeId).
   *  When an edge is selected, the inspector panel switches to EdgeInspector. */
  selectedEdgeId: string | null;
  dirty: boolean;
  past: PipelineJSON[];
  future: PipelineJSON[];
  /** UX Fix Pack: pipeline description — edited via PipelineInfoModal, persisted
   *  to backend on save. Lives here instead of pipeline_json so it survives
   *  updatePipeline's description-only PUT. */
  description: string;
  meta: {
    pipelineId: number | null;
    // PR-B: 5-stage lifecycle (same type as PipelineStatus). Phase 11 v6
    // adds "linked" for skill-owned pipelines.
    status: "draft" | "validating" | "locked" | "active" | "archived" | "linked";
    version: string;
    parentId: number | null;
    // Phase 5-UX-7: 3-kind classification (auto_patrol | auto_check | skill)
    // Null for unsaved pipelines; set on init from DB or first save.
    pipelineKind: "auto_patrol" | "auto_check" | "skill" | "diagnostic" | null;
  };
  /** PR-D1/D3 visual preferences (persisted to localStorage) */
  theme: PbTheme;
  density: PbDensity;
  /** Bonus C: if set, clicking a column header in DataPreview writes to this param key on the selected node. */
  focusedColumnTarget: string | null;
  /** v1.3 C: per-node cached preview results — auto-displayed when user selects a node. */
  nodeResults: Record<string, NodeResult>;
}

type Action =
  | { type: "INIT"; payload: PipelineRecord | { pipeline: PipelineJSON } }
  | {
      type: "ADD_NODE";
      block: BlockSpec;
      position: { x: number; y: number };
      /** v3.2 Agent: preset params (otherwise {}) */
      params?: Record<string, unknown>;
      /** v3.2 Agent: preset node id (otherwise auto-generated) */
      forceId?: string;
      /** v3.2 Agent: skip smart-offset (Agent already applied it server-side) */
      skipOffset?: boolean;
    }
  | { type: "REMOVE_NODE"; nodeId: string }
  | { type: "MOVE_NODE"; nodeId: string; position: { x: number; y: number } }
  | { type: "SET_PARAM"; nodeId: string; key: string; value: unknown }
  | { type: "SET_PARAMS"; nodeId: string; params: Record<string, unknown> }
  | { type: "RENAME_NODE"; nodeId: string; label: string }
  | { type: "CONNECT"; edge: PipelineEdge }
  | { type: "DISCONNECT"; edgeId: string }
  | { type: "SELECT"; nodeId: string | null }
  | { type: "SELECT_EDGE"; edgeId: string | null }
  | { type: "SET_THEME"; theme: PbTheme }
  | { type: "SET_DENSITY"; density: PbDensity }
  | { type: "RENAME_PIPELINE"; name: string }
  | { type: "SET_DESCRIPTION"; description: string }
  | { type: "SET_NODES_AND_EDGES"; nodes: PipelineNode[]; edges: PipelineEdge[] }
  | { type: "UNDO" }
  | { type: "REDO" }
  | { type: "MARK_SAVED" }
  | { type: "SET_COLUMN_TARGET"; key: string | null }
  | { type: "MERGE_NODE_RESULTS"; results: Record<string, NodeResult> }
  | { type: "CLEAR_NODE_RESULTS" }
  // Phase 4-B0: pipeline-level inputs
  | { type: "DECLARE_INPUT"; input: PipelineInput }
  | { type: "UPDATE_INPUT"; name: string; patch: Partial<PipelineInput> }
  | { type: "REMOVE_INPUT"; name: string };

function snapshot(state: BuilderState): PipelineJSON {
  // Deep enough clone — nodes/edges are value objects
  return JSON.parse(JSON.stringify(state.pipeline));
}

function pushHistory(state: BuilderState): Pick<BuilderState, "past" | "future"> {
  const past = [...state.past, snapshot(state)];
  if (past.length > MAX_HISTORY) past.shift();
  return { past, future: [] };
}

function genNodeId(nodes: PipelineNode[]): string {
  let i = 1;
  const existing = new Set(nodes.map((n) => n.id));
  while (existing.has(`n${i}`)) i += 1;
  return `n${i}`;
}

function genEdgeId(edges: PipelineEdge[]): string {
  let i = 1;
  const existing = new Set(edges.map((e) => e.id));
  while (existing.has(`e${i}`)) i += 1;
  return `e${i}`;
}

/** v1.3 A3: if desired position collides with an existing node (within tolerance),
 *  offset by (30,30) repeatedly until free. */
function smartOffset(
  existing: PipelineNode[],
  desired: { x: number; y: number },
  step = 30,
  tolerance = 20
): { x: number; y: number } {
  let pos = { ...desired };
  let safety = 40; // avoid infinite loops
  while (safety-- > 0) {
    const collides = existing.some(
      (n) => Math.abs(n.position.x - pos.x) < tolerance && Math.abs(n.position.y - pos.y) < tolerance
    );
    if (!collides) break;
    pos = { x: pos.x + step, y: pos.y + step };
  }
  return pos;
}

/** v1.3 C: compute all descendants (downstream nodes) of a given node. */
function descendants(nodeId: string, edges: PipelineEdge[]): Set<string> {
  const out = new Set<string>();
  const frontier = [nodeId];
  while (frontier.length) {
    const cur = frontier.shift()!;
    for (const e of edges) {
      if (e.from.node === cur && !out.has(e.to.node)) {
        out.add(e.to.node);
        frontier.push(e.to.node);
      }
    }
  }
  return out;
}

/** Clear cache entries for a node and all its downstream descendants. */
function invalidateFromNode(
  nodeResults: Record<string, NodeResult>,
  nodeId: string,
  edges: PipelineEdge[]
): Record<string, NodeResult> {
  const victims = descendants(nodeId, edges);
  victims.add(nodeId);
  const next: Record<string, NodeResult> = {};
  for (const [k, v] of Object.entries(nodeResults)) {
    if (!victims.has(k)) next[k] = v;
  }
  return next;
}

const defaultPipeline = (): PipelineJSON => ({
  version: "1.0",
  name: "新 Pipeline",
  inputs: [],
  metadata: {},
  nodes: [],
  edges: [],
});

const initialState: BuilderState = {
  pipeline: defaultPipeline(),
  selectedNodeId: null,
  selectedEdgeId: null,
  dirty: false,
  past: [],
  future: [],
  description: "",
  meta: { pipelineId: null, status: "draft", version: "1.0.0", parentId: null, pipelineKind: null },
  // PR-D: prefs — reducer will hydrate from localStorage on mount
  theme: "light",
  density: "full",
  focusedColumnTarget: null,
  nodeResults: {},
};

function reducer(state: BuilderState, action: Action): BuilderState {
  switch (action.type) {
    case "INIT": {
      if ("pipeline" in action.payload && !("id" in action.payload)) {
        return {
          ...initialState,
          pipeline: action.payload.pipeline,
        };
      }
      const rec = action.payload as PipelineRecord;
      return {
        ...initialState,
        pipeline: rec.pipeline_json,
        description: rec.description ?? "",
        meta: {
          pipelineId: rec.id,
          status: rec.status,
          version: rec.version,
          parentId: rec.parent_id ?? null,
          pipelineKind: rec.pipeline_kind ?? null,
        },
      };
    }
    case "ADD_NODE": {
      // v3.2 Agent path: caller supplies forceId + skipOffset + params; default path
      // keeps the v1.3 smart-offset behaviour and empty params.
      const id = action.forceId ?? genNodeId(state.pipeline.nodes);
      const position = action.skipOffset
        ? action.position
        : smartOffset(state.pipeline.nodes, action.position);
      const params: Record<string, unknown> = action.params ? { ...action.params } : {};
      // v3.2: auto-assign chart sequence = max(existing chart.sequence) + 1 unless caller already set it.
      if (action.block.name === "block_chart" && params.sequence === undefined) {
        const maxSeq = state.pipeline.nodes
          .filter((n) => n.block_id === "block_chart")
          .map((n) => (typeof n.params?.sequence === "number" ? (n.params.sequence as number) : 0))
          .reduce((a, b) => Math.max(a, b), 0);
        params.sequence = maxSeq + 1;
      }
      const newNode: PipelineNode = {
        id,
        block_id: action.block.name,
        block_version: action.block.version,
        position,
        params,
      };
      return {
        ...state,
        ...pushHistory(state),
        pipeline: { ...state.pipeline, nodes: [...state.pipeline.nodes, newNode] },
        selectedNodeId: id,
        dirty: true,
        // new node has no result yet; existing cache entries remain valid
      };
    }
    case "REMOVE_NODE": {
      // v1.3 C: invalidate removed node + its downstream
      const newResults = invalidateFromNode(
        state.nodeResults,
        action.nodeId,
        state.pipeline.edges
      );
      return {
        ...state,
        ...pushHistory(state),
        pipeline: {
          ...state.pipeline,
          nodes: state.pipeline.nodes.filter((n) => n.id !== action.nodeId),
          edges: state.pipeline.edges.filter(
            (e) => e.from.node !== action.nodeId && e.to.node !== action.nodeId
          ),
        },
        selectedNodeId: state.selectedNodeId === action.nodeId ? null : state.selectedNodeId,
        dirty: true,
        nodeResults: newResults,
      };
    }
    case "MOVE_NODE": {
      return {
        ...state,
        pipeline: {
          ...state.pipeline,
          nodes: state.pipeline.nodes.map((n) =>
            n.id === action.nodeId ? { ...n, position: action.position } : n
          ),
        },
        dirty: true,
      };
    }
    case "SET_PARAM": {
      // v1.3 C: changing params invalidates this node + downstream results
      const newResults = invalidateFromNode(
        state.nodeResults,
        action.nodeId,
        state.pipeline.edges
      );
      return {
        ...state,
        ...pushHistory(state),
        pipeline: {
          ...state.pipeline,
          nodes: state.pipeline.nodes.map((n) =>
            n.id === action.nodeId
              ? { ...n, params: { ...n.params, [action.key]: action.value } }
              : n
          ),
        },
        dirty: true,
        nodeResults: newResults,
      };
    }
    case "SET_PARAMS": {
      const newResults = invalidateFromNode(
        state.nodeResults,
        action.nodeId,
        state.pipeline.edges
      );
      return {
        ...state,
        ...pushHistory(state),
        pipeline: {
          ...state.pipeline,
          nodes: state.pipeline.nodes.map((n) =>
            n.id === action.nodeId ? { ...n, params: { ...action.params } } : n
          ),
        },
        dirty: true,
        nodeResults: newResults,
      };
    }
    case "RENAME_NODE": {
      return {
        ...state,
        ...pushHistory(state),
        pipeline: {
          ...state.pipeline,
          nodes: state.pipeline.nodes.map((n) =>
            n.id === action.nodeId ? { ...n, display_label: action.label } : n
          ),
        },
        dirty: true,
      };
    }
    case "CONNECT": {
      const id = action.edge.id || genEdgeId(state.pipeline.edges);
      const edge: PipelineEdge = { ...action.edge, id };
      const exists = state.pipeline.edges.some(
        (e) =>
          e.from.node === edge.from.node &&
          e.from.port === edge.from.port &&
          e.to.node === edge.to.node &&
          e.to.port === edge.to.port
      );
      if (exists) return state;
      const newEdges = [...state.pipeline.edges, edge];
      // v1.3 C: invalidate target node + its descendants (their data source changed)
      const newResults = invalidateFromNode(state.nodeResults, edge.to.node, newEdges);
      return {
        ...state,
        ...pushHistory(state),
        pipeline: { ...state.pipeline, edges: newEdges },
        dirty: true,
        nodeResults: newResults,
      };
    }
    case "DISCONNECT": {
      const removed = state.pipeline.edges.find((e) => e.id === action.edgeId);
      const newEdges = state.pipeline.edges.filter((e) => e.id !== action.edgeId);
      let newResults = state.nodeResults;
      if (removed) {
        newResults = invalidateFromNode(newResults, removed.to.node, newEdges);
      }
      return {
        ...state,
        ...pushHistory(state),
        pipeline: { ...state.pipeline, edges: newEdges },
        dirty: true,
        nodeResults: newResults,
        // Deselect the edge if it was the one removed.
        selectedEdgeId: state.selectedEdgeId === action.edgeId ? null : state.selectedEdgeId,
      };
    }
    case "SELECT": {
      // Selecting a node clears any selected edge.
      return { ...state, selectedNodeId: action.nodeId, selectedEdgeId: null };
    }
    case "SELECT_EDGE": {
      // Selecting an edge clears any selected node.
      return { ...state, selectedEdgeId: action.edgeId, selectedNodeId: null };
    }
    case "SET_THEME":
      return { ...state, theme: action.theme };
    case "SET_DENSITY":
      return { ...state, density: action.density };
    case "RENAME_PIPELINE": {
      return { ...state, pipeline: { ...state.pipeline, name: action.name }, dirty: true };
    }
    case "DECLARE_INPUT": {
      const existing = state.pipeline.inputs ?? [];
      if (existing.some((i) => i.name === action.input.name)) {
        return state;  // no-op on duplicate name
      }
      return {
        ...state,
        ...pushHistory(state),
        pipeline: { ...state.pipeline, inputs: [...existing, action.input] },
        dirty: true,
      };
    }
    case "UPDATE_INPUT": {
      const existing = state.pipeline.inputs ?? [];
      const next = existing.map((i) =>
        i.name === action.name ? { ...i, ...action.patch } : i
      );
      return {
        ...state,
        ...pushHistory(state),
        pipeline: { ...state.pipeline, inputs: next },
        dirty: true,
      };
    }
    case "REMOVE_INPUT": {
      const existing = state.pipeline.inputs ?? [];
      const next = existing.filter((i) => i.name !== action.name);
      // Also clear any node.params that referenced this input
      const refValue = `$${action.name}`;
      const newNodes = state.pipeline.nodes.map((n) => {
        const patched: Record<string, unknown> = {};
        let touched = false;
        for (const [k, v] of Object.entries(n.params ?? {})) {
          if (v === refValue) {
            touched = true;
            // Leave empty string so user must refill (Inspector shows as blank).
            patched[k] = "";
          } else {
            patched[k] = v;
          }
        }
        return touched ? { ...n, params: patched } : n;
      });
      return {
        ...state,
        ...pushHistory(state),
        pipeline: { ...state.pipeline, inputs: next, nodes: newNodes },
        dirty: true,
      };
    }
    case "SET_DESCRIPTION": {
      if (state.description === action.description) return state;
      return { ...state, description: action.description, dirty: true };
    }
    case "SET_NODES_AND_EDGES": {
      // structural change — safest to clear cache
      return {
        ...state,
        ...pushHistory(state),
        pipeline: { ...state.pipeline, nodes: action.nodes, edges: action.edges },
        dirty: true,
        nodeResults: {},
      };
    }
    case "UNDO": {
      if (state.past.length === 0) return state;
      const previous = state.past[state.past.length - 1];
      const newPast = state.past.slice(0, -1);
      const newFuture = [snapshot(state), ...state.future].slice(0, MAX_HISTORY);
      return {
        ...state,
        pipeline: previous,
        past: newPast,
        future: newFuture,
        dirty: true,
        nodeResults: {},  // v1.3 C: undo reverts structure; safest to clear cache
      };
    }
    case "REDO": {
      if (state.future.length === 0) return state;
      const next = state.future[0];
      const newFuture = state.future.slice(1);
      const newPast = [...state.past, snapshot(state)].slice(-MAX_HISTORY);
      return {
        ...state,
        pipeline: next,
        past: newPast,
        future: newFuture,
        dirty: true,
        nodeResults: {},
      };
    }
    case "MARK_SAVED":
      return { ...state, dirty: false };
    case "SET_COLUMN_TARGET":
      return { ...state, focusedColumnTarget: action.key };
    case "MERGE_NODE_RESULTS":
      return {
        ...state,
        nodeResults: { ...state.nodeResults, ...action.results },
      };
    case "CLEAR_NODE_RESULTS":
      return { ...state, nodeResults: {} };
    default:
      return state;
  }
}

interface BuilderContextValue {
  state: BuilderState;
  dispatch: React.Dispatch<Action>;
  actions: {
    init: (record: PipelineRecord | { pipeline: PipelineJSON }) => void;
    addNode: (block: BlockSpec, position: { x: number; y: number }) => void;
    /** v3.2 Agent: add with preset params + explicit node id (matches backend) */
    addNodeAgent: (
      block: BlockSpec,
      position: { x: number; y: number },
      params: Record<string, unknown>,
      nodeId: string
    ) => void;
    removeNode: (nodeId: string) => void;
    moveNode: (nodeId: string, position: { x: number; y: number }) => void;
    setParam: (nodeId: string, key: string, value: unknown) => void;
    setParams: (nodeId: string, params: Record<string, unknown>) => void;
    renameNode: (nodeId: string, label: string) => void;
    connect: (edge: PipelineEdge) => void;
    /** v3.2 Agent: connect with explicit edge id (matches backend) */
    connectAgent: (edge: PipelineEdge) => void;
    disconnect: (edgeId: string) => void;
    select: (nodeId: string | null) => void;
    selectEdge: (edgeId: string | null) => void;
    renamePipeline: (name: string) => void;
    setDescription: (description: string) => void;
    setTheme: (theme: PbTheme) => void;
    setDensity: (density: PbDensity) => void;
    setNodesAndEdges: (nodes: PipelineNode[], edges: PipelineEdge[]) => void;
    undo: () => void;
    redo: () => void;
    markSaved: () => void;
    setColumnTarget: (key: string | null) => void;
    mergeNodeResults: (results: Record<string, NodeResult>) => void;
    clearNodeResults: () => void;
    // Phase 4-B0 — pipeline-level inputs
    declareInput: (input: PipelineInput) => void;
    updateInput: (name: string, patch: Partial<PipelineInput>) => void;
    removeInput: (name: string) => void;
  };
  selectedNode: PipelineNode | null;
  selectedEdge: PipelineEdge | null;
}

const BuilderContext = createContext<BuilderContextValue | null>(null);

export function BuilderProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  // PR-D: hydrate theme + density from localStorage on first mount.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const t = window.localStorage.getItem("pb:theme");
      if (t === "light" || t === "dark") dispatch({ type: "SET_THEME", theme: t });
      const d = window.localStorage.getItem("pb:density");
      if (d === "compact" || d === "full") dispatch({ type: "SET_DENSITY", density: d });
    } catch {
      // localStorage unavailable (incognito / SSR) — keep defaults
    }
  }, []);

  // Persist prefs on change.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem("pb:theme", state.theme);
      window.localStorage.setItem("pb:density", state.density);
    } catch { /* ignore */ }
  }, [state.theme, state.density]);

  const actions = useMemo(
    () => ({
      init: (record: PipelineRecord | { pipeline: PipelineJSON }) =>
        dispatch({ type: "INIT", payload: record }),
      addNode: (block: BlockSpec, position: { x: number; y: number }) =>
        dispatch({ type: "ADD_NODE", block, position }),
      addNodeAgent: (
        block: BlockSpec,
        position: { x: number; y: number },
        params: Record<string, unknown>,
        nodeId: string
      ) =>
        dispatch({ type: "ADD_NODE", block, position, params, forceId: nodeId, skipOffset: true }),
      removeNode: (nodeId: string) => dispatch({ type: "REMOVE_NODE", nodeId }),
      moveNode: (nodeId: string, position: { x: number; y: number }) =>
        dispatch({ type: "MOVE_NODE", nodeId, position }),
      setParam: (nodeId: string, key: string, value: unknown) =>
        dispatch({ type: "SET_PARAM", nodeId, key, value }),
      setParams: (nodeId: string, params: Record<string, unknown>) =>
        dispatch({ type: "SET_PARAMS", nodeId, params }),
      renameNode: (nodeId: string, label: string) =>
        dispatch({ type: "RENAME_NODE", nodeId, label }),
      connect: (edge: PipelineEdge) => dispatch({ type: "CONNECT", edge }),
      connectAgent: (edge: PipelineEdge) => dispatch({ type: "CONNECT", edge }),
      disconnect: (edgeId: string) => dispatch({ type: "DISCONNECT", edgeId }),
      select: (nodeId: string | null) => dispatch({ type: "SELECT", nodeId }),
      selectEdge: (edgeId: string | null) => dispatch({ type: "SELECT_EDGE", edgeId }),
      renamePipeline: (name: string) => dispatch({ type: "RENAME_PIPELINE", name }),
      setDescription: (description: string) => dispatch({ type: "SET_DESCRIPTION", description }),
      setTheme: (theme: PbTheme) => dispatch({ type: "SET_THEME", theme }),
      setDensity: (density: PbDensity) => dispatch({ type: "SET_DENSITY", density }),
      setNodesAndEdges: (nodes: PipelineNode[], edges: PipelineEdge[]) =>
        dispatch({ type: "SET_NODES_AND_EDGES", nodes, edges }),
      undo: () => dispatch({ type: "UNDO" }),
      redo: () => dispatch({ type: "REDO" }),
      markSaved: () => dispatch({ type: "MARK_SAVED" }),
      setColumnTarget: (key: string | null) => dispatch({ type: "SET_COLUMN_TARGET", key }),
      mergeNodeResults: (results: Record<string, NodeResult>) =>
        dispatch({ type: "MERGE_NODE_RESULTS", results }),
      clearNodeResults: () => dispatch({ type: "CLEAR_NODE_RESULTS" }),
      declareInput: (input: PipelineInput) => dispatch({ type: "DECLARE_INPUT", input }),
      updateInput: (name: string, patch: Partial<PipelineInput>) =>
        dispatch({ type: "UPDATE_INPUT", name, patch }),
      removeInput: (name: string) => dispatch({ type: "REMOVE_INPUT", name }),
    }),
    []
  );

  const selectedNode = useMemo(
    () =>
      state.selectedNodeId
        ? state.pipeline.nodes.find((n) => n.id === state.selectedNodeId) ?? null
        : null,
    [state.selectedNodeId, state.pipeline.nodes]
  );

  const selectedEdge = useMemo(
    () =>
      state.selectedEdgeId
        ? state.pipeline.edges.find((e) => e.id === state.selectedEdgeId) ?? null
        : null,
    [state.selectedEdgeId, state.pipeline.edges]
  );

  return (
    <BuilderContext.Provider value={{ state, dispatch, actions, selectedNode, selectedEdge }}>
      {children}
    </BuilderContext.Provider>
  );
}

export function useBuilder() {
  const ctx = useContext(BuilderContext);
  if (!ctx) throw new Error("useBuilder must be used inside <BuilderProvider>");
  return ctx;
}

// Keyboard shortcut hook for undo/redo + delete
export function useBuilderKeybindings() {
  const { actions, state } = useBuilder();
  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;
      // PR-B: locked/active/archived are read-only (undo/redo not allowed)
      const isReadonly =
        state.meta.status === "locked" ||
        state.meta.status === "active" ||
        state.meta.status === "archived";
      if (meta && (e.key === "z" || e.key === "Z")) {
        e.preventDefault();
        if (e.shiftKey) actions.redo();
        else actions.undo();
      } else if (meta && (e.key === "y" || e.key === "Y")) {
        e.preventDefault();
        actions.redo();
      } else if (
        !isReadonly &&
        (e.key === "Delete" || e.key === "Backspace") &&
        state.selectedNodeId
      ) {
        const target = e.target as HTMLElement | null;
        const tag = target?.tagName?.toLowerCase();
        if (tag === "input" || tag === "textarea" || target?.isContentEditable) return;
        e.preventDefault();
        actions.removeNode(state.selectedNodeId);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [actions, state.selectedNodeId, state.meta.status]);

  // Use a constant callback to silence eslint if needed
  return useCallback(() => {}, []);
}
