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

  /* Load past events when modal opens — type is implicit from skill's trigger_config */
  void skillTriggerType; void eventType;
  useEffect(() => {
    if (!open || !slug) return;
    setPastLoading(true);
    fetch(`/api/skill-documents/${encodeURIComponent(slug)}/past-events`)
      .then(async (res) => res.ok ? (await res.json()).data as TestCase[] : [])
      .catch(() => [])
      .then((rows) => setPastCases(rows ?? []))
      .finally(() => setPastLoading(false));
  }, [open, slug]);

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
