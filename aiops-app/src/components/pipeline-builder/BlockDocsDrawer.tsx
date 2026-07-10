"use client";

/**
 * BlockDocsDrawer — side drawer showing a block's description + examples + schema.
 *
 * Opened from BlockLibrary's ℹ button. Users can read full docs + apply an
 * example to canvas (pre-fills params) before dragging anything.
 */

import { useBuilder } from "@/context/pipeline-builder/BuilderContext";
import type { BlockSpec } from "@/lib/pipeline-builder/types";

interface Props {
  block: BlockSpec | null;
  onClose: () => void;
}

export default function BlockDocsDrawer({ block, onClose }: Props) {
  const { actions, state } = useBuilder();
  if (!block) return null;

  const handleApplyExample = (paramsPreset: Record<string, unknown>) => {
    // Drop a new node onto canvas with preset params. Position uses the smart-offset path.
    const fallbackX = 80 + (state.pipeline.nodes.length * 30);
    actions.addNodeAgent(
      block,
      { x: fallbackX, y: 120 },
      { ...paramsPreset },
      // Let the reducer pick an ID (pass an empty forceId so genNodeId runs)
      genNodeId(state.pipeline.nodes)
    );
    onClose();
  };

  return (
    <div
      data-testid="block-docs-drawer"
      style={{
        position: "fixed",
        right: 0,
        top: 0,
        bottom: 0,
        width: "min(520px, 90vw)",
        background: "#fff",
        borderLeft: "1px solid #E2E8F0",
        boxShadow: "-8px 0 24px rgba(15,23,42,0.08)",
        zIndex: 180,
        display: "flex",
        flexDirection: "column",
        fontFamily: "Inter, system-ui, -apple-system, 'Noto Sans TC', sans-serif",
      }}
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
    >
      {/* Header */}
      <div
        style={{
          padding: "14px 18px",
          borderBottom: "1px solid #E2E8F0",
          background: "var(--pn, #F8FAFC)",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <CategoryBadge category={block.category} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#0F172A" }}>{block.name}</div>
          <div style={{ fontSize: 10, color: "#64748B", letterSpacing: "0.04em" }}>
            v{block.version} · {block.status}
          </div>
        </div>
        <button
          data-testid="block-docs-close"
          onClick={onClose}
          style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "#94A3B8" }}
          title="Close (Esc)"
        >
          ×
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 18 }}>
        {/* Description */}
        <Section title="Description">
          <pre
            style={{
              fontSize: 12,
              lineHeight: 1.6,
              color: "#334155",
              whiteSpace: "pre-wrap",
              fontFamily: "inherit",
              margin: 0,
              background: "var(--pn, #F8FAFC)",
              padding: 12,
              borderRadius: 4,
              border: "1px solid #E2E8F0",
            }}
          >
            {block.description || "（無描述）"}
          </pre>
        </Section>

        {/* Examples */}
        {block.examples && block.examples.length > 0 && (
          <Section title={`Examples (${block.examples.length})`}>
            {block.examples.map((ex, i) => (
              <div
                key={i}
                data-testid={`block-example-${i}`}
                style={{
                  border: "1px solid #E2E8F0",
                  borderRadius: 6,
                  padding: 12,
                  marginBottom: 10,
                  background: "#fff",
                }}
              >
                <div style={{ display: "flex", gap: 8, alignItems: "baseline", marginBottom: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: "#0F172A" }}>{ex.name}</span>
                  {ex.upstream_hint && (
                    <span
                      style={{
                        fontSize: 10,
                        padding: "1px 6px",
                        background: "#FEF3C7",
                        color: "#B45309",
                        borderRadius: 10,
                      }}
                    >
                      {ex.upstream_hint}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: "#475569", marginBottom: 8 }}>{ex.summary}</div>
                {Object.keys(ex.params).length > 0 && (
                  <details style={{ marginBottom: 8 }}>
                    <summary style={{ fontSize: 11, color: "#64748B", cursor: "pointer" }}>
                      params ({Object.keys(ex.params).length})
                    </summary>
                    <table style={{ fontSize: 11, marginTop: 6, width: "100%", borderCollapse: "collapse" }}>
                      <tbody>
                        {Object.entries(ex.params).map(([k, v]) => (
                          <tr key={k}>
                            <td style={{ padding: "3px 6px", color: "#475569", borderBottom: "1px solid #F1F5F9", width: "35%", verticalAlign: "top" }}>
                              {k}
                            </td>
                            <td style={{ padding: "3px 6px", color: "#0F172A", borderBottom: "1px solid #F1F5F9", fontFamily: "ui-monospace, monospace" }}>
                              {formatValue(v)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </details>
                )}
                <button
                  data-testid={`block-example-apply-${i}`}
                  onClick={() => handleApplyExample(ex.params)}
                  style={{
                    padding: "4px 10px",
                    fontSize: 11,
                    background: "var(--pl, #EEF2FF)",
                    color: "#3730A3",
                    border: "1px solid var(--pl, #C7D2FE)",
                    borderRadius: 3,
                    cursor: "pointer",
                    fontWeight: 600,
                    letterSpacing: "0.02em",
                  }}
                >
                  ＋ Apply to canvas
                </button>
              </div>
            ))}
          </Section>
        )}

        {/* Ports */}
        <Section title="Ports">
          <PortList label="Input" ports={block.input_schema} />
          <PortList label="Output" ports={block.output_schema} />
        </Section>

        {/* Param schema (technical) */}
        <Section title="Param schema">
          <pre
            style={{
              fontSize: 10,
              background: "var(--pn, #F8FAFC)",
              padding: 10,
              borderRadius: 4,
              border: "1px solid #E2E8F0",
              color: "#334155",
              overflow: "auto",
              margin: 0,
              maxHeight: 300,
            }}
          >
            {JSON.stringify(block.param_schema, null, 2)}
          </pre>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div
        style={{
          fontSize: 10,
          color: "#64748B",
          fontWeight: 700,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          marginBottom: 8,
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

function PortList({ label, ports }: { label: string; ports: { port: string; type: string }[] }) {
  if (!ports || ports.length === 0) {
    return <div style={{ fontSize: 11, color: "#94A3B8", marginBottom: 8 }}>{label}: none</div>;
  }
  return (
    <div style={{ fontSize: 11, marginBottom: 8 }}>
      <span style={{ color: "#64748B", fontWeight: 600 }}>{label}:</span>{" "}
      {ports.map((p, i) => (
        <span
          key={p.port}
          style={{
            display: "inline-block",
            padding: "1px 6px",
            margin: "0 4px 2px 0",
            background: "#F1F5F9",
            borderRadius: 10,
            color: "#334155",
            fontSize: 10,
            fontFamily: "ui-monospace, monospace",
          }}
        >
          {p.port} <span style={{ color: "#94A3B8" }}>:{p.type}</span>
        </span>
      ))}
    </div>
  );
}

function CategoryBadge({ category }: { category: string }) {
  const bg: Record<string, string> = {
    source: "#DBEAFE",
    transform: "#E0E7FF",
    logic: "#F3E8FF",
    output: "#FEE2E2",
    custom: "#F1F5F9",
  };
  const fg: Record<string, string> = {
    source: "#1E40AF",
    transform: "#3730A3",
    logic: "#6B21A8",
    output: "#991B1B",
    custom: "#475569",
  };
  return (
    <span
      style={{
        padding: "2px 8px",
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        borderRadius: 10,
        background: bg[category] ?? "#F1F5F9",
        color: fg[category] ?? "#475569",
      }}
    >
      {category}
    </span>
  );
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  if (typeof v === "string") return `"${v}"`;
  return String(v);
}

// Local copy of genNodeId so drawer doesn't reach into reducer internals.
// Exactly mirrors BuilderContext's implementation.
function genNodeId(nodes: { id: string }[]): string {
  let max = 0;
  for (const n of nodes) {
    const m = /^n(\d+)$/.exec(n.id);
    if (m) max = Math.max(max, parseInt(m[1], 10));
  }
  return `n${max + 1}`;
}
