import { useState } from "react";
import type { EvidenceItem } from "aiops-contract";

interface Props {
  items: EvidenceItem[];
  onHighlight?: (vizId: string) => void;
}

/** DR/AP-style evidence chain with collapsible python_code + step output. */
export function EvidenceChain({ items, onHighlight }: Props) {
  if (items.length === 0) return null;

  return (
    <div style={{ marginTop: 24 }}>
      <div style={{ fontSize: 12, color: "#718096", marginBottom: 8, letterSpacing: "0.05em" }}>
        EVIDENCE CHAIN
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {items.map((item) => (
          <EvidenceRow key={item.step} item={item} onHighlight={onHighlight} />
        ))}
      </div>
    </div>
  );
}

function EvidenceRow({ item, onHighlight }: { item: EvidenceItem; onHighlight?: (vizId: string) => void }) {
  const hasDetail = !!item.python_code || item.output !== undefined || !!item.error;
  const [open, setOpen] = useState(false);

  const statusColor =
    item.status === "error" ? "#fc8181"
    : item.status === "ok" ? "#9ae6b4"
    : "#90cdf4";

  return (
    <div style={{
      background: "#1a202c",
      border: "1px solid #2d3748",
      borderRadius: 6,
      overflow: "hidden",
    }}>
      <div
        onClick={() => {
          if (hasDetail) setOpen(o => !o);
          if (item.viz_ref) onHighlight?.(item.viz_ref);
        }}
        style={{
          padding: "10px 14px",
          display: "flex",
          gap: 12,
          alignItems: "flex-start",
          cursor: hasDetail || item.viz_ref ? "pointer" : "default",
        }}
      >
        <span style={{
          background: "#2d3748",
          color: statusColor,
          borderRadius: 4,
          padding: "2px 8px",
          fontSize: 11,
          fontWeight: 600,
          flexShrink: 0,
        }}>
          S{item.step}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: "#718096", marginBottom: 2 }}>
            {item.step_id || item.tool}
            {item.status === "error" && (
              <span style={{ marginLeft: 6, color: "#fc8181", fontWeight: 600 }}>FAILED</span>
            )}
          </div>
          <div style={{ fontSize: 13, color: "#e2e8f0" }}>
            {item.nl_segment || item.finding}
          </div>
        </div>
        {hasDetail && (
          <span style={{ fontSize: 10, color: "#4a5568", flexShrink: 0 }}>{open ? "▼" : "▶"}</span>
        )}
        {!hasDetail && item.viz_ref && (
          <span style={{ fontSize: 10, color: "#4a5568" }}>↗</span>
        )}
      </div>

      {open && hasDetail && (
        <div style={{ padding: "0 14px 12px 44px", borderTop: "1px solid #2d3748" }}>
          {item.python_code && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 10, color: "#718096", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                Python Code
              </div>
              <pre style={{
                background: "#0f1419", color: "#e2e8f0",
                padding: "10px 12px", borderRadius: 4,
                fontSize: 11, fontFamily: "ui-monospace, monospace",
                overflow: "auto", maxHeight: 240,
                margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word",
              }}>{item.python_code}</pre>
            </div>
          )}
          {item.error && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 10, color: "#fc8181", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                Error
              </div>
              <pre style={{
                background: "#2d1313", color: "#fed7d7",
                padding: "10px 12px", borderRadius: 4,
                fontSize: 11, fontFamily: "ui-monospace, monospace",
                margin: 0, whiteSpace: "pre-wrap",
              }}>{item.error}</pre>
            </div>
          )}
          {item.output !== undefined && item.output !== null && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 10, color: "#718096", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                Output
              </div>
              <pre style={{
                background: "#0f1419", color: "#a0aec0",
                padding: "10px 12px", borderRadius: 4,
                fontSize: 11, fontFamily: "ui-monospace, monospace",
                overflow: "auto", maxHeight: 200,
                margin: 0,
              }}>{stringifyOutput(item.output)}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function stringifyOutput(val: unknown): string {
  if (val === null || val === undefined) return "—";
  if (typeof val === "string") return val.length > 2000 ? val.slice(0, 2000) + "\n... (truncated)" : val;
  try {
    const s = JSON.stringify(val, null, 2);
    return s.length > 2000 ? s.slice(0, 2000) + "\n... (truncated)" : s;
  } catch {
    return String(val);
  }
}
