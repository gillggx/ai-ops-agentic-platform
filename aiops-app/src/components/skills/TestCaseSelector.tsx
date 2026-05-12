"use client";

/**
 * TestCaseSelector — modal that gates Run Skill.
 * Two tabs:
 *   - Past event: pull historical alarms / patrol_runs / personal_rule_fires
 *   - Manual input: form driven by trigger_config.type
 *
 * 11-C past-event API endpoints are TODO — modal currently surfaces UI
 * shape only and falls back to Manual input when API list is empty.
 */
import { useEffect, useMemo, useState } from "react";
import { Icon, Badge, Btn } from "./atoms";

export interface TestCase {
  id: string;
  kind: "live" | "historical" | "synthetic";
  title: string;
  desc: string;
  meta: { tool?: string; lot?: string; time?: string; outcome?: string };
  expected?: string;
  payload: Record<string, unknown>;
}

// Canonical preview values for common event-payload fields. Mirrors the
// Java _defaultForAttr() side of buildEventPayload — keep them in sync so
// past-event replay and Manual tab show identical shape.
function _canonicalForField(name: string): string {
  switch (name) {
    case "tool_id": case "equipment_id": return "EQP-01";
    case "lot_id":                       return "LOT-0001";
    case "step": case "step_id":         return "STEP_001";
    case "chamber_id":                   return "CH-1";
    case "recipe_id":                    return "RECIPE-A";
    case "parameter": case "ooc_parameter": return "CD_Mean";
    case "spc_chart": case "SPC_CHART":  return "spc_xbar";
    case "fault_code":                   return "FDC_RGA_H2O_HIGH";
    case "severity":                     return "warning";
    case "event_time": case "timestamp": case "process_timestamp":
                                         return "2026-05-01T00:00:00Z";
    case "ooc_details":                  return "{}";
    default:                             return "";
  }
}

const SYNTHETIC_BASELINE: TestCase = {
  id: "syn",
  kind: "synthetic",
  title: "Synthetic · 全綠 baseline",
  desc: "人造的 zero-issue 場景，用於確認沒有錯誤觸發",
  meta: { tool: "—", lot: "—", time: "—", outcome: "all pass" },
  expected: "All checks pass",
  payload: { tool_id: "EQP-00", lot_id: "LOT-baseline" },
};

