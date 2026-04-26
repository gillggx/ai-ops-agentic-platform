/**
 * Phase 5-UX-6: shared translator for Glass Box operation events → canvas actions.
 *
 * Used by:
 *  - AgentBuilderPanel: direct /api/agent/build/stream events
 *  - AppShell overlay + BuilderLayout session host: relayed pb_glass_op events
 *    from the chat agent's SSE stream
 *
 * Keep this pure (no React imports) so both consumers can call it synchronously.
 */

import Dagre from "@dagrejs/dagre";
import type { BlockSpec, PipelineNode, PipelineEdge } from "./types";

/** Minimal subset of BuilderContext actions we need to apply Glass Box ops. */
export interface GlassCanvasActions {
  addNodeAgent: (
    block: BlockSpec,
    position: { x: number; y: number },
    params: Record<string, unknown>,
    nodeId: string,
  ) => void;
  removeNode: (nodeId: string) => void;
  setParam: (nodeId: string, key: string, value: unknown) => void;
  renameNode: (nodeId: string, label: string) => void;
  connectAgent: (edge: {
    id: string;
    from: { node: string; port: string };
    to: { node: string; port: string };
  }) => void;
}

export interface ApplyResult {
  ok: boolean;
  error?: string;
}

/**
 * Translate one agent_builder operation into BuilderContext action(s).
 * Returns { ok: true } if applied; { ok: false, error } if the op was
 * malformed or referenced an unknown block.
 */
export function applyGlassOp(
  op: string,
  args: Record<string, unknown>,
  result: Record<string, unknown>,
  actions: GlassCanvasActions,
  blockCatalog: BlockSpec[],
): ApplyResult {
  try {
    if (op === "add_node") {
      const blockName = args.block_name as string;
      const blockVersion = (args.block_version as string) || "1.0.0";
      const spec =
        blockCatalog.find((b) => b.name === blockName && b.version === blockVersion) ??
        blockCatalog.find((b) => b.name === blockName);
      if (!spec) {
        return { ok: false, error: `unknown block: ${blockName}` };
      }
      const pos = (result.position as { x: number; y: number }) ?? { x: 100, y: 100 };
      const params = (args.params as Record<string, unknown>) ?? {};
      const nodeId = result.node_id as string;
      if (!nodeId) return { ok: false, error: "add_node result missing node_id" };
      actions.addNodeAgent(spec, pos, params, nodeId);
      return { ok: true };
    }
    if (op === "connect") {
      const from = { node: args.from_node as string, port: args.from_port as string };
      const to = { node: args.to_node as string, port: args.to_port as string };
      const edgeId = (result.edge_id as string) || `e_${Date.now().toString(36)}_${Math.floor(Math.random() * 1e4)}`;
      actions.connectAgent({ id: edgeId, from, to });
      return { ok: true };
    }
    if (op === "remove_node") {
      const nodeId = args.node_id as string;
      if (!nodeId) return { ok: false, error: "remove_node missing node_id" };
      actions.removeNode(nodeId);
      return { ok: true };
    }
    if (op === "set_param") {
      const nodeId = args.node_id as string;
      const key = args.key as string;
      if (!nodeId || !key) return { ok: false, error: "set_param missing node_id or key" };
      actions.setParam(nodeId, key, args.value);
      return { ok: true };
    }
    if (op === "rename_node") {
      const nodeId = args.node_id as string;
      // Agent emits the new label under `label`; earlier code read
      // `display_label` which is the RESULT field (what the node became)
      // not the ARGS field (what was requested). Mismatch caused the
      // rename to pass `undefined` → Canvas label erased silently.
      const label = (args.label as string) ?? (args.display_label as string);
      if (!nodeId) return { ok: false, error: "rename_node missing node_id" };
      actions.renameNode(nodeId, label);
      return { ok: true };
    }
    // finish / list_blocks / propose_patch / other — no canvas mutation
    return { ok: true };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
}

/** Pretty-print label for the operation log. */
export const OP_LABELS: Record<string, string> = {
  add_node: "加入 node",
  remove_node: "刪除 node",
  connect: "連邊",
  set_param: "設定參數",
  rename_node: "重新命名",
  finish: "完成",
};

export function opDetail(op: string, args: Record<string, unknown>): string {
  if (op === "add_node") return `${args.block_name ?? ""}`;
  if (op === "connect") return `${args.from_node}.${args.from_port} → ${args.to_node}.${args.to_port}`;
  if (op === "remove_node") return `${args.node_id}`;
  if (op === "set_param") {
    const v = JSON.stringify(args.value);
    return `${args.node_id}.${args.key} = ${v && v.length > 40 ? v.slice(0, 40) + "…" : v}`;
  }
  if (op === "rename_node") return `${args.node_id} → ${args.label ?? args.display_label ?? "?"}`;
  return "";
}

/**
 * Phase 5-UX-6: auto-layout the DAG via Dagre LR layout. Called after Glass
 * Box `done` event so the canvas ends tidy (not whatever ad-hoc positions
 * the agent emitted).
 */
export function autoLayoutPipeline(
  nodes: PipelineNode[],
  edges: PipelineEdge[],
): PipelineNode[] {
  const g = new Dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 50, ranksep: 90 });
  for (const n of nodes) g.setNode(n.id, { width: 180, height: 60 });
  for (const e of edges) g.setEdge(e.from.node, e.to.node);
  Dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) return n;
    return { ...n, position: { x: Math.round(pos.x - 90), y: Math.round(pos.y - 30) } };
  });
}
