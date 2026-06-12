"use client";

/**
 * useUpstreamColumns — for the currently-selected node, background-fetch the
 * output columns of each upstream node and return them grouped by input port.
 *
 * Strategy:
 *   - For each edge `(upstream → selected[inputPort])`, run a preview on the
 *     upstream node (sample_size=5 is plenty — we only need column names).
 *   - Cache across renders keyed by a hash of pipeline.nodes + selected node id,
 *     so switching nodes doesn't re-fetch unchanged upstream.
 *   - If any upstream fails, that port's entry becomes an empty array (fallback
 *     to free-text input in SchemaForm).
 */

import { useEffect, useMemo, useState } from "react";
import { previewNode } from "@/lib/pipeline-builder/api";
import type { PipelineJSON, PipelineNode } from "@/lib/pipeline-builder/types";

export type ColumnsByPort = Record<string, string[]>;

interface UpstreamState {
  loading: boolean;
  columnsByPort: ColumnsByPort;
  errors: Record<string, string>;
}

const EMPTY: UpstreamState = { loading: false, columnsByPort: {}, errors: {} };

/** Stable cache key for a (pipeline, node) pair — serialize only what matters. */
function cacheKey(pipeline: PipelineJSON, nodeId: string): string {
  const nodes = pipeline.nodes
    .map((n) => `${n.id}|${n.block_id}|${n.block_version}|${JSON.stringify(n.params ?? {})}`)
    .sort()
    .join("||");
  const edges = pipeline.edges
    .map((e) => `${e.from.node}.${e.from.port}→${e.to.node}.${e.to.port}`)
    .sort()
    .join("||");
  return `${nodeId}::${nodes}::${edges}`;
}

/** Module-level cache — survives re-renders but cleared on hard reload. */
const _cache = new Map<string, UpstreamState>();
const _inflight = new Map<string, Promise<UpstreamState>>();

async function fetchPortColumns(pipeline: PipelineJSON, upstreamNodeId: string): Promise<string[]> {
  const res = await previewNode({
    pipeline_json: pipeline,
    node_id: upstreamNodeId,
    sample_size: 5,
  });
  if (res.status === "validation_error") return [];
  const nr = res.node_result as
    | {
        status: string;
        preview: Record<
          string,
          { type?: string; columns?: string[]; all_columns?: string[] }
        > | null;
      }
    | null;
  if (!nr || nr.status !== "success" || !nr.preview) return [];
  // Take the first dataframe-typed port. Prefer `all_columns` (full name list,
  // uncapped) over `columns` (capped at 30 for sample-row economy) so the
  // picker can offer every column — flat-mode tables have 200-300 cols.
  for (const [, block] of Object.entries(nr.preview)) {
    if (block?.type === "dataframe") {
      if (Array.isArray(block.all_columns)) return block.all_columns;
      if (Array.isArray(block.columns)) return block.columns;
    }
  }
  return [];
}

async function computeUpstream(
  pipeline: PipelineJSON,
  selected: PipelineNode
): Promise<UpstreamState> {
  const inboundByPort: Record<string, { srcNode: string }[]> = {};
  for (const edge of pipeline.edges) {
    if (edge.to.node === selected.id) {
      (inboundByPort[edge.to.port] ??= []).push({ srcNode: edge.from.node });
    }
  }

  const ports = Object.keys(inboundByPort);
  if (ports.length === 0) return { loading: false, columnsByPort: {}, errors: {} };

  const columnsByPort: ColumnsByPort = {};
  const errors: Record<string, string> = {};

  await Promise.all(
    ports.map(async (port) => {
      const srcs = inboundByPort[port];
      const perSrc = await Promise.all(
        srcs.map(async ({ srcNode }) => {
          try {
            return await fetchPortColumns(pipeline, srcNode);
          } catch (e) {
            return { error: (e as Error).message };
          }
        })
      );
      // Flatten — for multi-input ports (rare) union the columns
      const allColumns: string[] = [];
      let lastError: string | null = null;
      for (const r of perSrc) {
        if (Array.isArray(r)) {
          for (const c of r) if (!allColumns.includes(c)) allColumns.push(c);
        } else {
          lastError = r.error;
        }
      }
      if (allColumns.length === 0 && lastError) {
        errors[port] = lastError;
      }
      columnsByPort[port] = allColumns;
    })
  );

  return { loading: false, columnsByPort, errors };
}

export function useUpstreamColumns(
  pipeline: PipelineJSON,
  selected: PipelineNode | null
): UpstreamState {
  const [state, setState] = useState<UpstreamState>(EMPTY);

  const key = useMemo(() => (selected ? cacheKey(pipeline, selected.id) : null), [pipeline, selected]);

  useEffect(() => {
    if (!selected || !key) {
      setState(EMPTY);
      return;
    }
    const cached = _cache.get(key);
    if (cached) {
      setState(cached);
      return;
    }
    const inflight = _inflight.get(key);
    if (inflight) {
      setState((s) => ({ ...s, loading: true }));
      inflight.then(setState).catch(() => setState(EMPTY));
      return;
    }
    // Kick off a new fetch
    setState({ loading: true, columnsByPort: {}, errors: {} });
    const p = computeUpstream(pipeline, selected).then((result) => {
      _cache.set(key, result);
      _inflight.delete(key);
      return result;
    });
    _inflight.set(key, p);
    p.then(setState).catch(() => {
      _inflight.delete(key);
      setState(EMPTY);
    });
  }, [key, pipeline, selected]);

  return state;
}

/** Expose a helper to clear the cache externally (not used yet; handy for debugging). */
export function clearUpstreamCache() {
  _cache.clear();
  _inflight.clear();
}
