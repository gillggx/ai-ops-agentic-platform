"use client";

/**
 * Phase 9-C — confirmation card for the chat agent's `propose_personal_rule`
 * tool output. Displays the rule draft + 3-fire preview + a "儲存規則" button
 * that POSTs the same draft to /api/v1/rules so the create is owned by the
 * authenticated user (not the agent's service token).
 */

import { useState } from "react";

interface RuleDraft {
  name: string;
  description?: string;
  kind: "personal_briefing" | "weekly_report" | "saved_query" | "watch_rule";
  schedule_cron: string | null;
  pipeline_json: Record<string, unknown>;
  notification_channels?: Array<{ type: string }>;
  notification_template?: string | null;
}

interface PreviewRun {
  status?: string;                   // success | failed | skipped
  result_summary?: string | null;
  duration_ms?: number;
  nodes?: Array<{
    node?: string;
    status?: string;
    rows?: number | null;
    duration_ms?: number;
    columns?: string[] | null;
    rows_total?: number | null;
  }>;
}

interface RulePreview {
  pipeline_summary?: string;
  node_count?: number;
  next_3_fires?: string[];
  schedule_human?: string;
  preview_run?: PreviewRun;
}

interface Props {
  ruleDraft: RuleDraft;
  preview: RulePreview;
  onSaved?: (rule: { id: number; name: string }) => void;
}

const KIND_LABEL: Record<string, string> = {
  personal_briefing: "每日 briefing",
  weekly_report: "每週報告",
  saved_query: "儲存查詢",
  watch_rule: "條件觸發",
};

