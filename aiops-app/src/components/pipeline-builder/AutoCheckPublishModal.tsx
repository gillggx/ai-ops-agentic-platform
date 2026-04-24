"use client";

/**
 * Phase 5-UX-7: publish modal for `auto_check` pipelines.
 *
 * Auto-check pipelines fire when an alarm is created with a matching
 * `trigger_event`. This modal lets the user pick which event_types to bind,
 * and calls `/pipelines/{id}/publish-auto-check` which writes the bindings +
 * transitions the pipeline to `active`.
 *
 * No inputs-mapping UI — the pipeline's declared input names are matched
 * against alarm payload keys at runtime (see auto_check_dispatcher).
 */

import { useEffect, useMemo, useState } from "react";
import type { PipelineJSON } from "@/lib/pipeline-builder/types";

interface Props {
  open: boolean;
  onClose: () => void;
  pipelineId: number;
  pipelineName: string;
  pipelineJson: PipelineJSON;
  onPublished: (eventTypes: string[]) => void;
}

export default function AutoCheckPublishModal({
  open,
  onClose,
  pipelineId,
  pipelineName,
  pipelineJson,
  onPublished,
}: Props) {
  const [eventTypesText, setEventTypesText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);

  const declaredInputs = useMemo(() => pipelineJson.inputs ?? [], [pipelineJson]);

  // P4.3: if the wizard stashed event_types in sessionStorage during create,
  // pre-fill the textarea when this modal opens.
  useEffect(() => {
    if (!open) return;
    try {
      const raw = sessionStorage.getItem(`pb:pending_auto_check:${pipelineId}`);
      if (raw) {
        const parsed = JSON.parse(raw) as { event_types?: string[] };
        if (parsed?.event_types?.length) {
          setEventTypesText(parsed.event_types.join(", "));
        }
      }
    } catch {
      // ignore malformed stash
    }
  }, [open, pipelineId]);

  if (!open) return null;

  const eventTypes = eventTypesText
    .split(/[,\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);

  async function handlePublish() {
    if (eventTypes.length === 0) {
      setError("請至少填一個 event_type");
      return;
    }
    setError(null);
    setPublishing(true);
    try {
      const res = await fetch(`/api/pipeline-builder/pipelines/${pipelineId}/publish-auto-check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_types: eventTypes }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`發佈失敗 (${res.status}): ${text.slice(0, 200)}`);
      }
      // Clear the wizard stash now that the bind is persisted.
      try { sessionStorage.removeItem(`pb:pending_auto_check:${pipelineId}`); } catch {}
      onPublished(eventTypes);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPublishing(false);
    }
  }

  return (
    <div style={overlayStyle} role="dialog" aria-modal="true">
      <div style={modalStyle}>
        <div style={{ padding: "14px 18px", borderBottom: "1px solid #E2E8F0", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 18 }}>⚡</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#0F172A" }}>發佈 Auto-Check</div>
            <div style={{ fontSize: 11, color: "#64748B" }}>{pipelineName}</div>
          </div>
          <button onClick={onClose} style={closeBtnStyle}>×</button>
        </div>

        <div style={{ padding: 18, overflowY: "auto", flex: 1 }}>
          <Section title="Step 1 · 綁定 alarm event_types">
            <p style={textStyle}>
              alarm 的 <code style={codeStyle}>trigger_event</code> 吻合這邊列的任何一個字串時，
              這條 pipeline 會被自動執行。多個 event_type 用逗號或換行分隔。
            </p>
            <textarea
              value={eventTypesText}
              onChange={(e) => setEventTypesText(e.target.value)}
              placeholder="e.g. SPC_OOC&#10;RECIPE_DRIFT&#10;auto_patrol:42"
              rows={3}
              style={textareaStyle}
            />
            {eventTypes.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                {eventTypes.map((et) => (
                  <span key={et} style={pillStyle}>{et}</span>
                ))}
              </div>
            )}
          </Section>

          <Section title="Step 2 · Inputs 對應（自動，顯示供確認）">
            {declaredInputs.length === 0 ? (
              <div style={{ ...textStyle, color: "#B91C1C" }}>
                ⚠ 這條 pipeline 沒宣告 inputs。Auto-check 需要 inputs 才能接收 alarm payload。
                回 canvas 加上至少一個 input（如 tool_id）再發佈。
              </div>
            ) : (
              <>
                <p style={textStyle}>
                  執行時，alarm payload 會依**欄位名稱**自動填入這些 inputs。沒對應到的
                  必填 input 會導致該次執行失敗（log 記錄）。
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {declaredInputs.map((inp) => (
                    <div
                      key={inp.name}
                      style={{
                        display: "flex", alignItems: "center", gap: 10, padding: "6px 10px",
                        border: "1px solid #E2E8F0", borderRadius: 4, fontSize: 11,
                      }}
                    >
                      <code style={{ ...codeStyle, fontWeight: 600 }}>{inp.name}</code>
                      <span style={{ color: "#94A3B8" }}>:</span>
                      <span style={{ color: "#64748B" }}>{inp.type}</span>
                      {inp.required && <span style={{ fontSize: 10, color: "#B91C1C" }}>required</span>}
                      <span style={{ flex: 1 }} />
                      <span style={{ color: "#94A3B8", fontSize: 10 }}>
                        ← alarm.{inp.name}
                        {inp.default != null && (
                          <span style={{ marginLeft: 4 }}>
                            (default: {JSON.stringify(inp.default)})
                          </span>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </Section>

          {error && (
            <div style={{
              marginTop: 12, padding: "8px 12px", background: "#FEF2F2",
              color: "#B91C1C", border: "1px solid #FECACA", borderRadius: 4, fontSize: 12,
            }}>
              {error}
            </div>
          )}
        </div>

        <div style={{ padding: "12px 18px", borderTop: "1px solid #E2E8F0", display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={btnStyle("ghost")} disabled={publishing}>取消</button>
          <button
            onClick={handlePublish}
            style={btnStyle("primary")}
            disabled={publishing || eventTypes.length === 0 || declaredInputs.length === 0}
          >
            {publishing ? "發佈中…" : "確定發佈"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: "#0F172A", marginBottom: 6 }}>{title}</div>
      {children}
    </div>
  );
}

const overlayStyle: React.CSSProperties = {
  position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
  background: "rgba(15, 23, 42, 0.5)",
  zIndex: 200, display: "flex", alignItems: "center", justifyContent: "center",
};

const modalStyle: React.CSSProperties = {
  background: "#fff", borderRadius: 8,
  width: "min(640px, 95vw)", maxHeight: "90vh",
  display: "flex", flexDirection: "column",
  boxShadow: "0 16px 40px rgba(0, 0, 0, 0.2)",
  fontFamily: "system-ui, -apple-system, sans-serif",
};

const closeBtnStyle: React.CSSProperties = {
  width: 28, height: 28, borderRadius: "50%",
  background: "transparent", border: "none", fontSize: 18, cursor: "pointer", color: "#64748B",
};

const textStyle: React.CSSProperties = {
  fontSize: 12, color: "#475569", lineHeight: 1.6, margin: "0 0 8px",
};

const codeStyle: React.CSSProperties = {
  background: "#F1F5F9", padding: "1px 6px", borderRadius: 3, fontSize: 11,
};

const textareaStyle: React.CSSProperties = {
  width: "100%", fontSize: 12, fontFamily: "ui-monospace, monospace",
  padding: 8, border: "1px solid #CBD5E0", borderRadius: 4,
  resize: "vertical", outline: "none",
};

const pillStyle: React.CSSProperties = {
  fontSize: 10, padding: "2px 8px", background: "#EEF2FF", color: "#4338CA",
  borderRadius: 10, fontFamily: "ui-monospace, monospace", fontWeight: 500,
};

function btnStyle(variant: "primary" | "ghost"): React.CSSProperties {
  const base: React.CSSProperties = {
    padding: "6px 14px", fontSize: 12, borderRadius: 4, cursor: "pointer",
    fontWeight: 600, border: "1px solid",
  };
  if (variant === "primary") {
    return { ...base, background: "#7C3AED", color: "#fff", borderColor: "#7C3AED" };
  }
  return { ...base, background: "#fff", color: "#475569", borderColor: "#CBD5E0" };
}
