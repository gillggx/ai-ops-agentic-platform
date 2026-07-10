"use client";

import { useBuilder } from "@/context/pipeline-builder/BuilderContext";
import type { BlockSpec } from "@/lib/pipeline-builder/types";
import { blockDisplayName } from "@/lib/pipeline-builder/style";

interface Props {
  blockCatalog: BlockSpec[];
  readOnly?: boolean;
}

export default function EdgeInspector({ blockCatalog, readOnly }: Props) {
  const { state, actions, selectedEdge } = useBuilder();

  if (!selectedEdge) return null;

  const fromNode = state.pipeline.nodes.find((n) => n.id === selectedEdge.from.node);
  const toNode = state.pipeline.nodes.find((n) => n.id === selectedEdge.to.node);

  const findBlock = (n: { block_id: string; block_version: string } | undefined) =>
    n
      ? blockCatalog.find((b) => b.name === n.block_id && b.version === n.block_version) ??
        blockCatalog.find((b) => b.name === n.block_id) ??
        null
      : null;

  const fromBlock = findBlock(fromNode);
  const toBlock = findBlock(toNode);

  const fromPortSpec = fromBlock?.output_schema?.find((p) => p.port === selectedEdge.from.port);
  const toPortSpec = toBlock?.input_schema?.find((p) => p.port === selectedEdge.to.port);

  const nodeLabel = (n: typeof fromNode) =>
    n ? n.display_label ?? blockDisplayName(n.block_id) : "?";

  return (
    <div
      data-testid="edge-inspector"
      style={{
        width: 320,
        minWidth: 320,
        borderLeft: "1px solid var(--pb-panel-border)",
        background: "var(--pb-panel-bg)",
        color: "var(--pb-text)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          padding: "8px 14px",
          borderBottom: "1px solid #E2E8F0",
          background: "var(--pn, #F8FAFC)",
        }}
      >
        <div
          style={{
            fontSize: 10,
            color: "#94A3B8",
            fontWeight: 600,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          Edge Inspector
        </div>
        <div style={{ fontSize: 11, color: "#64748B", marginTop: 2 }}>
          <code style={{ fontSize: 10 }}>{selectedEdge.id}</code>
        </div>
      </div>

      <div style={{ padding: 14, overflowY: "auto", flex: 1 }}>
        {/* Source section */}
        <Section label="SOURCE">
          <div style={rowStyle}>
            <span style={labelStyle}>Node</span>
            <span style={valueStyle}>{nodeLabel(fromNode)}</span>
          </div>
          <div style={rowStyle}>
            <span style={labelStyle}>Block</span>
            <span style={codeValueStyle}>{fromNode?.block_id ?? "—"}</span>
          </div>
          <div style={rowStyle}>
            <span style={labelStyle}>Port</span>
            <span style={valueStyle}>
              <code style={{ fontSize: 11, color: "#0F172A" }}>{selectedEdge.from.port}</code>
              {fromPortSpec?.type && (
                <span
                  style={{
                    marginLeft: 6,
                    fontSize: 9,
                    padding: "1px 5px",
                    background: "var(--pl, #EFF6FF)",
                    color: "#1E40AF",
                    border: "1px solid var(--p, #BFDBFE)",
                    borderRadius: 3,
                  }}
                >
                  {fromPortSpec.type}
                </span>
              )}
            </span>
          </div>
        </Section>

        <div
          style={{
            textAlign: "center",
            fontSize: 18,
            color: "#94A3B8",
            margin: "6px 0",
          }}
        >
          ↓
        </div>

        <Section label="TARGET">
          <div style={rowStyle}>
            <span style={labelStyle}>Node</span>
            <span style={valueStyle}>{nodeLabel(toNode)}</span>
          </div>
          <div style={rowStyle}>
            <span style={labelStyle}>Block</span>
            <span style={codeValueStyle}>{toNode?.block_id ?? "—"}</span>
          </div>
          <div style={rowStyle}>
            <span style={labelStyle}>Port</span>
            <span style={valueStyle}>
              <code style={{ fontSize: 11, color: "#0F172A" }}>{selectedEdge.to.port}</code>
              {toPortSpec?.type && (
                <span
                  style={{
                    marginLeft: 6,
                    fontSize: 9,
                    padding: "1px 5px",
                    background: "var(--pl, #EFF6FF)",
                    color: "#1E40AF",
                    border: "1px solid var(--p, #BFDBFE)",
                    borderRadius: 3,
                  }}
                >
                  {toPortSpec.type}
                </span>
              )}
            </span>
          </div>
        </Section>

        <div
          style={{
            marginTop: 14,
            padding: 10,
            fontSize: 10,
            background: "#F0F9FF",
            border: "1px solid #BAE6FD",
            borderRadius: 4,
            color: "#075985",
            lineHeight: 1.5,
          }}
        >
          💡 想改接線？直接在畫布拖曳邊的端點到其他 port（型別相容才會成功）。
        </div>
      </div>

      {!readOnly && (
        <div style={{ padding: 10, borderTop: "1px solid #E2E8F0", background: "var(--pn, #F8FAFC)" }}>
          <button
            data-testid="edge-inspector-delete"
            onClick={() => {
              actions.disconnect(selectedEdge.id);
            }}
            style={{
              width: "100%",
              padding: "5px 12px",
              fontSize: 11,
              background: "#FEF2F2",
              color: "#B91C1C",
              border: "1px solid #FCA5A5",
              borderRadius: 3,
              cursor: "pointer",
              letterSpacing: "0.02em",
            }}
          >
            🗑 刪除連線
          </button>
        </div>
      )}
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div
        style={{
          fontSize: 9,
          fontWeight: 700,
          color: "#94A3B8",
          letterSpacing: "0.08em",
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div style={{ border: "1px solid #E2E8F0", borderRadius: 4, padding: "6px 8px" }}>
        {children}
      </div>
    </div>
  );
}

const rowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "3px 0",
  fontSize: 11,
};

const labelStyle: React.CSSProperties = {
  color: "#64748B",
  fontSize: 10,
  letterSpacing: "0.03em",
  textTransform: "uppercase",
  fontWeight: 600,
};

const valueStyle: React.CSSProperties = {
  color: "#0F172A",
  fontWeight: 500,
  textAlign: "right",
  maxWidth: "65%",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const codeValueStyle: React.CSSProperties = {
  ...valueStyle,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: 10,
  color: "#475569",
};
