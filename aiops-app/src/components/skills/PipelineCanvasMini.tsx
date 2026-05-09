"use client";

/**
 * Mini block-diagram preview, ported from prototype `pipeline.jsx`. Used in
 * StepBlock's "Inspect pipeline" expand area to show the AI-translated chain
 * of source → transform → check.
 *
 * Real canvas editing happens in /admin/pipeline-builder/{pipeline_id}; this
 * is read-only.
 */
import type { ReactNode } from "react";

export interface MiniBlock {
  id: string;
  kind: string;       // source | transform | filter | count | join | output | rule | check
  title: string;
  params?: string;
  rows?: number | null;
  ms?: number | null;
  edgeLabel?: string | number;
}

const BLOCK_COLORS: Record<string, { dot: string; label: string }> = {
  source:    { dot: "var(--ai)",   label: "SOURCE" },
  transform: { dot: "#a07a3a",     label: "TRANSFORM" },
  filter:    { dot: "#a07a3a",     label: "FILTER" },
  count:     { dot: "#7a4ca0",     label: "COUNT" },
  check:     { dot: "var(--pass)", label: "CHECK" },
  join:      { dot: "#7a4ca0",     label: "JOIN" },
  output:    { dot: "var(--pass)", label: "OUTPUT" },
  rule:      { dot: "var(--fail)", label: "RULE" },
};

function PipelineBlock({
  block, selected, onClick,
}: { block: MiniBlock; selected?: boolean; onClick?: () => void }) {
  const meta = BLOCK_COLORS[block.kind] || BLOCK_COLORS.transform;
  return (
    <div
      onClick={onClick}
      style={{
        background: "var(--surface)",
        border: `1px solid ${selected ? "var(--ink-2)" : "var(--line)"}`,
        borderRadius: 6,
        padding: "8px 10px",
        minWidth: 168,
        cursor: onClick ? "pointer" : "default",
        boxShadow: selected ? "0 0 0 3px var(--bg-soft)" : "none",
        transition: "border-color 120ms, box-shadow 120ms",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <span style={{ width: 6, height: 6, borderRadius: 999, background: meta.dot }} />
        <span className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)" }}>{meta.label}</span>
      </div>
      <div style={{ fontSize: 12.5, fontWeight: 500, color: "var(--ink)", marginBottom: 4, lineHeight: 1.35 }}>{block.title}</div>
      {block.params && (
        <div className="mono" style={{ fontSize: 10.5, color: "var(--ink-3)", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
          {block.params}
        </div>
      )}
      {(block.rows != null || block.ms != null) && (
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 10, color: "var(--ink-4)" }}>
          {block.rows != null && <span className="mono">{block.rows} rows</span>}
          {block.ms != null && <span className="mono">{block.ms}ms</span>}
        </div>
      )}
    </div>
  );
}

function Connector({ label }: { label?: ReactNode }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      minWidth: 32, color: "var(--ink-4)",
    }}>
      <div style={{ height: 1, width: 28, background: "var(--line-strong)" }}/>
      {label != null && (
        <span className="mono" style={{ fontSize: 9, marginTop: 2, color: "var(--ink-4)" }}>{label}</span>
      )}
    </div>
  );
}

export default function PipelineCanvasMini({
  blocks, selectedId, onSelect, dense = true,
}: {
  blocks: MiniBlock[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  dense?: boolean;
}) {
  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: 0,
      flexWrap: dense ? "nowrap" : "wrap",
      padding: dense ? "8px 0" : "16px 4px",
      overflowX: "auto",
    }}>
      {blocks.map((b, i) => (
        <span key={b.id || i} style={{ display: "inline-flex", alignItems: "center" }}>
          <PipelineBlock
            block={b}
            selected={selectedId === b.id}
            onClick={onSelect ? () => onSelect(b.id) : undefined}
          />
          {i < blocks.length - 1 && (
            <Connector label={blocks[i + 1].edgeLabel ?? b.rows ?? undefined}/>
          )}
        </span>
      ))}
    </div>
  );
}
