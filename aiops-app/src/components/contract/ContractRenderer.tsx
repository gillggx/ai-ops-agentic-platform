"use client";

import { useState, type ComponentType } from "react";
import type { AIOpsReportContract, SuggestedAction, VisualizationItem, ChartDSL, SkillFindings } from "aiops-contract";
import { isAgentAction, isHandoffAction } from "aiops-contract";
import { EvidenceChain } from "./EvidenceChain";
import { SuggestedActions } from "./SuggestedActions";
import { VegaLiteChart } from "./visualizations/VegaLiteChart";
import { KpiCard } from "./visualizations/KpiCard";
import { UnsupportedPlaceholder } from "./visualizations/UnsupportedPlaceholder";
import { PlotlyVisualization } from "./visualizations/PlotlyVisualization";
import { ChartListRenderer, RenderMiddleware, type ChartDSL as LocalChartDSL, type OutputSchemaField, type SkillFindings as LocalSkillFindings } from "@/components/operations/SkillOutputRenderer";

// ── Render decision types (mirrors backend RenderIntentClassifier) ──────────
type RenderOptionBlock = {
  id: string;
  label: string;
  kind: string;
  output_schema: OutputSchemaField[];
  outputs: Record<string, unknown>;
  charts: LocalChartDSL[];
  recommended?: boolean;
};

type RenderDecision = {
  kind: "auto_chart" | "auto_table" | "auto_scalar" | "ask_user";
  question?: string;
  primary?: RenderOptionBlock;
  alternatives?: RenderOptionBlock[];
  options?: RenderOptionBlock[]; // ask_user case
};

// ---------------------------------------------------------------------------
// Visualization Type Registry
// ---------------------------------------------------------------------------

type VizComponent = ComponentType<{ spec: Record<string, unknown> }>;

const VISUALIZATION_REGISTRY: Record<string, VizComponent> = {
  "vega-lite": VegaLiteChart,
  "kpi-card":  KpiCard,
  "plotly":    PlotlyVisualization,
  // "topology": TopologyView,  — 未來加入
  // "gantt":    GanttChart,    — 未來加入
  // "table":    DataTable,     — 未來加入
};

function VisualizationRenderer({ item }: { item: VisualizationItem }) {
  const Component = VISUALIZATION_REGISTRY[item.type];
  if (!Component) return <UnsupportedPlaceholder type={item.type} />;
  return <Component spec={item.spec} />;
}

// ---------------------------------------------------------------------------
// ContractRenderer
// ---------------------------------------------------------------------------

interface Props {
  contract: AIOpsReportContract;
  onAgentMessage?: (message: string) => void;
  onHandoff?: (mcp: string, params?: Record<string, unknown>) => void;
}

