"use client";

/**
 * Phase 5-UX-7: publish modal for `auto_check` pipelines.
 *
 * Auto-check pipelines fire when an alarm is created with a matching
 * `trigger_event`. Phase D added per-binding match_filter so a publisher
 * can narrow the trigger to e.g. "only alarms with severity ∈ {HIGH,
 * CRITICAL}" — see AlarmAttributesHint for the canonical attribute list.
 *
 * No inputs-mapping UI — the pipeline's declared input names are matched
 * against alarm payload keys at runtime (see EventDispatchService).
 */

import { useEffect, useMemo, useState } from "react";
import type { PipelineJSON } from "@/lib/pipeline-builder/types";
import AlarmAttributesHint, {
  ALARM_ATTRIBUTES,
} from "./AlarmAttributesHint";

interface Props {
  open: boolean;
  onClose: () => void;
  pipelineId: number;
  pipelineName: string;
  pipelineJson: PipelineJSON;
  onPublished: (eventTypes: string[]) => void;
}

interface BindingRow {
  /** local-only id for keying / removal — not sent to server */
  rid: number;
  event_type: string;
  /** key → list of allowed values (OR within key, AND across keys) */
  match_filter: Record<string, string[]>;
}

let nextRid = 1;
const newRow = (event_type = ""): BindingRow => ({
  rid: nextRid++,
  event_type,
  match_filter: {},
});

