import type { SuggestedAction } from "aiops-contract";
import { isAgentAction, isHandoffAction } from "aiops-contract";

interface Props {
  actions: SuggestedAction[];
  onTrigger: (action: SuggestedAction) => void;
}

export function SuggestedActions({ actions, onTrigger }: Props) {
  if (actions.length === 0) return null;

  return (
    <div style={{ marginTop: 20, display: "flex", gap: 8, flexWrap: "wrap" }}>
      {actions.map((action, i) => (
        <button
          key={i}
          onClick={() => onTrigger(action)}
          style={{
            padding: "8px 16px",
            borderRadius: 6,
            border: "1px solid",
            fontSize: 13,
            cursor: "pointer",
            background: "transparent",
            ...(isAgentAction(action)
              ? { borderColor: "#4299e1", color: "#90cdf4" }
              : { borderColor: "#48bb78", color: "#9ae6b4" }
            ),
          }}
        >
          {isHandoffAction(action) && <span style={{ marginRight: 6 }}>⤴</span>}
          {action.label}
        </button>
      ))}
    </div>
  );
}
