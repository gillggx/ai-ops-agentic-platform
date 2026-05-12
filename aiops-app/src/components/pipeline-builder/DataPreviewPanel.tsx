"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { previewNode } from "@/lib/pipeline-builder/api";
import { useBuilder } from "@/context/pipeline-builder/BuilderContext";
import type { NodeResult, NodeResultPreview } from "@/lib/pipeline-builder/types";
import ChartRenderer, { looksLikeVegaLite, looksLikeChartDSL } from "./ChartRenderer";

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  /** If set, clicking a column header calls this (Bonus C: click-to-fill). */
  onColumnClick?: (columnName: string) => void;
}

const ROW_LIMIT_OPTIONS = [10, 25, 50, 100, "all"] as const;
type RowLimit = typeof ROW_LIMIT_OPTIONS[number];
const DEFAULT_ROW_LIMIT: RowLimit = "all";

/** Column prefix groups for wide tables (e.g. process_history) */
const PREFIX_GROUPS: Array<{ key: string; label: string; match: (c: string) => boolean }> = [
  { key: "base",   label: "BASE",   match: (c) => !/^(spc|apc|dc|recipe|fdc|ec)_/.test(c) },
  { key: "spc",    label: "SPC",    match: (c) => c.startsWith("spc_") },
  { key: "apc",    label: "APC",    match: (c) => c.startsWith("apc_") },
  { key: "dc",     label: "DC",     match: (c) => c.startsWith("dc_") },
  { key: "recipe", label: "RECIPE", match: (c) => c.startsWith("recipe_") },
  { key: "fdc",    label: "FDC",    match: (c) => c.startsWith("fdc_") },
  { key: "ec",     label: "EC",     match: (c) => c.startsWith("ec_") },
];

type LocalState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string };

interface RenderPreview {
  port: string;
  kind: "dataframe" | "chart" | "scalar" | "bool";
  columns?: string[];
  rows?: Array<Record<string, unknown>>;
  total?: number;
  spec?: unknown;
  payload?: unknown;
  boolValue?: boolean;
  otherPorts: string[];
}

/** Default port priority when user hasn't picked one.
 *  chart_spec > first dataframe > first bool > first scalar. */
function _pickDefaultPort(pv: Record<string, NodeResultPreview>): string | null {
  const ports = Object.keys(pv);
  if (ports.length === 0) return null;
  const chartPort = ports.find((p) => {
    if (p === "chart_spec") return true;
    const snap = (pv[p] as { snapshot?: unknown } | undefined)?.snapshot;
    return looksLikeVegaLite(snap) || looksLikeChartDSL(snap);
  });
  if (chartPort) return chartPort;
  const dfPort = ports.find((p) => (pv[p] as { type?: string } | undefined)?.type === "dataframe");
  if (dfPort) return dfPort;
  // For logic nodes: prefer 'evidence' (the DataFrame) over 'triggered' (the bool badge)
  if (ports.includes("evidence")) return "evidence";
  if (ports.includes("triggered")) return "triggered";
  return ports[0];
}

/** Resolve which port/preview to display given a cached NodeResult + selected port. */
function buildRenderPreview(nr: NodeResult | undefined, pickedPort?: string | null): RenderPreview | null {
  if (!nr || !nr.preview) return null;
  const pv = nr.preview;
  const ports = Object.keys(pv);
  if (ports.length === 0) return null;

  const chosen = pickedPort && ports.includes(pickedPort) ? pickedPort : _pickDefaultPort(pv);
  if (!chosen) return null;
  const others = ports.filter((p) => p !== chosen);

  const block = pv[chosen] as { type?: string; [k: string]: unknown };
  const t = block?.type;
  const snap = (block as { snapshot?: unknown }).snapshot;
  if (chosen === "chart_spec" || looksLikeVegaLite(snap) || looksLikeChartDSL(snap)) {
    const spec = (snap ?? block?.value ?? block) as unknown;
    return { port: chosen, kind: "chart", spec, otherPorts: others };
  }
  if (t === "dataframe") {
    const b = block as unknown as { columns: string[]; rows: Array<Record<string, unknown>>; total: number };
    return {
      port: chosen,
      kind: "dataframe",
      columns: b.columns ?? [],
      rows: b.rows ?? [],
      total: b.total ?? 0,
      otherPorts: others,
    };
  }
  if (t === "bool") {
    return {
      port: chosen,
      kind: "bool",
      boolValue: Boolean((block as { value?: boolean }).value),
      otherPorts: others,
    };
  }
  return { port: chosen, kind: "scalar", payload: block, otherPorts: others };
}

/** Walk upstream edges (BFS) to find nearest cached node result. Returns both
 *  the cached entry and which node it came from (may differ from selected). */
