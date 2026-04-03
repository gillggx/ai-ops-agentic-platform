"use client";

import type { AIOpsReportContract, SuggestedAction } from "aiops-contract";
import { isAgentAction, isHandoffAction } from "aiops-contract";

interface Props {
  contract: AIOpsReportContract;
  onTrigger?: (action: SuggestedAction) => void;
}

export function ContractCard({ contract, onTrigger }: Props) {
  return (
    <div style={{
      marginTop: 6,
      background: "#f7faff",
      border: "1px solid #bee3f8",
      borderRadius: 8,
      overflow: "hidden",
      fontSize: 12,
    }}>
      {/* Evidence Chain — compact */}
      {contract.evidence_chain.length > 0 && (
        <div style={{ padding: "8px 12px", borderBottom: "1px solid #e2e8f0" }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: "#718096", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.4px" }}>
            分析步驟
          </div>
          {contract.evidence_chain.map((item, i) => (
            <div key={i} style={{ display: "flex", gap: 6, marginBottom: 2, alignItems: "flex-start" }}>
              <span style={{ color: "#a0aec0", flexShrink: 0, minWidth: 14 }}>{i + 1}.</span>
              <span style={{ color: "#4a5568" }}>
                <span style={{ fontFamily: "monospace", color: "#2b6cb0", fontSize: 10, background: "#ebf4ff", padding: "1px 4px", borderRadius: 3, marginRight: 4 }}>
                  {item.tool}
                </span>
                {item.finding}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Suggested Actions */}
      {contract.suggested_actions.length > 0 && (
        <div style={{ padding: "8px 12px", display: "flex", flexWrap: "wrap", gap: 6 }}>
          {contract.suggested_actions.map((action, i) => {
            const isAgent   = isAgentAction(action);
            const isHandoff = isHandoffAction(action);
            return (
              <button
                key={i}
                onClick={() => onTrigger?.(action)}
                style={{
                  padding: "4px 10px",
                  borderRadius: 14,
                  border: isHandoff ? "1px solid #fbd38d" : "1px solid #bee3f8",
                  background: isHandoff ? "#fffaf0" : "#ebf4ff",
                  color: isHandoff ? "#c05621" : "#2b6cb0",
                  fontSize: 11,
                  fontWeight: 500,
                  cursor: "pointer",
                }}
              >
                {isHandoff ? "⚡ " : isAgent ? "💬 " : ""}{action.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
