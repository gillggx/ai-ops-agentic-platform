"use client";

/**
 * PbPipelineCard — inline render for Phase 5 build_pipeline results in chat.
 *
 * Renders:
 *   - Compact header with node count + triggered/not-triggered badge
 *   - Evidence rows (if triggered)
 *   - Chart list (reuses ChartRenderer — same look as PipelineResultsPanel)
 *   - DataView tables (block_data_view outputs)
 *   - Action buttons: Save as Skill / Edit in Builder
 *
 * Shared between two card types:
 *   - type="pb_pipeline"           — ad-hoc DAG the LLM just built (has pipeline_json)
 *   - type="pb_pipeline_published" — invoke of existing published skill (no pipeline_json)
 */

import { useState } from "react";
import ChartRenderer from "@/components/pipeline-builder/ChartRenderer";
import DataResultView from "@/components/common/DataResultView";
import SkillParameterizeModal, { type SkillDoc } from "@/components/skills-v2/SkillParameterizeModal";
import type {
  NodeResult,
  PipelineResultSummary,
  PipelineJSON,
  PipelineChartSummary,
  PipelineDataView,
} from "@/lib/pipeline-builder/types";

type ChartView = "stacked" | "grid" | "tabs";

export interface PbPipelineAdHocCard {
  type: "pb_pipeline";
  pipeline_json: PipelineJSON;
  inputs?: Record<string, unknown>;
  node_results: Record<string, NodeResult>;
  result_summary: PipelineResultSummary | null;
  run_id?: number | null;
  /** The user's original NL prompt that produced this pipeline (intent prefix
   *  already stripped). Threaded from AIAgentPanel so 存為 Skill can record it
   *  as the skill's natural-language description instead of losing it. */
  goal?: string;
}

export interface PbPipelinePublishedCard {
  type: "pb_pipeline_published";
  slug?: string;
  skill_name?: string;
  charts: PipelineChartSummary[];
  triggered?: boolean;
  evidence_rows?: number;
  run_id?: number | null;
}

export type PbPipelineCardData = PbPipelineAdHocCard | PbPipelinePublishedCard;

interface Props {
  card: PbPipelineCardData;
  /** Phase 5-UX-5: optional "↗ 展開 canvas" button; fires when user wants the
   *  full BuilderLayout overlay to mount on top of the current page. */
  onExpand?: (card: PbPipelineCardData) => void;
  /** 2026-07-08 (issue#1): compact mode — the charts/tables already live in
   *  the Lite Canvas overlay, so skip re-rendering them here but KEEP the
   *  header + ActionBar (存為 Skill / Edit in Builder). Without this, builds
   *  that stream into Lite Canvas lost the 存為 Skill button entirely. */
  compact?: boolean;
}

