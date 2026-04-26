"use client";

/**
 * PipelineWorkspace — v1.5 dashboard centerpiece.
 *
 * Replaces the old "empty dashboard while chat builds + floating
 * PipelineResultsPanel" pattern. Single inline column showing:
 *   1. Mini Pipeline Canvas (read-only) — drawn live by Glass Box agent
 *   2. Inline Results — alert banner + charts + evidence
 *   3. Takeover card — "edit in Pipeline Builder" / failure path
 *
 * AppShell owns the data; this component is purely presentational.
 */

import { useRouter } from "next/navigation";
import type { PipelineJSON, PipelineResultSummary, NodeResult } from "@/lib/pipeline-builder/types";
import MiniPipelineCanvas, { type MiniCanvasStatus } from "./MiniPipelineCanvas";
import ResultsBody from "../pipeline-builder/ResultsBody";

interface Props {
  pipelineJson: PipelineJSON | null;
  highlightNodeId: string | null;
  runStatuses: Record<string, "success" | "failed" | "skipped" | null>;
  canvasStatus: MiniCanvasStatus;
  summary: PipelineResultSummary | null;
  nodeResults: Record<string, NodeResult>;
  runError: string | null;
  durationMs: number | null;
  /** Reset workspace (clears pipeline + results). Called when user starts a fresh chat. */
  onReset?: () => void;
}

export default function PipelineWorkspace({
  pipelineJson,
  highlightNodeId,
  runStatuses,
  canvasStatus,
  summary,
  nodeResults,
  runError,
  durationMs,
  onReset,
}: Props) {
  const router = useRouter();
  const hasPipeline = (pipelineJson?.nodes?.length ?? 0) > 0;

  const onEditInBuilder = () => {
    if (!pipelineJson) return;
    try {
      sessionStorage.setItem(
        "pb:ephemeral_pipeline",
        JSON.stringify({ pipeline_json: pipelineJson, ts: Date.now() }),
      );
      router.push("/admin/pipeline-builder/new?from=agent");
    } catch {
      router.push("/admin/pipeline-builder/new");
    }
  };

  return (
    <div
      data-testid="pipeline-workspace"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        padding: 16,
        height: "100%",
        overflowY: "auto",
        background: "#F3F4F6",
      }}
    >
      <Header
        canvasStatus={canvasStatus}
        nodeCount={pipelineJson?.nodes.length ?? 0}
        edgeCount={pipelineJson?.edges.length ?? 0}
        durationMs={durationMs}
        canReset={hasPipeline}
        onReset={onReset}
      />

      <div
        style={{
          background: "#fff",
          border: "1px solid #E5E7EB",
          borderRadius: 10,
          padding: 12,
        }}
      >
        <CanvasHeader status={canvasStatus} nodeCount={pipelineJson?.nodes.length ?? 0} />
        <MiniPipelineCanvas
          pipelineJson={pipelineJson}
          highlightNodeId={highlightNodeId}
          runStatuses={runStatuses}
          status={canvasStatus}
          height={canvasStatus === "done" || canvasStatus === "error" ? 220 : 300}
        />
      </div>

      {summary && (
        <div
          style={{
            background: "#fff",
            border: "1px solid #E5E7EB",
            borderRadius: 10,
            padding: 14,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 10,
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600, color: "#111827" }}>📊 Pipeline 結果</div>
            <div style={{ fontSize: 12, color: "#6B7280" }}>
              {summary.charts.length} charts · {summary.evidence_rows} evidence rows
              {durationMs != null && ` · ${(durationMs / 1000).toFixed(1)}s`}
            </div>
          </div>
          <ResultsBody summary={summary} nodeResults={nodeResults} />
        </div>
      )}

      {canvasStatus === "error" && runError && (
        <FailureCard message={runError} />
      )}

      {hasPipeline && (canvasStatus === "done" || canvasStatus === "error") && (
        <TakeoverCard isError={canvasStatus === "error"} onClick={onEditInBuilder} />
      )}
    </div>
  );
}

