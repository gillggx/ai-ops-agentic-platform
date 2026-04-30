"use client";

import React from "react";

// SPEC_design_intent_confirm: when the agent is in builder mode and the user's
// prompt is too ambiguous to translate into a pipeline directly (e.g. "請確認
// 該機台最後一次 OOC 的 APC 參數"), the agent calls confirm_pipeline_intent
// and the sidecar emits a `design_intent_confirm` SSE event with this shape.
// Any panel hosting an agent stream can render the card; the onPick callback
// owns the post-click flow (auto follow-up POST or input pre-fill).

export interface DesignIntentInput {
  name: string;
  source: "user_input" | "event_payload" | "literal";
  rationale?: string;
}

export interface DesignIntentAlternative {
  summary: string;
}

export interface DesignIntentData {
  card_id: string;
  inputs: DesignIntentInput[];
  logic: string;
  presentation: "alert" | "chart" | "table" | "scalar" | "mixed";
  alternatives?: DesignIntentAlternative[];
  resolved?: boolean;  // flips to true once user picks; hides the buttons
}

export type DesignIntentChoice = "confirm" | "edit" | "cancel";

interface Props {
  data: DesignIntentData;
  /** Original prompt the user typed, used by the host to compose the
   *  follow-up message after confirm / edit. */
  originalPrompt: string;
  onPick: (choice: DesignIntentChoice, data: DesignIntentData) => void;
}

const SOURCE_LABEL: Record<DesignIntentInput["source"], string> = {
  user_input: "user 填",
  event_payload: "事件帶",
  literal: "寫死",
};

const PRESENT_LABEL: Record<DesignIntentData["presentation"], string> = {
  alert: "🔔 Alert（告警）",
  chart: "📈 Chart（圖表）",
  table: "📋 Table（表格）",
  scalar: "🔢 Scalar（單一數值）",
  mixed: "🧩 Mixed（多種輸出）",
};

export function DesignIntentCard({ data, onPick }: Props) {
  const disabled = !!data.resolved;
  return (
    <div style={{
      width: "100%",
      border: "1px solid #cbd5e0",
      borderRadius: 8,
      padding: "14px 16px",
      background: "#f7fafc",
      fontSize: 13,
      color: "#2d3748",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        fontWeight: 700, marginBottom: 10, color: "#1a202c",
      }}>
        <span>🛠</span>
        <span>我想為你建這條 pipeline — 你看對嗎？</span>
      </div>

      {/* Inputs */}
      {data.inputs.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{
            fontSize: 11, fontWeight: 700, color: "#4a5568",
            marginBottom: 4, letterSpacing: "0.3px",
          }}>📥 輸入</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {data.inputs.map((inp, i) => (
              <div key={i} style={{ fontSize: 12, color: "#2d3748" }}>
                <span style={{ fontFamily: "monospace", fontWeight: 600 }}>${inp.name}</span>
                <span style={{ color: "#718096", marginLeft: 6 }}>
                  ({SOURCE_LABEL[inp.source] ?? inp.source})
                </span>
                {inp.rationale && (
                  <span style={{ color: "#4a5568", marginLeft: 6 }}>— {inp.rationale}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Logic */}
      {data.logic && (
        <div style={{ marginBottom: 10 }}>
          <div style={{
            fontSize: 11, fontWeight: 700, color: "#4a5568",
            marginBottom: 4, letterSpacing: "0.3px",
          }}>📊 邏輯</div>
          <div style={{ fontSize: 12, color: "#2d3748", lineHeight: 1.5 }}>
            {data.logic}
          </div>
        </div>
      )}

      {/* Presentation */}
      <div style={{ marginBottom: 10 }}>
        <div style={{
          fontSize: 11, fontWeight: 700, color: "#4a5568",
          marginBottom: 4, letterSpacing: "0.3px",
        }}>📤 呈現</div>
        <div style={{ fontSize: 12, color: "#2d3748" }}>
          {PRESENT_LABEL[data.presentation] ?? data.presentation}
        </div>
      </div>

      {/* Alternatives */}
      {(data.alternatives?.length ?? 0) > 0 && (
        <div style={{
          marginBottom: 10, padding: "8px 10px", borderRadius: 6,
          background: "#edf2f7", fontSize: 12, color: "#4a5568",
        }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>💭 你也可能想看的另一種解讀</div>
          {(data.alternatives ?? []).map((a, i) => (
            <div key={i} style={{ marginLeft: 8 }}>• {a.summary}</div>
          ))}
        </div>
      )}

      {/* Buttons */}
      <div style={{
        display: "flex", gap: 8, marginTop: 12,
        opacity: disabled ? 0.5 : 1,
      }}>
        <button
          disabled={disabled}
          onClick={() => onPick("confirm", data)}
          style={{
            flex: "1 1 auto", padding: "8px 12px",
            border: "1px solid #2b6cb0", borderRadius: 6,
            background: disabled ? "#bee3f8" : "#2b6cb0",
            color: disabled ? "#4a5568" : "#fff",
            fontSize: 13, fontWeight: 600,
            cursor: disabled ? "default" : "pointer",
          }}
        >✅ 開始建</button>
        <button
          disabled={disabled}
          onClick={() => onPick("edit", data)}
          style={{
            padding: "8px 12px",
            border: "1px solid #cbd5e0", borderRadius: 6,
            background: disabled ? "#edf2f7" : "#ffffff",
            color: "#2d3748",
            fontSize: 13, fontWeight: 500,
            cursor: disabled ? "default" : "pointer",
          }}
        >✏️ 想修改</button>
        <button
          disabled={disabled}
          onClick={() => onPick("cancel", data)}
          style={{
            padding: "8px 12px",
            border: "1px solid #cbd5e0", borderRadius: 6,
            background: disabled ? "#edf2f7" : "#ffffff",
            color: "#a0aec0",
            fontSize: 13, fontWeight: 500,
            cursor: disabled ? "default" : "pointer",
          }}
        >❌ 取消</button>
      </div>

      {disabled && (
        <div style={{ marginTop: 8, fontSize: 11, color: "#a0aec0" }}>已選擇</div>
      )}
    </div>
  );
}