export default function PbPipelineCard({ card, onExpand, compact = false }: Props) {
  const isAdHoc = card.type === "pb_pipeline";

  // Resolve charts + data_views + evidence from whichever shape we got
  const charts: PipelineChartSummary[] = isAdHoc
    ? (card.result_summary?.charts ?? [])
    : card.charts;
  const dataViews: PipelineDataView[] = isAdHoc
    ? (card.result_summary?.data_views ?? [])
    : [];
  const triggered = isAdHoc ? !!card.result_summary?.triggered : !!card.triggered;
  const evidenceRows = isAdHoc ? (card.result_summary?.evidence_rows ?? 0) : (card.evidence_rows ?? 0);

  const nodeCount = isAdHoc ? (card.pipeline_json.nodes?.length ?? 0) : 0;
  const edgeCount = isAdHoc ? (card.pipeline_json.edges?.length ?? 0) : 0;
  const pipelineName = isAdHoc ? (card.pipeline_json.name || "Ad-hoc Pipeline") : (card.skill_name || card.slug || "Published Skill");

  return (
    <div
      style={{
        width: "100%",
        maxWidth: "100%",
        border: "1px solid #E2E8F0",
        borderRadius: 8,
        background: "#fff",
        overflow: "hidden",
        fontFamily: "Inter, system-ui, -apple-system, 'Noto Sans TC', sans-serif",
        marginTop: 4,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 12px",
          borderBottom: "1px solid #E2E8F0",
          background: "#F8FAFC",
        }}
      >
        <span style={{ fontSize: 9.5, fontWeight: 700, color: "#4F46E5", background: "#EEF2FF",
                       padding: "1px 6px", borderRadius: 4, letterSpacing: 0.5 }}>
          {isAdHoc ? "PIPELINE" : "SKILL"}
        </span>
        <span style={{ fontSize: 12, fontWeight: 600, color: "#0F172A", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {pipelineName}
        </span>
        {isAdHoc && (
          <span style={{ fontSize: 10, color: "#64748B" }}>
            {nodeCount} nodes · {edgeCount} edges
          </span>
        )}
        <TriggeredBadge triggered={triggered} />
        {isAdHoc && onExpand && (
          <button
            onClick={() => onExpand(card)}
            style={{
              padding: "3px 10px",
              fontSize: 10,
              fontWeight: 600,
              border: "1px solid #2B6CB0",
              borderRadius: 10,
              background: "#2B6CB0",
              color: "#fff",
              cursor: "pointer",
              flexShrink: 0,
            }}
            title="展開成全螢幕 canvas，可編輯/重跑"
          >
            ↗ 展開 canvas
          </button>
        )}
      </div>

      {/* Compact mode: charts/tables are already in Lite Canvas — just note it. */}
      {compact && (
        <div style={{ padding: "6px 12px", fontSize: 11, color: "#64748B", borderTop: "1px solid #F1F5F9" }}>
          結果已呈現在 Lite Canvas。
        </div>
      )}

      {/* Charts */}
      {!compact && charts.length > 0 && (
        <ChartList charts={charts} />
      )}

      {/* DataViews */}
      {!compact && dataViews.length > 0 && (
        <div style={{ padding: "8px 12px", borderTop: "1px solid #F1F5F9" }}>
          {dataViews.map((dv, i) => (
            <DataViewTable key={i} dv={dv}
              pipelineJson={isAdHoc ? card.pipeline_json : null} />
          ))}
        </div>
      )}

      {/* Evidence hint */}
      {!compact && triggered && evidenceRows > 0 && (
        <div style={{ padding: "6px 12px", fontSize: 11, color: "#B91C1C", background: "#FEF2F2", borderTop: "1px solid #FECACA" }}>
          [!] 觸發條件命中 · {evidenceRows} 筆佐證事件
        </div>
      )}

      {/* Actions — always shown, incl. compact (this restores 存為 Skill) */}
      <ActionBar card={card} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function TriggeredBadge({ triggered }: { triggered: boolean }) {
  const style: React.CSSProperties = {
    fontSize: 10,
    padding: "2px 8px",
    borderRadius: 10,
    fontWeight: 600,
    border: "1px solid",
    ...(triggered
      ? { background: "#FEF2F2", color: "#B91C1C", borderColor: "#FECACA" }
      : { background: "#F0FDF4", color: "#166534", borderColor: "#BBF7D0" }),
  };
  return <span style={style}>{triggered ? "Triggered" : "OK"}</span>;
}

function ChartList({ charts }: { charts: PipelineChartSummary[] }) {
  const [view, setView] = useState<ChartView>(charts.length <= 1 ? "stacked" : "grid");
  const [activeIdx, setActiveIdx] = useState(0);

  return (
    <div style={{ padding: "8px 12px" }}>
      {charts.length >= 2 && (
        <div style={{ display: "flex", gap: 4, marginBottom: 8, justifyContent: "flex-end" }}>
          {(["stacked", "grid", "tabs"] as ChartView[]).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              style={{
                padding: "3px 8px",
                fontSize: 10,
                border: "1px solid #E2E8F0",
                borderRadius: 4,
                background: view === v ? "#2B6CB0" : "#fff",
                color: view === v ? "#fff" : "#64748B",
                cursor: "pointer",
                fontWeight: view === v ? 600 : 400,
              }}
            >
              {v === "stacked" ? "堆疊" : v === "grid" ? "Grid" : "Tabs"}
            </button>
          ))}
        </div>
      )}

      {view === "tabs" ? (
        <>
          <div style={{ display: "flex", gap: 4, borderBottom: "1px solid #E2E8F0", marginBottom: 8 }}>
            {charts.map((c, i) => (
              <button
                key={i}
                onClick={() => setActiveIdx(i)}
                style={{
                  padding: "4px 10px",
                  fontSize: 11,
                  border: "none",
                  borderBottom: activeIdx === i ? "2px solid #2B6CB0" : "2px solid transparent",
                  background: "transparent",
                  color: activeIdx === i ? "#2B6CB0" : "#64748B",
                  cursor: "pointer",
                  fontWeight: activeIdx === i ? 600 : 400,
                }}
              >
                {c.title || `Chart ${i + 1}`}
              </button>
            ))}
          </div>
          <ChartCell chart={charts[activeIdx]} height={280} />
        </>
      ) : view === "grid" ? (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {charts.map((c, i) => <ChartCell key={i} chart={c} height={220} />)}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {charts.map((c, i) => <ChartCell key={i} chart={c} height={260} />)}
        </div>
      )}
    </div>
  );
}

function ChartCell({ chart, height }: { chart: PipelineChartSummary; height: number }) {
  return (
    <div style={{ border: "1px solid #F1F5F9", borderRadius: 4, overflow: "hidden" }}>
      {chart.title && (
        <div style={{ padding: "4px 8px", fontSize: 11, fontWeight: 600, color: "#0F172A", borderBottom: "1px solid #F1F5F9", background: "#FAFBFC" }}>
          {chart.title}
        </div>
      )}
      <ChartRenderer spec={chart.chart_spec} height={height} />
    </div>
  );
}

function DataViewTable({ dv, pipelineJson }: { dv: PipelineDataView; pipelineJson?: unknown }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "#0F172A", marginBottom: 4 }}>
        {dv.title} <span style={{ color: "#94A3B8", fontWeight: 400 }}>({dv.total_rows} rows)</span>
      </div>
      <div style={{ height: 260, display: "flex", flexDirection: "column" }}>
        <DataResultView
          result={dv.rows}
          enableFullscreen={false}
          emptyText="無資料"
          totalRows={dv.total_rows}
          exportSpec={pipelineJson ? { pipelineJson, nodeId: dv.node_id } : null}
        />
      </div>
    </div>
  );
}