function Header({
  canvasStatus,
  nodeCount,
  edgeCount,
  durationMs,
  canReset,
  onReset,
}: {
  canvasStatus: MiniCanvasStatus;
  nodeCount: number;
  edgeCount: number;
  durationMs: number | null;
  canReset: boolean;
  onReset?: () => void;
}) {
  const subtitle = (() => {
    if (canvasStatus === "idle") return "透過右側 AI Agent 對話，會在此即時繪製 pipeline 並執行";
    if (canvasStatus === "building") return `Agent 正在繪製… ${nodeCount} nodes / ${edgeCount} edges`;
    if (canvasStatus === "done") {
      const sec = durationMs != null ? `（耗時 ${(durationMs / 1000).toFixed(1)}s）` : "";
      return `已完成 ${sec}`;
    }
    if (canvasStatus === "error") return "執行過程出現錯誤，可套用 Agent 修補建議或自行接手";
    return "";
  })();

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div>
        <div style={{ fontSize: 16, fontWeight: 600, color: "#111827" }}>🧱 Pipeline Workspace</div>
        <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>{subtitle}</div>
      </div>
      <div style={{ flex: 1 }} />
      {canReset && onReset && (
        <button
          onClick={onReset}
          style={{
            fontSize: 12,
            background: "#fff",
            border: "1px solid #D1D5DB",
            borderRadius: 6,
            padding: "5px 10px",
            color: "#374151",
            cursor: "pointer",
          }}
        >
          🗙 清除
        </button>
      )}
    </div>
  );
}

function CanvasHeader({ status, nodeCount }: { status: MiniCanvasStatus; nodeCount: number }) {
  const pill = (() => {
    switch (status) {
      case "idle":
        return { text: "尚未開始", bg: "#F9FAFB", color: "#9CA3AF", border: "#E5E7EB" };
      case "building":
        return { text: `⏱ 建構中… ${nodeCount} nodes`, bg: "#EFF6FF", color: "#1D4ED8", border: "#BFDBFE" };
      case "done":
        return { text: "✓ 完成", bg: "#ECFDF5", color: "#047857", border: "#A7F3D0" };
      case "error":
        return { text: "✕ 失敗", bg: "#FEF2F2", color: "#B91C1C", border: "#FECACA" };
    }
  })();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 10,
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: "#374151" }}>📐 Canvas</div>
      <div
        style={{
          fontSize: 11,
          padding: "2px 8px",
          borderRadius: 12,
          background: pill.bg,
          color: pill.color,
          border: `1px solid ${pill.border}`,
        }}
      >
        {pill.text}
      </div>
    </div>
  );
}

function FailureCard({ message }: { message: string }) {
  return (
    <div
      style={{
        background: "#FEF2F2",
        border: "1px solid #FECACA",
        borderRadius: 10,
        padding: 14,
      }}
    >
      <div style={{ fontWeight: 600, color: "#991B1B", fontSize: 13 }}>❌ 執行失敗</div>
      <div style={{ fontSize: 12, color: "#7F1D1D", marginTop: 4, lineHeight: 1.5 }}>{message}</div>
    </div>
  );
}

function TakeoverCard({ isError, onClick }: { isError: boolean; onClick: () => void }) {
  const accent = isError
    ? { bg: "#FEF2F2", border: "#FECACA", title: "#991B1B", body: "#7F1D1D", link: "#B91C1C" }
    : { bg: "#FFF7ED", border: "#FDBA74", title: "#9A3412", body: "#9A3412", link: "#C2410C" };
  return (
    <div
      style={{
        background: accent.bg,
        border: `1px solid ${accent.border}`,
        borderRadius: 10,
        padding: "12px 14px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
      }}
    >
      <div style={{ fontSize: 13, color: accent.body }}>
        {isError ? "🛠 " : "📝 "}
        <b style={{ color: accent.title }}>
          {isError ? "不想讓 Agent 自動修？" : "需要調整這條 pipeline？"}
        </b>
        <div style={{ fontSize: 12, marginTop: 2 }}>
          {isError
            ? "在 Pipeline Builder 直接打開這條 pipeline 自己改"
            : "改 chart 樣式、加 filter、換時間範圍…"}
        </div>
      </div>
      <button
        onClick={onClick}
        style={{
          background: "transparent",
          border: "none",
          color: accent.link,
          fontWeight: 600,
          fontSize: 13,
          cursor: "pointer",
          whiteSpace: "nowrap",
        }}
      >
        {isError ? "在 Pipeline Builder 自己改 →" : "在 Pipeline Builder 開啟編輯 →"}
      </button>
    </div>
  );
}
