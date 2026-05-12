"use client";

/**
 * PipelineRunDialog — prompts for pipeline.inputs values when required fields
 * don't yet have a value.
 *
 * 2026-05-12: split into two tabs to match the Skills Library Test flow:
 *   - "📂 From past event" — when this pipeline is bound to a Skill with an
 *     event trigger, fetch past alarms and let the user replay any of them
 *     with one click (payload comes from the same /past-events endpoint that
 *     TestCaseSelector uses).
 *   - "✍️ Manual input" — original form, now with canonical fallback so 7
 *     OOC schema fields auto-fill (user only types overrides).
 * Past tab is preferred when available and pre-selects pastCases[0].
 */

import { useEffect, useMemo, useState } from "react";
import type { PipelineInput } from "@/lib/pipeline-builder/types";

interface PastCase {
  id: string;
  kind: string;
  title: string;
  desc?: string;
  meta?: { tool?: string; lot?: string; time?: string; outcome?: string };
  payload: Record<string, unknown>;
}

interface Props {
  open: boolean;
  inputs: PipelineInput[];
  /** Skill embed context — when set, dialog fetches /past-events and shows a
   *  picker tab. Null/undefined → Manual-only mode (independent pipeline). */
  skillCtx?: { slug: string; eventType?: string } | null;
  onCancel: () => void;
  onSubmit: (values: Record<string, unknown>) => void;
}

// Canonical example values used when the input declaration has no
// default/example set. Mirrors Java buildEventPayload._defaultForAttr +
// SkillEmbedBanner._CANONICAL_EXAMPLES so dry-run / past-event replay /
// manual payload all use the same shape.
const CANONICAL: Record<string, string> = {
  tool_id: "EQP-01",
  equipment_id: "EQP-01",
  lot_id: "LOT-0001",
  step: "STEP_001",
  step_id: "STEP_001",
  chamber_id: "CH-1",
  recipe_id: "RECIPE-A",
  parameter: "CD_Mean",
  ooc_parameter: "CD_Mean",
  spc_chart: "spc_xbar",
  SPC_CHART: "spc_xbar",
  fault_code: "FDC_RGA_H2O_HIGH",
  severity: "warning",
  event_time: "2026-05-01T00:00:00Z",
  timestamp: "2026-05-01T00:00:00Z",
  process_timestamp: "2026-05-01T00:00:00Z",
  ooc_details: "{}",
  time_range: "24h",
  limit: "100",
};

