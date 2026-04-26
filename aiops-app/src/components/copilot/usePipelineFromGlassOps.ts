"use client";

import { useEffect, useRef, useState } from "react";
import type { PipelineJSON } from "@/lib/pipeline-builder/types";

interface GlassOpEvent {
  kind: string;
  op?: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  pipeline_json?: unknown;
  status?: string;
}

interface DerivedState {
  pipelineJson: PipelineJSON | null;
  highlightNodeId: string | null;
}

const EMPTY: DerivedState = { pipelineJson: null, highlightNodeId: null };

function emptyPipeline(): PipelineJSON {
  return { version: "1.0", name: "(agent-built)", nodes: [], edges: [] };
}

/**
 * usePipelineFromGlassOps
 *
 * Replays the pb_glass_* event stream into a PipelineJSON snapshot for
 * MiniPipelineCanvas. Only handles the few ops the canvas cares about
 * (add_node / connect / rename_node / remove_node / set_param). On a
 * `done` event carrying a full pipeline_json we trust that snapshot.
 *
 * The hook is incremental: it tracks how many events it's processed and
 * only replays the new tail, so re-rendering a 50-op build doesn't
 * re-run the whole reducer each tick.
 */
export function usePipelineFromGlassOps(events: GlassOpEvent[]): DerivedState {
  const [state, setState] = useState<DerivedState>(EMPTY);
  const seenRef = useRef(0);

  useEffect(() => {
    // Cancelled / restarted (events were trimmed) → reset.
    if (events.length < seenRef.current) {
      seenRef.current = 0;
      setState(EMPTY);
      return;
    }
    if (events.length === seenRef.current) return;

    setState((prev) => {
      let next: PipelineJSON | null = prev.pipelineJson
        ? structuredClone(prev.pipelineJson)
        : null;
      let highlight = prev.highlightNodeId;

      for (let i = seenRef.current; i < events.length; i++) {
        const ev = events[i];

        if (ev.kind === "start") {
          next = emptyPipeline();
          highlight = null;
          continue;
        }
        if (ev.kind === "done") {
          const pj = ev.pipeline_json as PipelineJSON | undefined;
          if (pj && Array.isArray(pj.nodes)) {
            next = pj;
            highlight = null;
          }
          continue;
        }
        if (ev.kind !== "op" || !ev.op) continue;

        if (!next) next = emptyPipeline();
        const args = ev.args ?? {};
        const result = ev.result ?? {};

        switch (ev.op) {
          case "add_node": {
            const blockName = (args.block_name as string) ?? (args.block_id as string) ?? "block";
            const blockVersion = (args.block_version as string) ?? "1.0.0";
            const nodeId = (result.node_id as string) ?? `n${next.nodes.length + 1}`;
            const position = (result.position as { x: number; y: number }) ?? { x: 0, y: 0 };
            next.nodes.push({
              id: nodeId,
              block_id: blockName,
              block_version: blockVersion,
              position,
              params: (args.params as Record<string, unknown>) ?? {},
              display_label: blockName.replace(/^block_/, ""),
            });
            highlight = nodeId;
            break;
          }
          case "connect": {
            const fromNode = args.from_node as string;
            const fromPort = (args.from_port as string) ?? "out";
            const toNode = args.to_node as string;
            const toPort = (args.to_port as string) ?? "in";
            const edgeId = (result.edge_id as string) ?? `e${next.edges.length + 1}`;
            if (fromNode && toNode) {
              next.edges.push({
                id: edgeId,
                from: { node: fromNode, port: fromPort },
                to: { node: toNode, port: toPort },
              });
            }
            break;
          }
          case "rename_node": {
            const nodeId = args.node_id as string;
            const label = args.label as string;
            if (nodeId) {
              const node = next.nodes.find((n) => n.id === nodeId);
              if (node) node.display_label = label;
              highlight = nodeId;
            }
            break;
          }
          case "remove_node": {
            const nodeId = args.node_id as string;
            if (nodeId) {
              next.nodes = next.nodes.filter((n) => n.id !== nodeId);
              next.edges = next.edges.filter(
                (e) => e.from.node !== nodeId && e.to.node !== nodeId,
              );
              if (highlight === nodeId) highlight = null;
            }
            break;
          }
          case "set_param": {
            const nodeId = args.node_id as string;
            const key = args.key as string;
            const value = args.value;
            if (nodeId && key) {
              const node = next.nodes.find((n) => n.id === nodeId);
              if (node) node.params = { ...node.params, [key]: value };
            }
            break;
          }
        }
      }

      seenRef.current = events.length;
      return {
        pipelineJson: next && next.nodes.length > 0 ? next : null,
        highlightNodeId: highlight,
      };
    });
  }, [events]);

  return state;
}