function findCachedWithFallback(
  selectedId: string,
  cache: Record<string, NodeResult>,
  edges: Array<{ from: { node: string }; to: { node: string } }>
): { cached?: NodeResult; source: string | null } {
  if (cache[selectedId]) return { cached: cache[selectedId], source: selectedId };
  const visited = new Set<string>([selectedId]);
  const queue: string[] = [selectedId];
  while (queue.length) {
    const cur = queue.shift()!;
    for (const e of edges) {
      if (e.to.node === cur && !visited.has(e.from.node)) {
        visited.add(e.from.node);
        if (cache[e.from.node]) return { cached: cache[e.from.node], source: e.from.node };
        queue.push(e.from.node);
      }
    }
  }
  return { source: null };
}

export default function DataPreviewPanel({ collapsed, onToggle, onColumnClick }: Props) {
  const { selectedNode, state, actions } = useBuilder();
  const [local, setLocal] = useState<LocalState>({ kind: "idle" });
  const [colSearch, setColSearch] = useState("");
  const [groupHidden, setGroupHidden] = useState<Record<string, boolean>>({});
  const [rowLimit, setRowLimit] = useState<RowLimit>(DEFAULT_ROW_LIMIT);
  const [selectedPort, setSelectedPort] = useState<string | null>(null);
  // PR-F3: view mode tabs for dataframe preview (Rows / Schema / Stats)
  // 2026-05-13: add `json` tab for object-native data (Gemini dual-view).
  const [viewMode, setViewMode] = useState<"rows" | "schema" | "stats" | "json">("rows");
  // Track which rows are expanded in the table view (for nested array/object expansion).
  const [expandedRows, setExpandedRows] = useState<Record<number, boolean>>({});

  // v1.3 C: read selected node's cache; if absent, walk upstream for nearest cached ancestor
  const { cached: cachedResult, source: cacheSource } = useMemo(
    () =>
      selectedNode
        ? findCachedWithFallback(selectedNode.id, state.nodeResults, state.pipeline.edges)
        : { cached: undefined, source: null },
    [selectedNode, state.nodeResults, state.pipeline.edges]
  );
  const isOwnCache = Boolean(selectedNode && cacheSource === selectedNode.id);
  const render = useMemo(
    () => buildRenderPreview(cachedResult, selectedPort),
    [cachedResult, selectedPort]
  );

  // v1.3 C: error state — only surface failure for selected node's OWN cache
  const cachedError =
    isOwnCache && cachedResult?.status === "failed" ? cachedResult.error ?? "執行失敗" : null;

  /** PR-F3: upstream columns for schema-diff — from immediate predecessor node(s).
   *  Aggregates across all upstream dataframe inputs. */
  const upstreamColumns = useMemo<string[]>(() => {
    if (!selectedNode) return [];
    const upstreamIds = state.pipeline.edges
      .filter((e) => e.to.node === selectedNode.id)
      .map((e) => e.from.node);
    const set = new Set<string>();
    for (const nid of upstreamIds) {
      const nr = state.nodeResults[nid];
      if (!nr?.preview) continue;
      for (const p of Object.values(nr.preview)) {
        const port = p as { type?: string; columns?: string[] };
        if (port?.type === "dataframe" && Array.isArray(port.columns)) {
          port.columns.forEach((c) => set.add(c));
        }
      }
    }
    return Array.from(set);
  }, [selectedNode, state.pipeline.edges, state.nodeResults]);

  const runPreview = useCallback(async () => {
    if (!selectedNode) return;
    setLocal({ kind: "loading" });
    try {
      const res = await previewNode({
        pipeline_json: state.pipeline,
        node_id: selectedNode.id,
        sample_size: 1000,  // backend cap; covers "all" for typical previews
      });
      if (res.status === "validation_error") {
        setLocal({
          kind: "error",
          message: (res.errors ?? []).map((e) => e.message).join("; ") || "驗證失敗",
        });
        return;
      }
      // v1.3 C: merge all returned node results into context cache
      if (res.all_node_results) {
        actions.mergeNodeResults(res.all_node_results as Record<string, NodeResult>);
      }
      setLocal({ kind: "idle" });  // data now comes from cache
    } catch (e) {
      setLocal({ kind: "error", message: (e as Error).message });
    }
  }, [selectedNode, state.pipeline, actions]);

  // v1.3 C: reset only the UI filters when selection changes; cached results persist
  useEffect(() => {
    setColSearch("");
    setGroupHidden({});
    setLocal({ kind: "idle" });
    setSelectedPort(null);
  }, [selectedNode?.id]);

  // v1.3.4: user-configurable row count
  const visibleRowCount = useMemo(() => {
    if (render?.kind !== "dataframe") return 0;
    const total = render.rows?.length ?? 0;
    return rowLimit === "all" ? total : Math.min(rowLimit, total);
  }, [render, rowLimit]);

  const { visibleColumns, groupStats } = useMemo(() => {
    if (!render || render.kind !== "dataframe" || !render.columns) {
      return { visibleColumns: [] as string[], groupStats: [] as Array<{ key: string; label: string; total: number; hidden: boolean }> };
    }
    const cols = render.columns;
    const stats = PREFIX_GROUPS.map((g) => ({
      key: g.key,
      label: g.label,
      total: cols.filter(g.match).length,
      hidden: Boolean(groupHidden[g.key]),
    })).filter((g) => g.total > 0);

    let filtered = cols;
    filtered = filtered.filter((c) => {
      const grp = PREFIX_GROUPS.find((g) => g.match(c));
      if (!grp) return true;
      return !groupHidden[grp.key];
    });
    const q = colSearch.trim().toLowerCase();
    if (q) filtered = filtered.filter((c) => c.toLowerCase().includes(q));
    return { visibleColumns: filtered, groupStats: stats };
  }, [render, colSearch, groupHidden]);

  if (collapsed) {
    return (
      <div
        data-testid="preview-panel-collapsed"
        style={{
          height: 28,
          background: "#F8FAFC",
          borderTop: "1px solid #E2E8F0",
          display: "flex",
          alignItems: "center",
          padding: "0 14px",
          fontSize: 11,
          color: "#64748B",
          cursor: "pointer",
          letterSpacing: "0.05em",
          textTransform: "uppercase",
          fontWeight: 600,
        }}
        onClick={onToggle}
      >
        <span style={{ marginRight: 8 }}>▲</span>
        Data Preview (collapsed)
      </div>
    );
  }

  const hasRender = Boolean(render);
  const isRendering = local.kind === "loading";
  const displayError = local.kind === "error" ? local.message : cachedError;
  const availablePorts = useMemo(
    () => (cachedResult?.preview ? Object.keys(cachedResult.preview) : []),
    [cachedResult]
  );

  return (
    <div
      data-testid="preview-panel"
      style={{
        background: "var(--pb-panel-bg)",
        color: "var(--pb-text)",
        display: "flex",
        flexDirection: "column",
        height: "100%",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "6px 14px",
          background: "var(--pb-node-bg-2)",
          borderBottom: "1px solid var(--pb-panel-border)",
          fontSize: 11,
          fontWeight: 600,
          color: "var(--pb-text-3)",
          letterSpacing: "0.05em",
          textTransform: "uppercase",
          display: "flex",
          alignItems: "center",
          gap: 14,
        }}
      >
        <span onClick={onToggle} style={{ cursor: "pointer" }}>
          ▼ Data Preview
          {render && ` : ${render.port}`}
        </span>
        {selectedNode && (
          <span style={{ color: "#0369A1", fontWeight: 500, textTransform: "none", letterSpacing: "normal" }}>
            Node: {selectedNode.display_label ?? selectedNode.block_id} ({selectedNode.id})
            {isOwnCache && (
              <span data-testid="cache-badge" style={{ marginLeft: 6, fontSize: 9, padding: "1px 6px", background: "#DCFCE7", color: "#166534", borderRadius: 3, letterSpacing: "0.02em" }}>
                cached
              </span>
            )}
            {!isOwnCache && cacheSource && (
              <span data-testid="upstream-badge" style={{ marginLeft: 6, fontSize: 9, padding: "1px 6px", background: "#FEF3C7", color: "#B45309", borderRadius: 3, letterSpacing: "0.02em" }}>
                upstream: {cacheSource}
              </span>
            )}
          </span>
        )}
        {render?.kind === "dataframe" && (
          <span
            data-testid="row-count-badge"
            style={{
              marginLeft: "auto",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              color: "#475569",
              fontWeight: 500,
              textTransform: "none",
              letterSpacing: "normal",
              fontSize: 11,
            }}
          >
            <span style={{ background: "#F1F5F9", padding: "2px 8px", borderRadius: 3 }}>
              {visibleRowCount} / {render.total ?? 0} rows · {render.columns?.length ?? 0} cols
            </span>
            <label style={{ color: "#64748B", fontSize: 10, letterSpacing: "0.03em" }}>
              show
            </label>
            <select
              data-testid="row-limit-select"
              value={rowLimit}
              onChange={(e) => {
                const v = e.target.value;
                setRowLimit(v === "all" ? "all" : Number(v) as RowLimit);
              }}
              style={{
                fontSize: 11,
                padding: "2px 6px",
                border: "1px solid #CBD5E1",
                borderRadius: 3,
                background: "#fff",
              }}
            >
              {ROW_LIMIT_OPTIONS.map((o) => (
                <option key={String(o)} value={String(o)}>
                  {o === "all" ? "all" : o}
                </option>
              ))}
            </select>
          </span>
        )}
        <span style={{ marginLeft: render?.kind === "dataframe" ? 8 : "auto" }}>
          <button
            data-testid="preview-run-btn"
            onClick={runPreview}
            disabled={!selectedNode || isRendering}
            style={{
              padding: "3px 12px",
              fontSize: 11,
              background: "#4F46E5",
              color: "#fff",
              border: "none",
              borderRadius: 3,
              cursor: selectedNode && !isRendering ? "pointer" : "not-allowed",
              opacity: selectedNode ? 1 : 0.5,
              letterSpacing: "0.02em",
              textTransform: "uppercase",
              fontWeight: 600,
            }}
          >
            {isRendering ? "Running…" : "Run Preview"}
          </button>
        </span>
      </div>

      {/* Port tabs (only when node has >1 output port) */}
      {availablePorts.length > 1 && (
        <div
          data-testid="port-tabs"
          style={{
            padding: "4px 14px",
            borderBottom: "1px solid #F1F5F9",
            display: "flex",
            gap: 4,
            background: "#FAFAFA",
            fontSize: 10,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            fontWeight: 600,
          }}
        >
          {availablePorts.map((p) => {
            const active = (render?.port ?? null) === p;
            const t = (cachedResult?.preview?.[p]?.type ?? "");
            return (
              <button
                key={p}
                data-testid={`port-tab-${p}`}
                data-active={active ? "true" : "false"}
                onClick={() => setSelectedPort(p)}
                style={{
                  padding: "3px 10px",
                  border: "none",
                  borderBottom: active ? "2px solid #4F46E5" : "2px solid transparent",
                  background: "transparent",
                  color: active ? "#3730A3" : "#64748B",
                  cursor: "pointer",
                  fontSize: 10,
                  letterSpacing: "0.04em",
                  fontWeight: 600,
                }}
                title={`port type: ${t}`}
              >
                {p}
                <span style={{ marginLeft: 4, opacity: 0.5, fontWeight: 400 }}>
                  {t ? t.slice(0, 4) : ""}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* Column controls (dataframe only, >8 cols) */}
      {render?.kind === "dataframe" && (render.columns?.length ?? 0) > 8 && (
        <div
          data-testid="preview-controls"
          style={{
            padding: "5px 14px",
            borderBottom: "1px solid #F1F5F9",
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
            fontSize: 11,
          }}
        >
          <input
            data-testid="preview-col-search"
            type="text"
            placeholder="search columns…"
            value={colSearch}
            onChange={(e) => setColSearch(e.target.value)}
            style={{
              padding: "3px 8px",
              fontSize: 11,
              border: "1px solid #CBD5E1",
              borderRadius: 3,
              width: 160,
            }}
          />
          <span style={{ color: "#94A3B8", marginLeft: 4 }}>groups:</span>
          {groupStats.map((g) => (
            <button
              key={g.key}
              data-testid={`preview-group-${g.key}`}
              onClick={() => setGroupHidden((prev) => ({ ...prev, [g.key]: !prev[g.key] }))}
              style={{
                padding: "1px 8px",
                fontSize: 10,
                background: g.hidden ? "#F1F5F9" : "#E0E7FF",
                color: g.hidden ? "#94A3B8" : "#3730A3",
                border: `1px solid ${g.hidden ? "#E2E8F0" : "#C7D2FE"}`,
                borderRadius: 10,
                cursor: "pointer",
                textDecoration: g.hidden ? "line-through" : "none",
                letterSpacing: "0.02em",
                fontWeight: 600,
              }}
            >
              {g.label} ({g.total})
            </button>
          ))}
          <span style={{ marginLeft: "auto", color: "#94A3B8" }}>
            visible: {visibleColumns.length} / {render.columns?.length ?? 0} cols
          </span>
        </div>
      )}

      {/* Body */}
      <div style={{ flex: 1, overflow: "auto", padding: "0 0" }}>
        {!selectedNode && (
          <EmptyHint text="Click a node in the canvas to inspect schema & data" />
        )}
        {selectedNode && !hasRender && !isRendering && !displayError && (
          <EmptyHint text='Click "Run Preview" to execute pipeline up to this node' />
        )}
        {isRendering && <EmptyHint text="Running preview…" />}
        {displayError && (
          <div
            data-testid="preview-error"
            style={{
              color: "#B91C1C",
              background: "#FEF2F2",
              border: "1px solid #FECACA",
              borderRadius: 4,
              padding: 12,
              fontSize: 12,
              margin: 14,
            }}
          >
            {displayError}
          </div>
        )}

        {!displayError && render?.kind === "bool" && (
          <div
            data-testid="preview-bool"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "40px 20px",
            }}
          >
            <div
              style={{
                padding: "16px 28px",
                background: render.boolValue ? "#DCFCE7" : "#F1F5F9",
                color: render.boolValue ? "#166534" : "#64748B",
                border: `1px solid ${render.boolValue ? "#86EFAC" : "#CBD5E1"}`,
                borderRadius: 6,
                fontSize: 14,
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              {render.boolValue ? "✓ TRIGGERED" : "✗ NOT TRIGGERED"}
            </div>
          </div>
        )}

        {!displayError && render?.kind === "scalar" && (
          <pre
            data-testid="preview-scalar"
            style={{
              fontSize: 11,
              padding: 12,
              background: "#F8FAFC",
              borderRadius: 4,
              margin: 14,
              overflow: "auto",
              color: "#334155",
            }}
          >
            {`[port: ${render.port}]\n${JSON.stringify(render.payload, null, 2)}`}
          </pre>
        )}

        {!displayError && render?.kind === "chart" && (
          <ChartRenderer spec={render.spec} />
        )}

        {!displayError && render?.kind === "dataframe" && (
          <>
            {/* PR-F3: Rows / Schema / Stats tabs */}
            <PreviewTabs mode={viewMode} onChange={setViewMode} />
            {viewMode === "rows" && (() => {
              const visibleRows = (render.rows ?? []).slice(0, visibleRowCount);
              // Detect whether ANY cell in visible rows is nested (object/list).
              // If so, render a leading [+] column for expansion.
              const hasNested = visibleRows.some((row) =>
                visibleColumns.some((col) => isNested(row[col]))
              );
              return (
                <table
                  data-testid="preview-table"
                  style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}
                >
                  <thead>
                    <tr>
                      {hasNested && (
                        <th style={{ width: 24, padding: "6px 6px", borderBottom: "1px solid var(--pb-panel-border)", position: "sticky", top: 0, background: "var(--pb-panel-bg)" }} />
                      )}
                      {visibleColumns.map((col) => (
                        <th
                          key={col}
                          data-testid={`preview-col-header-${col}`}
                          onClick={() => onColumnClick?.(col)}
                          style={{
                            textAlign: "left",
                            padding: "6px 10px",
                            borderBottom: "1px solid var(--pb-panel-border)",
                            position: "sticky",
                            top: 0,
                            background: "var(--pb-panel-bg)",
                            color: "var(--pb-text-2)",
                            fontWeight: 600,
                            whiteSpace: "nowrap",
                            cursor: onColumnClick ? "pointer" : "default",
                          }}
                          title={onColumnClick ? "click to fill inspector field" : undefined}
                        >
                          {col}
                        </th>
                      ))}
                      {visibleColumns.length === 0 && (
                        <th style={{ color: "var(--pb-text-4)", padding: "6px 10px", fontWeight: 400 }}>
                          （無欄位符合搜尋 / 分組條件）
                        </th>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((row, ri) => {
                      const rowHasNested = visibleColumns.some((col) => isNested(row[col]));
                      const isOpen = !!expandedRows[ri];
                      return (
                        <Fragment key={ri}>
                          <tr>
                            {hasNested && (
                              <td style={{ padding: "4px 6px", borderBottom: "1px solid var(--pb-node-border)", color: "var(--pb-text-3)", cursor: rowHasNested ? "pointer" : "default" }}
                                  onClick={() => rowHasNested && setExpandedRows((s) => ({ ...s, [ri]: !s[ri] }))}
                                  title={rowHasNested ? "Expand nested fields" : ""}>
                                {rowHasNested ? (isOpen ? "▾" : "▸") : ""}
                              </td>
                            )}
                            {visibleColumns.map((col) => (
                              <td
                                key={col}
                                style={{
                                  padding: "4px 10px",
                                  borderBottom: "1px solid var(--pb-node-border)",
                                  color: renderCellColor(row[col], col),
                                  background: renderCellBg(row[col], col),
                                  maxWidth: 240,
                                  overflow: "hidden",
                                  textOverflow: "ellipsis",
                                  whiteSpace: "nowrap",
                                  fontFamily: typeof row[col] === "number" ? "ui-monospace, monospace" : undefined,
                                }}
                              >
                                {formatCellShort(row[col])}
                              </td>
                            ))}
                          </tr>
                          {isOpen && rowHasNested && (
                            <tr>
                              <td colSpan={visibleColumns.length + (hasNested ? 1 : 0)}
                                  style={{ padding: "8px 16px", background: "var(--pb-node-bg-2)", borderBottom: "1px solid var(--pb-node-border)" }}>
                                <NestedFieldsPanel row={row} columns={visibleColumns} />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              );
            })()}
            {viewMode === "json" && (
              <JsonTreeView
                rows={(render.rows ?? []).slice(0, visibleRowCount)}
                total={render.total ?? 0}
              />
            )}
            {viewMode === "schema" && (
              <SchemaView
                outputCols={render.columns ?? []}
                upstreamCols={upstreamColumns}
                rows={render.rows ?? []}
              />
            )}
            {viewMode === "stats" && (
              <StatsView columns={render.columns ?? []} rows={render.rows ?? []} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <div
      style={{
        color: "#94A3B8",
        fontSize: 11,
        padding: "32px 20px",
        textAlign: "center",
        letterSpacing: "0.05em",
        textTransform: "uppercase",
        fontWeight: 600,
      }}
    >
      {text}
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Like formatCell, but for nested values shows a short marker
 *  (`{...3}` or `[...5]`) instead of inline JSON so the table stays
 *  readable. Full content lives in the expanded sub-panel + JSON tab. */
function formatCellShort(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return `[…${v.length}]`;
  if (typeof v === "object") {
    const keys = Object.keys(v as Record<string, unknown>);
    return `{…${keys.length}}`;
  }
  return String(v);
}

function isNested(v: unknown): boolean {
  return v !== null && typeof v === "object";
}

/** Sub-panel rendered when user clicks [+] on a row.
 *  Shows nested array/object fields with full content. Arrays of objects
 *  are rendered as a mini-table; arrays of scalars as a list; plain
 *  objects as a key/value grid. */
function NestedFieldsPanel({
  row,
  columns,
}: {
  row: Record<string, unknown>;
  columns: string[];
}) {
  const nestedFields = columns.filter((c) => isNested(row[c]));
  if (nestedFields.length === 0) {
    return <div style={{ color: "var(--pb-text-4)", fontSize: 11 }}>（無 nested 欄位）</div>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {nestedFields.map((field) => (
        <div key={field}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--pb-text-2)", marginBottom: 4 }}>
            {field}
          </div>
          <NestedValueView value={row[field]} />
        </div>
      ))}
    </div>
  );
}

function NestedValueView({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <div style={{ color: "var(--pb-text-4)", fontSize: 11 }}>[]</div>;
    }
    // Array of objects → mini table
    const objectArray = value.every((e) => e !== null && typeof e === "object" && !Array.isArray(e));
    if (objectArray) {
      const subCols = Array.from(new Set(value.flatMap((e) => Object.keys(e as Record<string, unknown>))));
      return (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, background: "var(--pb-panel-bg)" }}>
          <thead>
            <tr>
              {subCols.map((c) => (
                <th key={c} style={{ textAlign: "left", padding: "3px 8px", borderBottom: "1px solid var(--pb-node-border)", color: "var(--pb-text-3)", fontWeight: 600 }}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {value.map((elem, i) => (
              <tr key={i}>
                {subCols.map((c) => (
                  <td key={c} style={{ padding: "3px 8px", borderBottom: "1px solid var(--pb-node-border)", color: renderCellColor((elem as Record<string, unknown>)[c], c), background: renderCellBg((elem as Record<string, unknown>)[c], c) }}>
                    {formatCellShort((elem as Record<string, unknown>)[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    }
    // Array of scalars → comma-joined
    return <div style={{ fontSize: 11, color: "var(--pb-text)", fontFamily: "ui-monospace, monospace" }}>{value.map((v) => formatCell(v)).join(", ")}</div>;
  }
  if (value !== null && typeof value === "object") {
    return (
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", columnGap: 12, rowGap: 3, fontSize: 11 }}>
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <Fragment key={k}>
            <div style={{ color: "var(--pb-text-3)", fontWeight: 600 }}>{k}</div>
            <div style={{ color: "var(--pb-text)", fontFamily: typeof v === "number" ? "ui-monospace, monospace" : undefined }}>{formatCell(v)}</div>
          </Fragment>
        ))}
      </div>
    );
  }
  return <div style={{ fontSize: 11 }}>{formatCell(value)}</div>;
}

/** JSON tree view with collapsible nodes — drop-in for the JSON tab. */
function JsonTreeView({ rows, total }: { rows: Array<Record<string, unknown>>; total: number }) {
  return (
    <div style={{ padding: 12, fontFamily: "ui-monospace, monospace", fontSize: 12 }}>
      <div style={{ color: "var(--pb-text-3)", fontSize: 11, marginBottom: 8 }}>
        Showing {rows.length} of {total} record(s) — click ▸ to expand.
      </div>
      {rows.map((r, i) => (
        <JsonNode key={i} label={`[${i}]`} value={r} depth={0} initialOpen={i === 0} />
      ))}
    </div>
  );
}

function JsonNode({
  label,
  value,
  depth,
  initialOpen = false,
}: {
  label: string;
  value: unknown;
  depth: number;
  initialOpen?: boolean;
}) {
  const [open, setOpen] = useState(initialOpen || depth < 2);
  const isObj = value !== null && typeof value === "object";
  const isArr = Array.isArray(value);
  if (!isObj) {
    return (
      <div style={{ marginLeft: depth * 16, color: "var(--pb-text)", display: "flex", gap: 6 }}>
        <span style={{ color: "var(--pb-text-3)" }}>{label}:</span>
        <span style={{ color: typeof value === "string" ? "var(--pb-ok)" : "var(--pb-accent)" }}>
          {typeof value === "string" ? `"${value}"` : String(value)}
        </span>
      </div>
    );
  }
  const summary = isArr
    ? `Array(${(value as unknown[]).length})`
    : `Object(${Object.keys(value as Record<string, unknown>).length})`;
  return (
    <div style={{ marginLeft: depth * 16 }}>
      <div onClick={() => setOpen((o) => !o)} style={{ cursor: "pointer", color: "var(--pb-text-3)" }}>
        <span style={{ display: "inline-block", width: 12 }}>{open ? "▾" : "▸"}</span>
        <span>{label}: </span>
        <span style={{ color: "var(--pb-text-4)" }}>{summary}</span>
      </div>
      {open && (
        <div>
          {isArr
            ? (value as unknown[]).map((v, i) => (
                <JsonNode key={i} label={`[${i}]`} value={v} depth={depth + 1} />
              ))
            : Object.entries(value as Record<string, unknown>).map(([k, v]) => (
                <JsonNode key={k} label={k} value={v} depth={depth + 1} />
              ))}
        </div>
      )}
    </div>
  );
}

/** PR-F3: semantic cell coloring (null / OOC / PASS / WARN flags). */
function renderCellColor(v: unknown, col: string): string {
  if (v === null || v === undefined) return "var(--pb-text-4)";
  const low = col.toLowerCase();
  if (typeof v === "string") {
    if (low.includes("status") || low.includes("flag")) {
      const s = v.toUpperCase();
      if (s === "OOC" || s === "FAIL" || s === "ERR" || s === "ERROR") return "var(--pb-err)";
      if (s === "WARN" || s === "WARNING") return "var(--pb-warn)";
      if (s === "PASS" || s === "OK") return "var(--pb-ok)";
    }
  }
  if (typeof v === "boolean") {
    if (low === "triggered_row" || low === "triggered") return v ? "var(--pb-err)" : "var(--pb-text-3)";
  }
  return "var(--pb-text)";
}

function renderCellBg(v: unknown, col: string): string {
  if (typeof v === "boolean" && (col === "triggered_row" || col === "triggered") && v) {
    return "var(--pb-err-soft)";
  }
  if (typeof v === "string") {
    const s = v.toUpperCase();
    if ((col.toLowerCase().includes("status") || col.toLowerCase().includes("flag")) &&
        (s === "OOC" || s === "FAIL" || s === "ERR")) {
      return "var(--pb-err-soft)";
    }
  }
  return "transparent";
}

// ── PR-F3: Preview Tabs / Schema / Stats ────────────────────────────────────

function PreviewTabs({
  mode,
  onChange,
}: {
  mode: "rows" | "schema" | "stats" | "json";
  onChange: (m: "rows" | "schema" | "stats" | "json") => void;
}) {
  const items: Array<{ key: "rows" | "schema" | "stats" | "json"; label: string }> = [
    { key: "rows", label: "📊 Table" },
    { key: "json", label: "{} JSON" },
    { key: "schema", label: "Schema Diff" },
    { key: "stats", label: "Stats" },
  ];
  return (
    <div
      data-testid="preview-tabs"
      style={{
        display: "flex",
        gap: 2,
        borderBottom: "1px solid var(--pb-panel-border)",
        background: "var(--pb-node-bg-2)",
        padding: "4px 10px 0",
        position: "sticky",
        top: 0,
        zIndex: 1,
      }}
    >
      {items.map((i) => {
        const active = mode === i.key;
        return (
          <button
            key={i.key}
            onClick={() => onChange(i.key)}
            data-testid={`tab-${i.key}`}
            style={{
              padding: "5px 12px",
              fontSize: 11,
              fontWeight: 600,
              color: active ? "var(--pb-accent)" : "var(--pb-text-3)",
              background: "transparent",
              border: "none",
              borderBottom: `2px solid ${active ? "var(--pb-accent)" : "transparent"}`,
              cursor: "pointer",
              letterSpacing: "0.02em",
              marginBottom: -1,
            }}
          >
            {i.label}
          </button>
        );
      })}
    </div>
  );
}

function SchemaView({
  outputCols,
  upstreamCols,
  rows,
}: {
  outputCols: string[];
  upstreamCols: string[];
  rows: Array<Record<string, unknown>>;
}) {
  const upstreamSet = new Set(upstreamCols);
  const outputSet = new Set(outputCols);
  const added = outputCols.filter((c) => !upstreamSet.has(c));
  const kept = outputCols.filter((c) => upstreamSet.has(c));
  const removed = upstreamCols.filter((c) => !outputSet.has(c));
  const sample = rows[0] ?? {};

  const typeOf = (v: unknown): string => {
    if (v === null || v === undefined) return "null";
    if (typeof v === "boolean") return "bool";
    if (typeof v === "number") return Number.isInteger(v) ? "int" : "float";
    if (typeof v === "string") return "str";
    return typeof v;
  };

  return (
    <div data-testid="preview-schema" style={{ padding: 14, fontSize: 12 }}>
      <SchemaSection title={`OUTPUT (${outputCols.length})`}>
        {outputCols.length === 0 && <Muted>無欄位</Muted>}
        {outputCols.map((c) => {
          const isNew = !upstreamSet.has(c);
          return (
            <SchemaRow
              key={c}
              name={c}
              typeLabel={typeOf((sample as Record<string, unknown>)[c])}
              tone={isNew ? "added" : "kept"}
            />
          );
        })}
      </SchemaSection>
      {removed.length > 0 && (
        <SchemaSection title={`REMOVED (${removed.length})`}>
          {removed.map((c) => (
            <SchemaRow key={c} name={c} typeLabel="—" tone="removed" />
          ))}
        </SchemaSection>
      )}
      {upstreamCols.length === 0 && (
        <div style={{ marginTop: 8, color: "var(--pb-text-4)", fontSize: 10 }}>
          （上游無 cached preview — 跑一次 preview 後 Schema Diff 會比較完整）
        </div>
      )}
      {kept.length === outputCols.length && added.length === 0 && removed.length === 0 && (
        <div style={{ marginTop: 8, color: "var(--pb-text-3)", fontSize: 11 }}>
          此節點未改變 schema（相同欄位）。
        </div>
      )}
    </div>
  );
}

function SchemaSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div
        style={{
          fontSize: 9,
          fontWeight: 700,
          color: "var(--pb-text-3)",
          letterSpacing: "0.08em",
          marginBottom: 4,
          paddingBottom: 3,
          borderBottom: "1px solid var(--pb-panel-border)",
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

function SchemaRow({
  name,
  typeLabel,
  tone,
}: {
  name: string;
  typeLabel: string;
  tone: "added" | "kept" | "removed";
}) {
  const toneStyles = {
    added: { bg: "var(--pb-ok-soft)", fg: "var(--pb-ok)", badge: "NEW" },
    kept: { bg: "transparent", fg: "var(--pb-text-2)", badge: "" },
    removed: { bg: "var(--pb-err-soft)", fg: "var(--pb-err)", badge: "REMOVED" },
  }[tone];
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "3px 6px",
        borderRadius: 3,
        background: toneStyles.bg,
        fontFamily: "ui-monospace, 'JetBrains Mono', monospace",
        fontSize: 11,
      }}
    >
      <span style={{ flex: 1, color: "var(--pb-text)" }}>{name}</span>
      <span style={{ color: "var(--pb-text-4)", fontSize: 10 }}>{typeLabel}</span>
      {toneStyles.badge && (
        <span
          style={{
            fontSize: 9,
            fontWeight: 700,
            color: toneStyles.fg,
            padding: "0 5px",
            borderRadius: 2,
            letterSpacing: "0.05em",
            border: `1px solid ${toneStyles.fg}`,
          }}
        >
          {toneStyles.badge}
        </span>
      )}
    </div>
  );
}

function Muted({ children }: { children: React.ReactNode }) {
  return <div style={{ color: "var(--pb-text-4)", fontSize: 11, padding: "4px 0" }}>{children}</div>;
}

function StatsView({
  columns,
  rows,
}: {
  columns: string[];
  rows: Array<Record<string, unknown>>;
}) {
  const stats = columns.map((c) => computeColStat(c, rows));
  return (
    <div data-testid="preview-stats" style={{ padding: 14, fontSize: 11 }}>
      <div style={{ display: "grid", gap: 6 }}>
        {stats.map((s) => (
          <div
            key={s.col}
            style={{
              display: "grid",
              gridTemplateColumns: "160px 60px 1fr",
              alignItems: "center",
              gap: 10,
              padding: "4px 6px",
              borderBottom: "1px solid var(--pb-node-border)",
            }}
          >
            <span
              style={{
                fontFamily: "ui-monospace, monospace",
                color: "var(--pb-text)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {s.col}
            </span>
            <span style={{ color: "var(--pb-text-3)", fontSize: 10 }}>{s.type}</span>
            <span style={{ color: "var(--pb-text-2)", fontFamily: "ui-monospace, monospace", fontSize: 10 }}>
              {s.summary}
            </span>
          </div>
        ))}
        {stats.length === 0 && <Muted>無欄位</Muted>}
      </div>
    </div>
  );
}

function computeColStat(
  col: string,
  rows: Array<Record<string, unknown>>,
): { col: string; type: string; summary: string } {
  const values = rows.map((r) => r[col]);
  const total = values.length;
  const nulls = values.filter((v) => v === null || v === undefined).length;
  const nonNull = values.filter((v) => v !== null && v !== undefined);
  if (nonNull.length === 0) {
    return { col, type: "null", summary: `nulls=${total}` };
  }
  const first = nonNull[0];
  if (typeof first === "number") {
    const nums = nonNull as number[];
    const min = nums.reduce((a, b) => (a < b ? a : b), nums[0]);
    const max = nums.reduce((a, b) => (a > b ? a : b), nums[0]);
    const sum = nums.reduce((a, b) => a + b, 0);
    const mean = sum / nums.length;
    return {
      col,
      type: Number.isInteger(first) ? "int" : "float",
      summary: `min=${fmtNum(min)}  max=${fmtNum(max)}  mean=${fmtNum(mean)}  nulls=${nulls}`,
    };
  }
  if (typeof first === "boolean") {
    const trueN = (nonNull as boolean[]).filter(Boolean).length;
    return { col, type: "bool", summary: `true=${trueN}  false=${nonNull.length - trueN}  nulls=${nulls}` };
  }
  // string / object — uniqueness
  const seen = new Set<string>();
  for (const v of nonNull) seen.add(typeof v === "string" ? v : JSON.stringify(v));
  const top3 = Array.from(seen).slice(0, 3).join(", ");
  return {
    col,
    type: typeof first,
    summary: `unique=${seen.size}  nulls=${nulls}${seen.size <= 5 ? `  values=[${top3}]` : ""}`,
  };
}

function fmtNum(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1000) return n.toFixed(0);
  if (Math.abs(n) >= 1) return n.toFixed(2);
  return n.toFixed(4);
}