export default function AutoCheckPublishModal({
  open,
  onClose,
  pipelineId,
  pipelineName,
  pipelineJson,
  onPublished,
}: Props) {
  const [rows, setRows] = useState<BindingRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);

  const declaredInputs = useMemo(() => pipelineJson.inputs ?? [], [pipelineJson]);

  // P4.3: if the wizard stashed event_types in sessionStorage during create,
  // pre-fill the rows when this modal opens. (Pre-D format is plain string[].)
  useEffect(() => {
    if (!open) return;
    let initial: BindingRow[] = [];
    try {
      const raw = sessionStorage.getItem(`pb:pending_auto_check:${pipelineId}`);
      if (raw) {
        const parsed = JSON.parse(raw) as { event_types?: string[] };
        if (parsed?.event_types?.length) {
          initial = parsed.event_types.map((et) => newRow(et));
        }
      }
    } catch {
      // ignore malformed stash
    }
    if (initial.length === 0) initial = [newRow()];
    setRows(initial);
  }, [open, pipelineId]);

  if (!open) return null;

  const eventTypesNonEmpty = rows
    .map((r) => r.event_type.trim())
    .filter(Boolean);

  function updateRow(rid: number, patch: Partial<BindingRow>) {
    setRows((prev) => prev.map((r) => (r.rid === rid ? { ...r, ...patch } : r)));
  }

  function addRow() {
    setRows((prev) => [...prev, newRow()]);
  }

  function removeRow(rid: number) {
    setRows((prev) => (prev.length === 1 ? prev : prev.filter((r) => r.rid !== rid)));
  }

  async function handlePublish() {
    const valid = rows.filter((r) => r.event_type.trim());
    if (valid.length === 0) {
      setError("請至少填一個 event_type");
      return;
    }
    setError(null);
    setPublishing(true);
    try {
      const body = {
        event_types: valid.map((r) => {
          const mf = compactFilter(r.match_filter);
          return mf
            ? { event_type: r.event_type.trim(), match_filter: mf }
            : { event_type: r.event_type.trim() };
        }),
      };
      const res = await fetch(`/api/pipeline-builder/pipelines/${pipelineId}/publish-auto-check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`發佈失敗 (${res.status}): ${text.slice(0, 200)}`);
      }
      // Clear the wizard stash now that the bind is persisted.
      try { sessionStorage.removeItem(`pb:pending_auto_check:${pipelineId}`); } catch {}
      onPublished(valid.map((r) => r.event_type.trim()));
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
          <AlarmAttributesHint />

          <Section title="Step 1 · 綁定 alarm 觸發條件">
            <p style={textStyle}>
              alarm 的 <code style={codeStyle}>trigger_event</code> 吻合任一筆設定且
              附加條件全過時，這條 pipeline 會被自動執行。
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {rows.map((row) => (
                <BindingEditor
                  key={row.rid}
                  row={row}
                  onChange={(patch) => updateRow(row.rid, patch)}
                  onRemove={() => removeRow(row.rid)}
                  removable={rows.length > 1}
                />
              ))}
              <button onClick={addRow} style={addBindingBtnStyle}>＋ 加一個 binding</button>
            </div>
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
            disabled={publishing || eventTypesNonEmpty.length === 0 || declaredInputs.length === 0}
          >
            {publishing ? "發佈中…" : "確定發佈"}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Strip empty key→[] entries; return undefined when nothing left so the
 *  binding row drops `match_filter` from the payload entirely (server-side
 *  null = no filter). */
function compactFilter(mf: Record<string, string[]>): Record<string, string[]> | undefined {
  const out: Record<string, string[]> = {};
  for (const [k, v] of Object.entries(mf)) {
    const cleaned = (v ?? []).map((s) => s.trim()).filter(Boolean);
    if (cleaned.length > 0) out[k] = cleaned;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

function BindingEditor({
  row, onChange, onRemove, removable,
}: {
  row: BindingRow;
  onChange: (patch: Partial<BindingRow>) => void;
  onRemove: () => void;
  removable: boolean;
}) {
  const [filterOpen, setFilterOpen] = useState(
    Object.keys(row.match_filter).length > 0,
  );

  // Keys not yet used in this binding — for the "+ 加條件" key picker.
  const usedKeys = new Set(Object.keys(row.match_filter));
  const availableKeys = ALARM_ATTRIBUTES.filter((a) => !usedKeys.has(a.name));

  function setFilterKey(key: string) {
    if (!key) return;
    onChange({ match_filter: { ...row.match_filter, [key]: [] } });
  }

  function setFilterValues(key: string, values: string[]) {
    onChange({ match_filter: { ...row.match_filter, [key]: values } });
  }

  function dropFilterKey(key: string) {
    const next = { ...row.match_filter };
    delete next[key];
    onChange({ match_filter: next });
  }

  return (
    <div
      style={{
        border: "1px solid #E2E8F0",
        borderRadius: 6,
        padding: 10,
        background: "#fff",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input
          type="text"
          value={row.event_type}
          onChange={(e) => onChange({ event_type: e.target.value })}
          placeholder="event_type，例如 SPC_OOC 或 auto_patrol:42"
          style={inputStyle}
        />
        {removable && (
          <button
            onClick={onRemove}
            style={removeBtnStyle}
            title="移除此 binding"
          >
            ✕
          </button>
        )}
      </div>

      <button
        onClick={() => setFilterOpen((v) => !v)}
        style={toggleBtnStyle}
      >
        {filterOpen ? "▾" : "▸"} 附加條件 ({Object.keys(row.match_filter).length})
      </button>

      {filterOpen && (
        <div
          style={{
            marginTop: 6,
            padding: "8px 10px",
            background: "#F8FAFC",
            border: "1px dashed #CBD5E0",
            borderRadius: 4,
            display: "flex",
            flexDirection: "column",
            gap: 6,
            fontSize: 11,
          }}
        >
          {Object.entries(row.match_filter).length === 0 && (
            <div style={{ color: "#64748B" }}>
              沒有附加條件 — 任何匹配 event_type 的 alarm 都會觸發。
            </div>
          )}
          {Object.entries(row.match_filter).map(([key, values]) => (
            <div key={key} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <code style={{ ...codeStyle, minWidth: 100 }}>{key}</code>
              <span style={{ color: "#64748B" }}>∈</span>
              <ChipInput
                values={values}
                onChange={(next) => setFilterValues(key, next)}
                placeholder={key === "severity" ? "HIGH, CRITICAL" : "EQP-01, EQP-02"}
              />
              <button
                onClick={() => dropFilterKey(key)}
                style={smallRemoveBtnStyle}
                title="移除這條條件"
              >
                ✕
              </button>
            </div>
          ))}
          {availableKeys.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <select
                onChange={(e) => {
                  setFilterKey(e.target.value);
                  e.target.value = "";  // reset
                }}
                style={{ ...inputStyle, fontSize: 11, padding: "4px 6px" }}
                defaultValue=""
              >
                <option value="" disabled>＋ 加條件（選欄位）</option>
                {availableKeys.map((a) => (
                  <option key={a.name} value={a.name}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ChipInput({
  values, onChange, placeholder,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  function commitDraft() {
    const trimmed = draft.trim();
    if (!trimmed) return;
    if (values.includes(trimmed)) return;
    onChange([...values, trimmed]);
    setDraft("");
  }

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexWrap: "wrap",
        gap: 4,
        padding: "4px 6px",
        background: "#fff",
        border: "1px solid #CBD5E0",
        borderRadius: 4,
        minHeight: 28,
        alignItems: "center",
      }}
    >
      {values.map((v) => (
        <span key={v} style={pillStyle}>
          {v}
          <button
            onClick={() => onChange(values.filter((x) => x !== v))}
            style={{
              marginLeft: 4, background: "transparent", border: "none",
              color: "#4338CA", cursor: "pointer", fontSize: 10,
            }}
          >
            ×
          </button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commitDraft();
          }
        }}
        onBlur={commitDraft}
        placeholder={placeholder ?? "輸入後 Enter / 逗號"}
        style={{
          flex: 1, minWidth: 80,
          fontSize: 11, padding: 0, border: "none", outline: "none", background: "transparent",
        }}
      />
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
  width: "min(680px, 95vw)", maxHeight: "90vh",
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
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
};

const inputStyle: React.CSSProperties = {
  flex: 1, padding: "6px 10px", fontSize: 12,
  border: "1px solid #CBD5E0", borderRadius: 4, outline: "none",
};

const pillStyle: React.CSSProperties = {
  fontSize: 10, padding: "2px 6px", background: "#EEF2FF", color: "#4338CA",
  borderRadius: 10, fontFamily: "ui-monospace, monospace", fontWeight: 500,
  display: "inline-flex", alignItems: "center",
};

const removeBtnStyle: React.CSSProperties = {
  width: 26, height: 26, borderRadius: 4,
  background: "#fff", border: "1px solid #FECACA", color: "#B91C1C",
  cursor: "pointer", fontSize: 12,
};

const smallRemoveBtnStyle: React.CSSProperties = {
  ...removeBtnStyle, width: 22, height: 22, fontSize: 10,
};

const toggleBtnStyle: React.CSSProperties = {
  marginTop: 4, padding: "3px 8px", fontSize: 11, color: "#475569",
  background: "transparent", border: "none", cursor: "pointer",
};

const addBindingBtnStyle: React.CSSProperties = {
  padding: "6px 10px", fontSize: 11, color: "#7C3AED",
  background: "transparent", border: "1px dashed #CBD5E0", borderRadius: 4,
  cursor: "pointer", alignSelf: "flex-start",
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
