import type { EvidenceItem } from "aiops-contract";

interface Props {
  items: EvidenceItem[];
  onHighlight?: (vizId: string) => void;
}

export function EvidenceChain({ items, onHighlight }: Props) {
  if (items.length === 0) return null;

  return (
    <div style={{ marginTop: 24 }}>
      <div style={{ fontSize: 12, color: "#718096", marginBottom: 8, letterSpacing: "0.05em" }}>
        EVIDENCE CHAIN
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {items.map((item) => (
          <div
            key={item.step}
            onClick={() => item.viz_ref && onHighlight?.(item.viz_ref)}
            style={{
              background: "#1a202c",
              border: "1px solid #2d3748",
              borderRadius: 6,
              padding: "10px 14px",
              display: "flex",
              gap: 12,
              alignItems: "flex-start",
              cursor: item.viz_ref ? "pointer" : "default",
            }}
          >
            <span style={{
              background: "#2d3748",
              color: "#90cdf4",
              borderRadius: 4,
              padding: "2px 8px",
              fontSize: 11,
              fontWeight: 600,
              flexShrink: 0,
            }}>
              S{item.step}
            </span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: "#718096", marginBottom: 2 }}>{item.tool}</div>
              <div style={{ fontSize: 13, color: "#e2e8f0" }}>{item.finding}</div>
            </div>
            {item.viz_ref && (
              <span style={{ fontSize: 10, color: "#4a5568" }}>↗</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