function ActionBar({ card }: { card: PbPipelineCardData }) {
  const isAdHoc = card.type === "pb_pipeline";
  const adhoc = card.type === "pb_pipeline" ? card : null;  // TS narrowing for goal/pipeline_json
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  // 真 Skill 化 (2026-07-08): 存檔前走參數化精靈（開放參數 + 說明書）
  const [wizardOpen, setWizardOpen] = useState(false);
  const [pendingName, setPendingName] = useState<string>("");

  function handleSaveAsSkill() {
    if (!isAdHoc) return;
    const defaultName = card.pipeline_json.name || "Chat-built Pipeline";
    const name = window.prompt("儲存為 Skill（草稿）\n\n名稱：", defaultName);
    if (!name) return;
    setPendingName(name);
    setWizardOpen(true);
  }

  async function saveSkill(pj: Record<string, unknown>, doc: SkillDoc | null) {
    setWizardOpen(false);
    setSaving(true);
    try {
      // 2026-06-28: route through the v2 atomic endpoint (pipeline + skill +
      // bind in one txn). 2026-07-08: pipeline 已參數化、doc 為人審過的說明書。
      const res = await fetch("/api/skills-v2/with-pipeline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: pendingName,
          nl: adhoc?.goal ?? "",
          sub: adhoc?.goal ? adhoc.goal.slice(0, 60) : "從 Agent 對話建立",
          pipeline_json: pj,
          pipeline_kind: "skill",
          doc: doc ?? undefined,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(`建立 Skill 失敗：${err?.error?.message || err.detail || res.statusText}`);
        return;
      }
      const env = await res.json();
      const data = env?.data ?? env;
      const sid = data?.skill?.id;
      setSaved(true);
      if (sid && window.confirm(`Skill 已建好（草稿狀態）。\n\n要開啟 Editor 去 review + 啟用嗎？`)) {
        window.open(`/skills/${sid}`, "_blank");
      }
    } catch (e) {
      alert(`儲存失敗：${e instanceof Error ? e.message : "未知錯誤"}`);
    } finally {
      setSaving(false);
    }
  }

  function handleEditInBuilder() {
    if (!isAdHoc) return;
    // Stash ephemeral pipeline_json for the /new route to pick up
    try {
      sessionStorage.setItem("pb:ephemeral_pipeline", JSON.stringify({
        pipeline_json: card.pipeline_json,
        inputs: card.inputs ?? {},
        ts: Date.now(),
      }));
    } catch {
      // ignore quota errors
    }
    window.open("/admin/pipeline-builder/new?from=chat", "_blank");
  }

  return (
    <div style={{ display: "flex", gap: 8, padding: "8px 12px", borderTop: "1px solid #F1F5F9", background: "#FAFBFC" }}>
      {isAdHoc && (
        <SkillParameterizeModal
          open={wizardOpen}
          skillName={pendingName}
          nl={adhoc?.goal ?? ""}
          pipelineJson={(adhoc?.pipeline_json ?? {}) as unknown as Record<string, unknown>}
          onClose={() => setWizardOpen(false)}
          onConfirm={({ pipelineJson: pj, doc }) => { void saveSkill(pj, doc); }}
          confirmLabel="建立 Skill"
        />
      )}
      {isAdHoc && (
        <>
          <button
            onClick={handleEditInBuilder}
            style={actionBtnStyle("secondary")}
          >
            Edit in Builder
          </button>
          <button
            onClick={handleSaveAsSkill}
            disabled={saving || saved}
            style={actionBtnStyle(saved ? "done" : "primary")}
          >
            {saved ? "已儲存" : saving ? "儲存中…" : "存為 Skill"}
          </button>
        </>
      )}
      {!isAdHoc && card.slug && (
        <span style={{ fontSize: 11, color: "#64748B" }}>
          Skill: <code style={{ background: "#F1F5F9", padding: "1px 5px", borderRadius: 3 }}>{card.slug}</code>
        </span>
      )}
    </div>
  );
}

function actionBtnStyle(variant: "primary" | "secondary" | "done"): React.CSSProperties {
  const base: React.CSSProperties = {
    padding: "4px 10px",
    fontSize: 11,
    borderRadius: 4,
    cursor: "pointer",
    fontWeight: 500,
    border: "1px solid",
  };
  if (variant === "primary") {
    return { ...base, background: "#2B6CB0", color: "#fff", borderColor: "#2B6CB0" };
  }
  if (variant === "done") {
    return { ...base, background: "#F0FDF4", color: "#166534", borderColor: "#BBF7D0", cursor: "default" };
  }
  return { ...base, background: "#fff", color: "#4A5568", borderColor: "#CBD5E0" };
}