export default function TestCaseSelector({
  open, slug, skillTriggerType, eventType,
  onClose, onStart,
}: {
  open: boolean;
  slug: string;
  skillTriggerType: "system" | "user" | "schedule";
  eventType?: string;
  onClose: () => void;
  onStart: (testCase: TestCase | null, payload: Record<string, unknown>) => void;
}) {
  const [tab, setTab] = useState<"past" | "manual">("past");
  const [pastCases, setPastCases] = useState<TestCase[]>([]);
  const [pastLoading, setPastLoading] = useState(false);
  const [selected, setSelected] = useState<string>("syn");
  const [manualPayload, setManualPayload] = useState<Record<string, string>>({
    tool_id: "EQP-01", lot_id: "LOT-0001", severity: "med",
  });

  void skillTriggerType;

  /* Load past events when modal opens — type is implicit from skill's trigger_config */
  useEffect(() => {
    if (!open || !slug) return;
    setPastLoading(true);
    fetch(`/api/skill-documents/${encodeURIComponent(slug)}/past-events`)
      .then(async (res) => res.ok ? (await res.json()).data as TestCase[] : [])
      .catch(() => [])
      .then((rows) => {
        const arr = rows ?? [];
        setPastCases(arr);
        // 2026-05-12: pre-select the first REAL past event so the user can
        // hit Start dry-run immediately. Was defaulted to "syn" (synthetic
        // baseline = 2 fake fields), which made users think Test required
        // them to switch to Manual tab and fill payload by hand. With this
        // pre-selection the Past event tab is the one-click path.
        if (arr.length > 0) setSelected(arr[0].id);
      })
      .finally(() => setPastLoading(false));
  }, [open, slug]);

  /* When skill has an event trigger, populate Manual tab from event_types
     schema so the user doesn't have to "Add field" 6 times. Canonical
     defaults match buildEventPayload on the Java side so dry-run + past-
     event-replay shape matches. */
  useEffect(() => {
    if (!open || !eventType) return;
    fetch(`/api/event-types/by-name/${encodeURIComponent(eventType)}`, { cache: "no-store" })
      .then(async (res) => res.ok ? (await res.json()) : null)
      .then((json) => {
        if (!json) return;
        const data = json?.data ?? json;
        const rawAttrs = data?.attributes;
        const attrs = typeof rawAttrs === "string"
          ? (rawAttrs.trim() ? JSON.parse(rawAttrs) : [])
          : (Array.isArray(rawAttrs) ? rawAttrs : []);
        if (!Array.isArray(attrs) || attrs.length === 0) return;
        const next: Record<string, string> = {};
        for (const a of attrs as Array<Record<string, unknown>>) {
          const n = String(a?.name ?? "");
          if (!n) continue;
          next[n] = _canonicalForField(n);
        }
        setManualPayload(next);
      })
      .catch(() => { /* keep legacy 3-field default on failure */ });
  }, [open, eventType]);

  const allCases = useMemo<TestCase[]>(() => [...pastCases, SYNTHETIC_BASELINE], [pastCases]);
  const sel = allCases.find((c) => c.id === selected) ?? SYNTHETIC_BASELINE;

  if (!open) return null;

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 100,
      background: "rgba(10, 12, 16, 0.45)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 24,
      animation: "skill-modal-in 180ms ease-out",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: 880, maxHeight: "82vh", display: "flex", flexDirection: "column",
        background: "var(--bg)", borderRadius: 14,
        border: "1px solid var(--line-strong)",
        boxShadow: "0 24px 60px rgba(10,12,16,0.25)",
        overflow: "hidden",
      }}>
        <div style={{ padding: "20px 24px 0", borderBottom: "1px solid var(--line)" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 6 }}>
            <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600, letterSpacing: "-0.01em" }}>Select test case for dry-run</h2>
            <Badge kind="ai" icon={<Icon.Spark/>}>Sandboxed</Badge>
          </div>
          <p style={{ marginTop: 6, marginBottom: 16, fontSize: 12.5, color: "var(--ink-3)", lineHeight: 1.55 }}>
            這個 skill 將在沙盒內針對選擇的 test case 執行，所有結果僅供驗證與評估使用，不會寫入正式系統。
          </p>
          <div style={{ display: "inline-flex", padding: 2, borderRadius: 8,
                        background: "var(--surface-2)", border: "1px solid var(--line)" }}>
            {(["past", "manual"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} style={{
                padding: "5px 12px", borderRadius: 6, border: "none",
                background: tab === t ? "var(--surface)" : "transparent",
                color: tab === t ? "var(--ink)" : "var(--ink-3)",
                fontSize: 12, fontWeight: 500, cursor: "pointer",
                boxShadow: tab === t ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
              }}>
                {t === "past" ? "📂 From past event" : "✍️ Manual input"}
              </button>
            ))}
          </div>
          <div style={{ height: 14 }}/>
        </div>

        {tab === "past" ? (
          <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", flex: 1, minHeight: 0 }}>
            <div style={{ padding: "12px 16px", overflowY: "auto", borderRight: "1px solid var(--line)" }}>
              {pastLoading && (
                <div style={{ fontSize: 12, color: "var(--ink-3)", padding: 12 }}>
                  <span className="skill-spinner" style={{ marginRight: 6 }}/> 載入歷史 events…
                </div>
              )}
              {!pastLoading && pastCases.length === 0 && (
                <div style={{ fontSize: 12.5, color: "var(--ink-3)", padding: "12px 4px", lineHeight: 1.5 }}>
                  目前沒有歷史 events 可供重播。<br/>
                  <span style={{ color: "var(--ink-4)" }}>
                    切到 ✍️ Manual input 自己填 payload，或等 trigger 累積一些事件後再試。
                  </span>
                </div>
              )}
              {[...pastCases, SYNTHETIC_BASELINE].map((c) => {
                const dotColor = c.kind === "live" ? "var(--fail)" : c.kind === "historical" ? "var(--warn)" : "var(--ai)";
                return (
                  <button key={c.id} onClick={() => setSelected(c.id)} style={{
                    all: "unset", cursor: "pointer", display: "block", width: "100%",
                    padding: "10px 12px",
                    background: selected === c.id ? "var(--surface-2)" : "transparent",
                    border: `1px solid ${selected === c.id ? "var(--ink-2)" : "var(--line)"}`,
                    borderRadius: 6, marginBottom: 6,
                    transition: "all 120ms",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
                      <span style={{ width: 6, height: 6, borderRadius: 999, background: dotColor }}/>
                      <span style={{ fontSize: 12.5, color: "var(--ink)", fontWeight: 500 }}>{c.title}</span>
                    </div>
                    <div style={{ fontSize: 11.5, color: "var(--ink-3)", lineHeight: 1.5, paddingLeft: 14 }}>{c.desc}</div>
                  </button>
                );
              })}
            </div>
            <div style={{ padding: "16px 18px", overflowY: "auto", background: "var(--bg-soft)" }}>
              <div className="mono" style={{ fontSize: 10, letterSpacing: "0.08em", color: "var(--ink-3)", marginBottom: 6 }}>PAYLOAD PREVIEW</div>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--ink)", marginBottom: 10, letterSpacing: "-0.005em" }}>{sel.title}</div>
              <pre className="mono" style={{
                margin: 0, padding: 12, background: "var(--surface)",
                border: "1px solid var(--line)", borderRadius: 6,
                fontSize: 11, color: "var(--ink-2)", lineHeight: 1.7,
                whiteSpace: "pre-wrap",
              }}>{JSON.stringify(sel.payload, null, 2)}</pre>
              {sel.expected && (
                <div style={{
                  marginTop: 14, padding: "10px 12px",
                  background: "var(--ai-bg)",
                  border: "1px solid color-mix(in oklch, var(--ai), transparent 75%)",
                  borderRadius: 6, fontSize: 11.5, color: "var(--ink-2)",
                  display: "flex", gap: 8, alignItems: "flex-start",
                }}>
                  <Icon.Spark/>
                  <span><strong style={{ color: "var(--ai)" }}>Expected outcome</strong> · {sel.expected}</span>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div style={{ flex: 1, padding: "16px 24px", overflowY: "auto" }}>
            <div className="mono" style={{ fontSize: 10, letterSpacing: "0.08em", color: "var(--ink-3)", marginBottom: 8 }}>
              MANUAL TRIGGER PAYLOAD
            </div>
            <p style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 0, lineHeight: 1.55 }}>
              依 trigger 類型填欄位；skill runner 用這個 payload 跑全部 step。
            </p>
            {/* 2026-05-12 — point user back to Past event tab when there's
                actually historical data available. User reported "test 還要
                我填一堆 event 欄位" because they had switched to Manual without
                noticing Past event already listed real OOC events ready to
                replay with one click. */}
            {pastCases.length > 0 && (
              <div style={{
                marginTop: 4, marginBottom: 12,
                padding: "8px 12px", borderRadius: 6,
                background: "var(--ai-bg)",
                border: "1px solid color-mix(in oklch, var(--ai), transparent 70%)",
                fontSize: 12, color: "var(--ink-2)", lineHeight: 1.5,
              }}>
                💡 旁邊 <button
                  onClick={() => setTab("past")}
                  style={{
                    all: "unset", cursor: "pointer", fontWeight: 600,
                    color: "var(--ai)", textDecoration: "underline",
                  }}>📂 From past event</button> 已經列了 {pastCases.length} 筆歷史事件，
                點一筆就能一鍵帶入真實 payload，不用手填。
              </div>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8, alignItems: "center", marginTop: 14, maxWidth: 520 }}>
              {Object.entries(manualPayload).map(([k, v]) => (
                <span key={k} style={{ display: "contents" }}>
                  <span className="mono" style={{ fontSize: 11.5, color: "var(--ink-3)" }}>{k}</span>
                  <input value={v} onChange={(e) => setManualPayload((p) => ({ ...p, [k]: e.target.value }))}
                    className="mono"
                    style={{ padding: "6px 10px", fontSize: 12, border: "1px solid var(--line-strong)", background: "var(--surface)",
                             color: "var(--ink)", borderRadius: 6, outline: "none", fontFamily: "JetBrains Mono, monospace" }}/>
                </span>
              ))}
            </div>
            <div style={{ marginTop: 16 }}>
              <button onClick={() => setManualPayload((p) => ({ ...p, ["new_field"]: "" }))} style={{
                all: "unset", cursor: "pointer", padding: "5px 10px", borderRadius: 6,
                background: "var(--surface-2)", color: "var(--ink-2)", border: "1px dashed var(--line-strong)",
                fontSize: 12, display: "inline-flex", alignItems: "center", gap: 6,
              }}>
                <Icon.Plus/> Add field
              </button>
            </div>
          </div>
        )}

        <div style={{ padding: "14px 24px", borderTop: "1px solid var(--line)", display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 11.5, color: "var(--ink-3)" }}>
            Test 結果不會發通知；若要保留為 regression case，跑完按 Save。
          </span>
          <span style={{ flex: 1 }}/>
          <Btn kind="ghost" onClick={onClose}>Cancel</Btn>
          <Btn kind="primary" icon={<Icon.Play/>} onClick={() => {
            if (tab === "past") {
              onStart(sel, sel.payload);
            } else {
              onStart(null, manualPayload);
            }
          }}>Start dry-run</Btn>
        </div>
      </div>
    </div>
  );
}
