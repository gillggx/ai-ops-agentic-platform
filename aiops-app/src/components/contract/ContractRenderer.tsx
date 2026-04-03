"use client";

import type { ComponentType } from "react";
import type { AIOpsReportContract, SuggestedAction, VisualizationItem } from "aiops-contract";
import { isAgentAction, isHandoffAction } from "aiops-contract";
import { EvidenceChain } from "./EvidenceChain";
import { SuggestedActions } from "./SuggestedActions";
import { VegaLiteChart } from "./visualizations/VegaLiteChart";
import { KpiCard } from "./visualizations/KpiCard";
import { UnsupportedPlaceholder } from "./visualizations/UnsupportedPlaceholder";
import { PlotlyVisualization } from "./visualizations/PlotlyVisualization";

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
  function handleAction(action: SuggestedAction) {
    if (isAgentAction(action)) {
      onAgentMessage?.(action.message);
    } else if (isHandoffAction(action)) {
      onHandoff?.(action.mcp, action.params);
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

      {/* Visualizations */}
      {contract.visualization.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 8 }}>
          {contract.visualization.map((viz) => (
            <div key={viz.id}>
              <VisualizationRenderer item={viz} />
            </div>
          ))}
        </div>
      )}

      {/* Evidence Chain */}
      <EvidenceChain items={contract.evidence_chain} />

      {/* Suggested Actions */}
      <SuggestedActions actions={contract.suggested_actions} onTrigger={handleAction} />
    </div>
  );
}
