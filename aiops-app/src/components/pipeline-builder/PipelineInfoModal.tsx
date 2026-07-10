"use client";

import { useEffect, useState } from "react";
import { useBuilder } from "@/context/pipeline-builder/BuilderContext";

interface Props {
  open: boolean;
  onClose: () => void;
  readOnly?: boolean;
}

type EditableKind = "auto_patrol" | "auto_check" | "skill";

export default function PipelineInfoModal({ open, onClose, readOnly }: Props) {
  const { state, actions } = useBuilder();
  const [nameDraft, setNameDraft] = useState(state.pipeline.name);
  const [descDraft, setDescDraft] = useState(state.description);
  // Phase 5-UX-7: kind is mutable while draft/validating.
  const currentKind = state.meta.pipelineKind as EditableKind | "diagnostic" | null;
  const [kindDraft, setKindDraft] = useState<EditableKind>(
    (currentKind === "auto_patrol" || currentKind === "auto_check" || currentKind === "skill")
      ? currentKind
      : "skill"
  );
  const [kindSaving, setKindSaving] = useState(false);
  const [kindError, setKindError] = useState<string | null>(null);

  // Kind is read-only (and requires clone) once pipeline is locked/active/archived.
  const statusAllowsKindChange = state.meta.status === "draft" || state.meta.status === "validating";
  const canEditKind = !readOnly && statusAllowsKindChange && state.meta.pipelineId != null;

  useEffect(() => {
    if (open) {
      setNameDraft(state.pipeline.name);
      setDescDraft(state.description);
      const k = state.meta.pipelineKind;
      if (k === "auto_patrol" || k === "auto_check" || k === "skill") setKindDraft(k);
      setKindError(null);
    }
  }, [open, state.pipeline.name, state.description, state.meta.pipelineKind]);

  if (!open) return null;

  const dirty =
    nameDraft !== state.pipeline.name || descDraft !== state.description;
  const kindDirty = canEditKind && currentKind !== kindDraft;

  const handleSave = async () => {
    const trimmedName = nameDraft.trim();
    if (!trimmedName) return;
    if (trimmedName !== state.pipeline.name) actions.renamePipeline(trimmedName);
    if (descDraft !== state.description) actions.setDescription(descDraft);
    // Phase 5-UX-7: persist kind change via PUT (separate from auto-save because
    // it requires a server round-trip to run per-kind validation at publish time).
    if (kindDirty && state.meta.pipelineId != null) {
      setKindSaving(true);
      setKindError(null);
      try {
        const res = await fetch(`/api/pipeline-builder/pipelines/${state.meta.pipelineId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pipeline_kind: kindDraft }),
        });
        if (!res.ok) {
          const text = await res.text().catch(() => "");
          throw new Error(`kind 改為 ${kindDraft} 失敗 (${res.status}): ${text.slice(0, 200)}`);
        }
        const rec = await res.json();
        // Reflect new kind locally; full reload handled by caller if needed.
        if (rec.pipeline_kind) {
          actions.init({ ...rec, pipeline_json: rec.pipeline_json ?? state.pipeline });
        }
      } catch (e) {
        setKindError((e as Error).message);
        setKindSaving(false);
        return;
      }
      setKindSaving(false);
    }
    onClose();
  };

  return (
    <div
      data-testid="pipeline-info-modal"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,23,42,0.45)",
        zIndex: 3000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 520,
          maxWidth: "90vw",
          background: "#fff",
          borderRadius: 8,
          boxShadow: "0 8px 24px rgba(15,23,42,0.18)",
          padding: 20,
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", marginBottom: 14 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: "#0F172A" }}>
            Pipeline Info
          </div>
          <div style={{ marginLeft: "auto", fontSize: 11, color: "#64748B" }}>
            {state.meta.pipelineId != null ? `#${state.meta.pipelineId}` : "未儲存"} · {state.meta.status}
          </div>
        </div>

        <div style={{ marginBottom: 14 }}>
          <label
            style={{
              display: "block",
              fontSize: 11,
              fontWeight: 600,
              color: "#475569",
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              marginBottom: 4,
            }}
          >
            名稱 <span style={{ color: "#DC2626" }}>*</span>
          </label>
          <input
            data-testid="info-modal-name"
            type="text"
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            disabled={readOnly}
            maxLength={120}
            style={{
              width: "100%",
              padding: "7px 10px",
              fontSize: 13,
              border: "1px solid #CBD5E1",
              borderRadius: 4,
              outline: "none",
              background: readOnly ? "#F1F5F9" : "#fff",
            }}
          />
        </div>

        <div style={{ marginBottom: 14 }}>
          <label
            style={{
              display: "block",
              fontSize: 11,
              fontWeight: 600,
              color: "#475569",
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              marginBottom: 4,
            }}
          >
            Pipeline 類型
            <span style={{ marginLeft: 8, fontSize: 10, color: "#94A3B8", fontWeight: 400, textTransform: "none" }}>
              {canEditKind
                ? "可變更（draft / validating 階段）；lock 後要 clone"
                : `凍結於 ${state.meta.status}（要改需 Clone）`}
            </span>
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 }}>
            {(["auto_patrol", "auto_check", "skill"] as const).map((k) => {
              const active = kindDraft === k;
              const labelMap: Record<EditableKind, string> = {
                auto_patrol: "🔍 Auto Patrol",
                auto_check: "⚡ Auto-Check",
                skill: "🩺 Skill",
              };
              return (
                <button
                  key={k}
                  onClick={() => canEditKind && setKindDraft(k)}
                  disabled={!canEditKind}
                  style={{
                    padding: "6px 8px",
                    fontSize: 11,
                    fontWeight: active ? 600 : 500,
                    background: active ? "var(--pl, #EEF2FF)" : "#fff",
                    color: active ? "var(--pd, #4338CA)" : "#475569",
                    border: `1px solid ${active ? "var(--pd, #4338CA)" : "#CBD5E1"}`,
                    borderRadius: 4,
                    cursor: canEditKind ? "pointer" : "not-allowed",
                    opacity: canEditKind ? 1 : 0.55,
                  }}
                >
                  {labelMap[k]}
                </button>
              );
            })}
          </div>
          {kindDirty && (
            <div style={{ marginTop: 6, fontSize: 10, color: "#B45309" }}>
              ⚠ 改 kind 會重新驗證結構（e.g. skill→auto_check 需要 inputs + block_alert/chart）。
              lock 之前若不通過會退回 draft。
            </div>
          )}
          {kindError && (
            <div style={{ marginTop: 6, fontSize: 10, color: "#B91C1C" }}>{kindError}</div>
          )}
        </div>

        <div style={{ marginBottom: 14 }}>
          <label
            style={{
              display: "block",
              fontSize: 11,
              fontWeight: 600,
              color: "#475569",
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              marginBottom: 4,
            }}
          >
            描述
            <span style={{ marginLeft: 8, fontSize: 10, color: "#94A3B8", fontWeight: 400, textTransform: "none" }}>
              這段描述會作為 Agent RAG 檢索依據，越具體越好
            </span>
          </label>
          <textarea
            data-testid="info-modal-description"
            value={descDraft}
            onChange={(e) => setDescDraft(e.target.value)}
            disabled={readOnly}
            rows={5}
            maxLength={2000}
            placeholder="例如：偵測 TOOL 最近 5 次 process 是否出現 ≥2 次 OOC；輸入 tool_id，輸出 alert + table"
            style={{
              width: "100%",
              padding: "8px 10px",
              fontSize: 13,
              border: "1px solid #CBD5E1",
              borderRadius: 4,
              outline: "none",
              background: readOnly ? "#F1F5F9" : "#fff",
              fontFamily: "inherit",
              resize: "vertical",
              lineHeight: 1.5,
            }}
          />
          <div style={{ marginTop: 4, fontSize: 10, color: "#94A3B8", textAlign: "right" }}>
            {descDraft.length} / 2000
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button
            onClick={onClose}
            style={{
              padding: "6px 14px",
              fontSize: 12,
              background: "#fff",
              color: "#475569",
              border: "1px solid #CBD5E1",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            取消
          </button>
          <button
            data-testid="info-modal-save"
            onClick={handleSave}
            disabled={readOnly || !nameDraft.trim() || (!dirty && !kindDirty) || kindSaving}
            style={{
              padding: "6px 14px",
              fontSize: 12,
              background: "var(--p, #4F46E5)",
              color: "#fff",
              border: "1px solid var(--p, #4F46E5)",
              borderRadius: 4,
              cursor: readOnly || !nameDraft.trim() || (!dirty && !kindDirty) || kindSaving ? "not-allowed" : "pointer",
              opacity: readOnly || !nameDraft.trim() || (!dirty && !kindDirty) || kindSaving ? 0.5 : 1,
              fontWeight: 600,
            }}
          >
            {kindSaving ? "儲存中…" : "確認"}
          </button>
        </div>
      </div>
    </div>
  );
}
