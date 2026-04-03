"use client";

import type { AIOpsReportContract } from "aiops-contract";
import { ContractRenderer } from "@/components/contract/ContractRenderer";

interface Props {
  contract: AIOpsReportContract | null;
  onClose: () => void;
  onAgentMessage?: (msg: string) => void;
  onHandoff?: (mcp: string, params?: Record<string, unknown>) => void;
}

export function AnalysisPanel({ contract, onClose, onAgentMessage, onHandoff }: Props) {
  return (
    <div style={{
      flex: 1,
      display: "flex",
      flexDirection: "column",
      background: "#f7f8fc",
      borderRight: "1px solid #e2e8f0",
      overflow: "hidden",
      minWidth: 0,
    }}>
      {/* Header */}
      <div style={{
        padding: "12px 20px",
        borderBottom: "1px solid #e2e8f0",
        background: "#ffffff",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexShrink: 0,
        gap: 12,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: "#1a202c" }}>分析結果</span>
          <span style={{
            fontSize: 10,
            padding: "2px 8px",
            background: "#ebf4ff",
            color: "#2b6cb0",
            borderRadius: 10,
            fontWeight: 600,
            border: "1px solid #bee3f8",
          }}>
            Investigate Mode
          </span>
        </div>
        <button
          onClick={onClose}
          style={{
            padding: "4px 12px",
            background: "#f7f8fc",
            border: "1px solid #e2e8f0",
            borderRadius: 6,
            fontSize: 12,
            color: "#718096",
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          ✕ 結束分析
        </button>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: "auto", padding: "24px 28px" }}>
        {!contract ? (
          <div style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            height: "100%",
            gap: 14,
            paddingBottom: 60,
          }}>
            <div style={{ fontSize: 44, lineHeight: 1 }}>🔍</div>
            <div style={{ fontSize: 15, color: "#718096", fontWeight: 500 }}>等待 Agent 分析結果...</div>
            <div style={{ fontSize: 12, color: "#a0aec0", textAlign: "center", maxWidth: 300, lineHeight: 1.7 }}>
              在右側對話框輸入分析指令<br />Agent 完成分析後，結構化結果將顯示於此
            </div>
          </div>
        ) : (
          <ContractRenderer
            contract={contract}
            onAgentMessage={onAgentMessage}
            onHandoff={onHandoff}
          />
        )}
      </div>
    </div>
  );
}