export function ContractRenderer({ contract, onAgentMessage, onHandoff }: Props) {
  async function handleAction(action: SuggestedAction) {
    if (isAgentAction(action)) {
      onAgentMessage?.(action.message);
    } else if (isHandoffAction(action)) {
      onHandoff?.(action.mcp, action.params);
    } else if ((action as Record<string, unknown>).trigger === "promote_analysis") {
      // Promote ad-hoc analysis to My Skill
      const payload = (action as Record<string, unknown>).payload as Record<string, unknown> | undefined;
      if (!payload) {
        alert("無法儲存：缺少分析步驟資料");
        return;
      }
      const title = (payload.title as string) || "Ad-hoc 分析";
      const name = prompt("儲存為 My Skill\n\n名稱：", title);
      if (!name) return;  // user cancelled
      try {
        const res = await fetch("/api/admin/analysis/promote", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name,
            description: `從 Agent chat promote：${title}`,
            auto_check_description: title,
            steps_mapping: payload.steps_mapping,
            input_schema: payload.input_schema,
            output_schema: payload.output_schema || [],
          }),
        });
        if (res.ok) {
          alert(`已儲存為 Skill: ${name}\n\n前往 Knowledge Studio → My Skills 查看`);
        } else {
          const err = await res.json().catch(() => ({}));
          alert(`儲存失敗: ${(err as Record<string, string>).message || res.statusText}`);
        }
      } catch (e) {
        alert(`儲存失敗: ${e instanceof Error ? e.message : "未知錯誤"}`);
      }
    }
  }

  // ── Render decision (from MCP classifier) — instant-switchable alternatives ──
  const renderDecision = (contract as unknown as { render_decision?: RenderDecision }).render_decision;

  // Selected option index (0 = primary). For ask_user, no default selection until user picks.
  const [selectedAltIdx, setSelectedAltIdx] = useState<number>(-1);

  // Prefer the new chart DSL list (from backend ChartMiddleware) over legacy visualization
  const chartList = (contract.charts as ChartDSL[] | undefined) ?? null;
  const findings = (contract.findings as SkillFindings | undefined) ?? null;
  const outputSchema = (contract.output_schema as OutputSchemaField[] | undefined) ?? undefined;
  const useLegacyViz = (!chartList || chartList.length === 0) && contract.visualization.length > 0;

  // Resolve which option to render right now
  let activeOption: RenderOptionBlock | null = null;
  if (renderDecision) {
    if (renderDecision.kind === "ask_user") {
      // Only show content after user picks one
      if (selectedAltIdx >= 0 && renderDecision.options?.[selectedAltIdx]) {
        activeOption = renderDecision.options[selectedAltIdx];
      }
    } else {
      // auto_* — primary or chosen alternative
      if (selectedAltIdx >= 0 && renderDecision.alternatives?.[selectedAltIdx]) {
        activeOption = renderDecision.alternatives[selectedAltIdx];
      } else if (renderDecision.primary) {
        activeOption = renderDecision.primary;
      }
    }
  }

  return (
    <div style={{ maxWidth: 900 }}>
      {/* Summary */}
      <div style={{
        fontSize: 16,
        lineHeight: 1.6,
        color: "#e2e8f0",
        background: "#1a202c",
        borderRadius: 8,
        padding: "16px 20px",
        borderLeft: "3px solid #4299e1",
        marginBottom: 20,
      }}>
        {contract.summary}
      </div>

      {/* ── Render decision UI (MCP classifier output) ───────────────────── */}
      {renderDecision && renderDecision.kind === "ask_user" && selectedAltIdx < 0 && (
        <div style={{
          background: "#1a202c",
          border: "1px solid #2d3748",
          borderRadius: 8,
          padding: "16px 20px",
          marginBottom: 20,
          color: "#e2e8f0",
        }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
            {renderDecision.question || "請選擇呈現方式："}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {(renderDecision.options ?? []).map((opt, i) => (
              <button
                key={opt.id}
                onClick={() => setSelectedAltIdx(i)}
                style={{
                  textAlign: "left",
                  padding: "10px 14px",
                  background: opt.recommended ? "#2c5282" : "#2d3748",
                  border: opt.recommended ? "1px solid #4299e1" : "1px solid #4a5568",
                  borderRadius: 6,
                  color: "#e2e8f0",
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                {opt.recommended && <span style={{ marginRight: 6 }}>⭐</span>}
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Active render option (primary OR user-selected alt) */}
      {activeOption && (
        <div style={{ background: "#fff", padding: 16, borderRadius: 8, marginBottom: 16, color: "#2d3748" }}>
          <RenderMiddleware
            findings={{
              condition_met: false,
              summary: "",
              outputs: activeOption.outputs as Record<string, unknown>,
            }}
            outputSchema={activeOption.output_schema}
            charts={activeOption.charts}
          />
        </div>
      )}

      {/* Switch buttons for alternative renders (auto_* mode) */}
      {renderDecision && renderDecision.kind !== "ask_user" && (renderDecision.alternatives?.length ?? 0) > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 }}>
          <button
            onClick={() => setSelectedAltIdx(-1)}
            style={{
              padding: "5px 12px",
              fontSize: 11,
              borderRadius: 14,
              border: selectedAltIdx === -1 ? "1px solid #4299e1" : "1px solid #cbd5e0",
              background: selectedAltIdx === -1 ? "#ebf4ff" : "#fff",
              color: selectedAltIdx === -1 ? "#2b6cb0" : "#4a5568",
              cursor: "pointer",
              fontWeight: selectedAltIdx === -1 ? 600 : 400,
            }}
          >
            ⭐ {renderDecision.primary?.label ?? "預設"}
          </button>
          {(renderDecision.alternatives ?? []).map((alt, i) => (
            <button
              key={alt.id}
              onClick={() => setSelectedAltIdx(i)}
              style={{
                padding: "5px 12px",
                fontSize: 11,
                borderRadius: 14,
                border: selectedAltIdx === i ? "1px solid #4299e1" : "1px solid #cbd5e0",
                background: selectedAltIdx === i ? "#ebf4ff" : "#fff",
                color: selectedAltIdx === i ? "#2b6cb0" : "#4a5568",
                cursor: "pointer",
                fontWeight: selectedAltIdx === i ? 600 : 400,
              }}
            >
              {alt.label}
            </button>
          ))}
        </div>
      )}

      {/* Legacy: Findings without render_decision (DR/AP try-run, execute_analysis) */}
      {findings && !renderDecision && (
        <div style={{ background: "#fff", padding: 16, borderRadius: 8, marginBottom: 16, color: "#2d3748" }}>
          <RenderMiddleware
            findings={findings as LocalSkillFindings}
            outputSchema={outputSchema}
            charts={chartList as LocalChartDSL[] | null}
          />
        </div>
      )}

      {/* Legacy: chart-only (no findings, no render_decision) */}
      {!findings && !renderDecision && chartList && chartList.length > 0 && (
        <div style={{ background: "#fff", padding: 16, borderRadius: 8, marginBottom: 16 }}>
          <ChartListRenderer charts={chartList as LocalChartDSL[]} />
        </div>
      )}

      {/* Legacy visualization (vega-lite / kpi-card / plotly) — only if no chartList */}
      {useLegacyViz && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 8 }}>
          {contract.visualization.map((viz) => (
            <div key={viz.id}>
              <VisualizationRenderer item={viz} />
            </div>
          ))}
        </div>
      )}

      {/* Evidence Chain (now with python_code + step output) */}
      <EvidenceChain items={contract.evidence_chain} />

      {/* Suggested Actions */}
      <SuggestedActions actions={contract.suggested_actions} onTrigger={handleAction} />
    </div>
  );
}