export function RuleProposalCard({ ruleDraft, preview, onSaved }: Props) {
  const [name, setName] = useState(ruleDraft.name);
  const [template, setTemplate] = useState(ruleDraft.notification_template || "");
  const [saving, setSaving] = useState(false);
  const [savedId, setSavedId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onConfirm = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch("/api/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          description: ruleDraft.description ?? "",
          kind: ruleDraft.kind,
          schedule_cron: ruleDraft.schedule_cron,
          pipeline_json: JSON.stringify(ruleDraft.pipeline_json),
          notification_channels: JSON.stringify(ruleDraft.notification_channels ?? [{ type: "in_app" }]),
          notification_template: template || null,
        }),
      });
      const body = await res.json();
      if (!res.ok || body?.ok === false) {
        throw new Error(body?.error?.message || `HTTP ${res.status}`);
      }
      const created = body.data ?? body;
      setSavedId(created.id);
      onSaved?.({ id: created.id, name: created.name });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  if (savedId) {
    return (
      <div style={cardStyle}>
        <div style={{ color: "#48bb78", fontSize: 13, fontWeight: 600 }}>
          ✓ 規則已儲存（id={savedId}）
        </div>
        <div style={{ color: "#a0aec0", fontSize: 12, marginTop: 4 }}>
          下次觸發時會推播到鈴鐺 · 可在 <a href="/rules" style={{ color: "#63b3ed" }}>/rules</a> 管理
        </div>
      </div>
    );
  }

  return (
    <div style={cardStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", color: "#a0aec0", textTransform: "uppercase" }}>
          🔔 RULE PROPOSAL · {KIND_LABEL[ruleDraft.kind] ?? ruleDraft.kind}
        </span>
      </div>

      <div style={{ marginBottom: 10 }}>
        <label style={lblStyle}>名稱</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={inputStyle}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
        <div>
          <label style={lblStyle}>排程 cron</label>
          <div style={fieldStyle}>{ruleDraft.schedule_cron ?? "(saved query — 手動觸發)"}</div>
        </div>
        <div>
          <label style={lblStyle}>頻率說明</label>
          <div style={fieldStyle}>{preview.schedule_human ?? "—"}</div>
        </div>
      </div>

      <div style={{ marginBottom: 10 }}>
        <label style={lblStyle}>Pipeline ({preview.node_count ?? 0} blocks)</label>
        <div style={{ ...fieldStyle, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11 }}>
          {preview.pipeline_summary ?? "(empty)"}
        </div>
      </div>

      {(preview.next_3_fires?.length ?? 0) > 0 && (
        <div style={{ marginBottom: 10 }}>
          <label style={lblStyle}>下次 3 個觸發時間</label>
          <ul style={{ margin: 0, paddingLeft: 18, color: "#cbd5e0", fontSize: 12, fontFamily: "ui-monospace, Menlo, monospace" }}>
            {preview.next_3_fires!.map((t, i) => <li key={i}>{t}</li>)}
          </ul>
        </div>
      )}

      {/* Preview run output — show the user what THIS rule will produce
          before they commit. Phase 9-fix: always rendered when present so
          schedule-first flow (case 2) gets verification surface. */}
      {preview.preview_run && (
        <div style={{ marginBottom: 10 }}>
          <label style={lblStyle}>
            預覽輸出 ({preview.preview_run.status === "success" ? "✓" : "⚠"} status: {preview.preview_run.status ?? "—"}
            {preview.preview_run.duration_ms != null && `, ${preview.preview_run.duration_ms}ms`})
          </label>
          {preview.preview_run.result_summary && (
            <div style={{ ...fieldStyle, marginBottom: 6 }}>
              {preview.preview_run.result_summary}
            </div>
          )}
          {(preview.preview_run.nodes?.length ?? 0) > 0 && (
            <div style={{
              background: "#0d1117",
              border: "1px solid #2d3748",
              borderRadius: 4,
              padding: "6px 8px",
              fontSize: 11,
              fontFamily: "ui-monospace, Menlo, monospace",
              color: "#cbd5e0",
            }}>
              {preview.preview_run.nodes!.map((n, i) => (
                <div key={i} style={{ display: "flex", gap: 8, padding: "2px 0", borderBottom: i < preview.preview_run!.nodes!.length - 1 ? "1px dashed #2d3748" : "none" }}>
                  <span style={{ color: n.status === "success" ? "#48bb78" : "#fc8181", minWidth: 14 }}>
                    {n.status === "success" ? "✓" : "✗"}
                  </span>
                  <span style={{ color: "#a0aec0", minWidth: 60 }}>{n.node ?? "?"}</span>
                  <span style={{ color: "#cbd5e0" }}>
                    {n.rows != null ? `${n.rows} rows` : "—"}
                    {n.rows_total != null && n.rows_total !== n.rows ? ` / ${n.rows_total} total` : ""}
                    {n.columns?.length ? `  cols: ${n.columns.slice(0, 4).join(", ")}${n.columns.length > 4 ? `…+${n.columns.length - 4}` : ""}` : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ marginBottom: 10 }}>
        <label style={lblStyle}>推播訊息模板（可選）</label>
        <textarea
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
          rows={2}
          placeholder="例：上週 OOC top-5: {top_tools}"
          style={{ ...inputStyle, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12, resize: "vertical" }}
        />
      </div>

      {error && (
        <div style={{ background: "#742a2a", border: "1px solid #c53030", borderRadius: 4, padding: "8px 10px", marginBottom: 10, color: "#fed7d7", fontSize: 12 }}>
          ⚠ 儲存失敗：{error}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button
          disabled={saving}
          onClick={onConfirm}
          style={{
            padding: "6px 14px",
            background: saving ? "#2d3748" : "#3182ce",
            color: "white",
            border: "none",
            borderRadius: 4,
            cursor: saving ? "wait" : "pointer",
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          {saving ? "儲存中…" : "💾 儲存規則"}
        </button>
      </div>
    </div>
  );
}

const cardStyle: React.CSSProperties = {
  background: "#1a202c",
  border: "1px solid #2d3748",
  borderRadius: 8,
  padding: "12px 14px",
  margin: "4px 0",
  color: "#e2e8f0",
  fontSize: 13,
};

const lblStyle: React.CSSProperties = {
  display: "block",
  fontSize: 10,
  letterSpacing: "0.08em",
  color: "#a0aec0",
  marginBottom: 3,
  textTransform: "uppercase",
  fontWeight: 600,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "5px 8px",
  background: "#0d1117",
  color: "#e2e8f0",
  border: "1px solid #2d3748",
  borderRadius: 4,
  fontSize: 13,
};

const fieldStyle: React.CSSProperties = {
  padding: "5px 8px",
  background: "#0d1117",
  border: "1px solid #2d3748",
  borderRadius: 4,
  fontSize: 12,
  color: "#cbd5e0",
};