export default function PipelineRunDialog({ open, inputs, skillCtx, onCancel, onSubmit }: Props) {
  const initial = useMemo(() => {
    const v: Record<string, string> = {};
    for (const inp of inputs) {
      const seed = inp.default ?? inp.example ?? CANONICAL[inp.name] ?? "";
      v[inp.name] = seed === null ? "" : String(seed);
    }
    return v;
  }, [inputs]);
  const [values, setValues] = useState<Record<string, string>>(initial);
  const [error, setError] = useState<string | null>(null);

  // Past-event tab state.
  const [tab, setTab] = useState<"past" | "manual">("past");
  const [pastCases, setPastCases] = useState<PastCase[]>([]);
  const [pastLoading, setPastLoading] = useState(false);
  const [selectedPastId, setSelectedPastId] = useState<string>("");

  // Fetch past events when dialog opens with skill context.
  useEffect(() => {
    if (!open || !skillCtx?.slug) {
      setPastCases([]);
      return;
    }
    setPastLoading(true);
    fetch(`/api/skill-documents/${encodeURIComponent(skillCtx.slug)}/past-events`)
      .then(async (res) => res.ok ? (await res.json()).data as PastCase[] : [])
      .catch(() => [])
      .then((rows) => {
        const arr = rows ?? [];
        setPastCases(arr);
        if (arr.length > 0) {
          setSelectedPastId(arr[0].id);
          setTab("past");
        } else {
          setTab("manual");
        }
      })
      .finally(() => setPastLoading(false));
  }, [open, skillCtx?.slug]);

  // Reset Manual values when dialog re-opens (so re-runs don't carry stale state).
  useEffect(() => {
    if (open) setValues(initial);
  }, [open, initial]);

  if (!open) return null;

  const submitManual = () => {
    for (const inp of inputs) {
      if (inp.required && !values[inp.name]) {
        setError(`"${inp.name}" 為必填`);
        return;
      }
    }
    onSubmit(values);
    setError(null);
  };

  const submitPast = () => {
    const c = pastCases.find((x) => x.id === selectedPastId);
    if (!c) { setError("請選一筆歷史事件"); return; }
    onSubmit(c.payload);
    setError(null);
  };

  const canShowPastTab = !!skillCtx?.slug;
  const selectedPast = pastCases.find((x) => x.id === selectedPastId);

  return (
    <div
      data-testid="pipeline-run-dialog"
      onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}
      style={{
        position: "fixed", inset: 0,
        background: "rgba(15,23,42,0.35)",
        zIndex: 230,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: canShowPastTab ? "min(720px, 94vw)" : "min(480px, 92vw)",
          maxHeight: "82vh",
          background: "#fff",
          borderRadius: 8,
          boxShadow: "0 16px 48px rgba(15,23,42,0.18)",
          fontFamily: "Inter, system-ui, -apple-system, 'Noto Sans TC', sans-serif",
          display: "flex", flexDirection: "column",
        }}
      >
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #E2E8F0", background: "#F8FAFC", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 16 }}>▶</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#0F172A" }}>Run Pipeline</div>
            <div style={{ fontSize: 10, color: "#64748B" }}>
              {canShowPastTab
                ? "從歷史事件挑一筆重放，或自填 payload"
                : "填入 pipeline inputs 的值"}
            </div>
          </div>
        </div>

        {canShowPastTab && (
          <div style={{ padding: "10px 16px 0", borderBottom: "1px solid #E2E8F0" }}>
            <div style={{ display: "inline-flex", padding: 2, borderRadius: 6, background: "#F1F5F9", border: "1px solid #E2E8F0" }}>
              {(["past", "manual"] as const).map((t) => (
                <button key={t}
                  data-testid={`run-tab-${t}`}
                  onClick={() => setTab(t)}
                  style={{
                    all: "unset", cursor: "pointer",
                    padding: "5px 14px", borderRadius: 4,
                    background: tab === t ? "#fff" : "transparent",
                    color: tab === t ? "#0F172A" : "#64748B",
                    fontSize: 12, fontWeight: 500,
                    boxShadow: tab === t ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
                  }}>
                  {t === "past" ? "📂 From past event" : "✍️ Manual input"}
                </button>
              ))}
            </div>
            <div style={{ height: 10 }}/>
          </div>
        )}

        {canShowPastTab && tab === "past" ? (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", flex: 1, minHeight: 0 }}>
            <div style={{ padding: "12px 16px", overflowY: "auto", borderRight: "1px solid #E2E8F0", maxHeight: "55vh" }}>
              {pastLoading && (
                <div style={{ fontSize: 12, color: "#64748B" }}>載入歷史 events…</div>
              )}
              {!pastLoading && pastCases.length === 0 && (
                <div style={{ fontSize: 12, color: "#64748B", lineHeight: 1.5 }}>
                  目前沒有歷史 event 可選。<br/>
                  <button onClick={() => setTab("manual")} style={{ all: "unset", cursor: "pointer", color: "#4F46E5", textDecoration: "underline", marginTop: 8, fontSize: 12 }}>
                    切到 ✍️ Manual input 自填
                  </button>
                </div>
              )}
              {pastCases.map((c) => {
                const isSel = c.id === selectedPastId;
                return (
                  <button key={c.id}
                    data-testid={`past-case-${c.id}`}
                    onClick={() => setSelectedPastId(c.id)}
                    style={{
                      all: "unset", cursor: "pointer", display: "block", width: "100%",
                      padding: "9px 11px",
                      background: isSel ? "#F1F5F9" : "transparent",
                      border: `1px solid ${isSel ? "#475569" : "#E2E8F0"}`,
                      borderRadius: 5, marginBottom: 5,
                    }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                      <span style={{ width: 5, height: 5, borderRadius: 999, background: "#D97706" }}/>
                      <span style={{ fontSize: 12.5, color: "#0F172A", fontWeight: 500 }}>{c.title}</span>
                    </div>
                    {c.desc && <div style={{ fontSize: 11, color: "#64748B", lineHeight: 1.45, paddingLeft: 11 }}>{c.desc}</div>}
                    {c.meta?.time && (
                      <div className="mono" style={{ fontSize: 10, color: "#94A3B8", paddingLeft: 11, marginTop: 2, fontFamily: "ui-monospace, monospace" }}>
                        {c.meta.time}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
            <div style={{ padding: "12px 14px", overflowY: "auto", background: "#F8FAFC", maxHeight: "55vh" }}>
              <div className="mono" style={{ fontSize: 10, letterSpacing: "0.08em", color: "#64748B", marginBottom: 5, fontFamily: "ui-monospace, monospace" }}>PAYLOAD PREVIEW</div>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: "#0F172A", marginBottom: 8 }}>
                {selectedPast?.title ?? "—"}
              </div>
              <pre className="mono" style={{
                margin: 0, padding: 10, background: "#fff",
                border: "1px solid #E2E8F0", borderRadius: 5,
                fontSize: 11, color: "#475569", lineHeight: 1.55,
                fontFamily: "ui-monospace, monospace",
                whiteSpace: "pre-wrap", maxHeight: "40vh", overflowY: "auto",
              }}>{selectedPast ? JSON.stringify(selectedPast.payload, null, 2) : ""}</pre>
            </div>
          </div>
        ) : (
          <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, overflowY: "auto", maxHeight: "60vh" }}>
            {canShowPastTab && pastCases.length > 0 && (
              <div style={{
                padding: "8px 12px", borderRadius: 5,
                background: "#EFF6FF",
                border: "1px solid #BFDBFE",
                fontSize: 12, color: "#1E40AF", lineHeight: 1.4,
              }}>
                💡 旁邊 <button onClick={() => setTab("past")} style={{ all: "unset", cursor: "pointer", fontWeight: 600, color: "#1D4ED8", textDecoration: "underline" }}>📂 From past event</button> 已經列了 {pastCases.length} 筆歷史事件，點一筆就能一鍵帶入。
              </div>
            )}
            {inputs.map((inp) => (
              <label key={inp.name} style={{ fontSize: 11, display: "flex", flexDirection: "column", gap: 3 }}>
                <span style={{ color: "#475569" }}>
                  <code style={{ color: "#3730A3", fontFamily: "ui-monospace, monospace" }}>${inp.name}</code>
                  {inp.required && <span style={{ color: "#B91C1C" }}> *</span>}
                  <span style={{ color: "#94A3B8", marginLeft: 8 }}>({inp.type})</span>
                  {inp.description && <span style={{ marginLeft: 8, color: "#64748B" }}>— {inp.description}</span>}
                </span>
                <input
                  data-testid={`run-dialog-input-${inp.name}`}
                  type={inp.type === "integer" || inp.type === "number" ? "number" : "text"}
                  value={values[inp.name] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [inp.name]: e.target.value }))}
                  placeholder={inp.example != null ? String(inp.example) : ""}
                  style={{
                    padding: "6px 10px",
                    fontSize: 12,
                    border: "1px solid #CBD5E1",
                    borderRadius: 3,
                    outline: "none",
                  }}
                />
              </label>
            ))}
          </div>
        )}

        {error && <div style={{ padding: "0 16px 4px", color: "#DC2626", fontSize: 11 }}>{error}</div>}

        <div style={{ padding: "10px 16px", borderTop: "1px solid #E2E8F0", display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onCancel}
            style={{ padding: "6px 14px", fontSize: 12, background: "#fff", border: "1px solid #CBD5E1", borderRadius: 3, cursor: "pointer", color: "#475569" }}>
            取消
          </button>
          <button
            data-testid="run-dialog-submit"
            onClick={() => (canShowPastTab && tab === "past") ? submitPast() : submitManual()}
            style={{ padding: "6px 16px", fontSize: 12, background: "#4F46E5", color: "#fff", border: "none", borderRadius: 3, cursor: "pointer", fontWeight: 600 }}>
            Run
          </button>
        </div>
      </div>
    </div>
  );
}
