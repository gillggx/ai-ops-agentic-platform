"use client";

/**
 * 画面 B — Checklist Editor + Dry-run (DIAGNOSE stage of Skill Studio).
 *
 * Per the OOC Skill Studio spec §4 + §5.  Forks the standalone dry-run
 * page at /skills/[slug]/dry-run so the legacy surface stays untouched:
 *
 *   - Same state machine (editor | picker | running | report).
 *   - Same overlay components & Variant A separation rule.
 *   - PLUS a sticky Top App Bar (角色 toggle, ▸ Dry-run, primary action).
 *   - PLUS inline Edit Panel jumpback from FAIL findings.
 *   - PLUS Locked (現場 oncall) mode that disables edits.
 *
 * Reads + writes use the existing /api/skill-documents/[slug]/* endpoints
 * (Phase 4 doesn't depend on skill_stages — those drive page A only).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { TK, SHADOW, FONT, MONO_EYEBROW, SANDBOX_PILL } from "@/components/skill-dryrun/tokens";
import type {
  SkillDocument, SkillStep, TestCase, StepResult, DryRunView,
} from "@/components/skill-dryrun/types";
import ChartRenderer from "@/components/pipeline-builder/ChartRenderer";

const RUNNING_MIN_MS = 950;
const TOAST_DURATION_MS = 2400;
const HIGHLIGHT_SCROLL_OFFSET = 110;

type Role = "editing" | "locked";

// ── Page ─────────────────────────────────────────────────────────────────────

export default function ChecklistPage() {
  const params = useParams<{ slug: string }>();
  const slug = params?.slug ?? "";

  const [skill, setSkill] = useState<SkillDocument | null>(null);
  const [cases, setCases] = useState<TestCase[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [role, setRole] = useState<Role>("editing");
  const [view, setView] = useState<DryRunView>("editor");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [runCaseId, setRunCaseId] = useState<string | null>(null);
  const [stepResults, setStepResults] = useState<StepResult[]>([]);
  const [thresholdOverrides, setThresholdOverrides] = useState<Record<number, number>>({});
  const [highlightIndex, setHighlightIndex] = useState<number | null>(null);
  const [expandedFails, setExpandedFails] = useState<Record<number, boolean>>({});
  const [toast, setToast] = useState<string>("");
  const [savingRegression, setSavingRegression] = useState(false);

  const stepRefs = useRef<(HTMLDivElement | null)[]>([]);

  // ── Load skill + past events ──────────────────────────────────────────────

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    (async () => {
      try {
        const [sRes, eRes] = await Promise.all([
          fetch(`/api/skill-documents/${encodeURIComponent(slug)}`),
          fetch(`/api/skill-documents/${encodeURIComponent(slug)}/past-events`),
        ]);
        if (!sRes.ok) throw new Error(`skill load: HTTP ${sRes.status}`);
        const sEnv = await sRes.json();
        const sData = sEnv?.data ?? sEnv;
        const parsed: SkillDocument = {
          ...sData,
          steps: safeJson<SkillStep[]>(sData.steps, []),
          test_cases: safeJson<TestCase[]>(sData.test_cases, []),
          trigger_config: safeJson<Record<string, unknown>>(sData.trigger_config, {}),
        };
        if (cancelled) return;
        setSkill(parsed);

        let pastCases: TestCase[] = [];
        if (eRes.ok) {
          const eEnv = await eRes.json();
          const eData = (eEnv?.data ?? eEnv) as unknown[];
          pastCases = Array.isArray(eData) ? eData.map(adaptPastEvent) : [];
        }
        if (!cancelled) {
          setCases(pastCases.length > 0 ? pastCases : parsed.test_cases);
        }
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [slug]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), TOAST_DURATION_MS);
    return () => clearTimeout(t);
  }, [toast]);

  // ── Run dry-run via SSE ───────────────────────────────────────────────────

  const runDryRun = useCallback(async (caseId: string) => {
    const tc = cases.find(c => c.id === caseId);
    if (!tc || !skill) return;

    setView("running");
    setStepResults([]);
    setRunCaseId(caseId);
    const startedAt = Date.now();

    const accumulated: StepResult[] = [];
    try {
      const res = await fetch(`/api/skill-documents/${encodeURIComponent(slug)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trigger_payload: tc.payload, is_test: true }),
      });
      if (!res.ok || !res.body) throw new Error(`run: HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) !== -1) {
          const frame = buf.slice(0, i);
          buf = buf.slice(i + 2);
          const parsed = parseSseFrame(frame);
          if (parsed?.name === "step_done" || parsed?.name === "stepDone") {
            const sr = adaptStepDone(parsed.data);
            if (sr) accumulated.push(sr);
          }
        }
      }
    } catch (e) {
      setToast(`Dry-run failed: ${e instanceof Error ? e.message : e}`);
      setView("editor");
      return;
    }

    const elapsed = Date.now() - startedAt;
    if (elapsed < RUNNING_MIN_MS) {
      await new Promise(r => setTimeout(r, RUNNING_MIN_MS - elapsed));
    }
    setStepResults(accumulated);
    const initialExpand: Record<number, boolean> = {};
    accumulated.forEach((r, idx) => { if (r.status === "fail") initialExpand[idx] = true; });
    setExpandedFails(initialExpand);
    setView("report");
  }, [cases, slug, skill]);

  // ── Edit-this-step flow ───────────────────────────────────────────────────

  const editStep = useCallback((stepIndex: number) => {
    if (role === "locked") {
      setToast("唯讀模式：需切換到 Editing（作者權限）");
      setView("editor");
      return;
    }
    setView("editor");
    setHighlightIndex(stepIndex);
    requestAnimationFrame(() => {
      const node = stepRefs.current[stepIndex];
      if (node) {
        const top = node.getBoundingClientRect().top + window.scrollY - HIGHLIGHT_SCROLL_OFFSET;
        window.scrollTo({ top, behavior: "smooth" });
      }
    });
  }, [role]);

  const saveThreshold = useCallback((stepIndex: number, value: number) => {
    setThresholdOverrides(prev => ({ ...prev, [stepIndex]: value }));
    setHighlightIndex(null);
    const stepNo = String(stepIndex + 1).padStart(2, "0");
    setToast(`Step ${stepNo} threshold 已更新 → ${value}（限本次 session，尚未持久化）`);
  }, []);

  // ── Save as regression ────────────────────────────────────────────────────

  const saveAsRegression = useCallback(async () => {
    if (!skill || !runCaseId) return;
    const tc = cases.find(c => c.id === runCaseId);
    if (!tc) return;
    setSavingRegression(true);
    try {
      const nextTestCases = [...skill.test_cases, {
        ...tc,
        id: `regression-${Date.now()}`,
        label: `${tc.label ?? tc.id} (regression)`,
      }];
      const res = await fetch(`/api/skill-documents/${encodeURIComponent(slug)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          test_cases: JSON.stringify(nextTestCases),
        }),
      });
      if (!res.ok) throw new Error(`save: HTTP ${res.status}`);
      setSkill(s => s ? { ...s, test_cases: nextTestCases } : s);
      setToast("已存成 regression case ✓");
      setView("editor");
    } catch (e) {
      setToast(`Save failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSavingRegression(false);
    }
  }, [cases, runCaseId, skill, slug]);

  // ── Render ────────────────────────────────────────────────────────────────

  if (loadError) {
    return <CenteredMessage>Load failed: {loadError}</CenteredMessage>;
  }
  if (!skill) {
    return <CenteredMessage>載入中...</CenteredMessage>;
  }

  return (
    <>
      <style>{`
        @media (max-width: 599px) {
          .dryrun-dialog { max-width: 100% !important; height: 100vh !important; max-height: 100vh !important; border-radius: 0 !important; }
          .dryrun-report-card { max-width: 100% !important; border-radius: 0 !important; }
          .dryrun-picker-body { flex-direction: column !important; max-height: none !important; }
          .dryrun-picker-list { width: 100% !important; max-height: 40vh !important; border-right: 0 !important; border-bottom: 1px solid ${TK.border} !important; }
        }
      `}</style>

      <TopAppBar
        slug={slug}
        role={role}
        onRoleChange={setRole}
        onDryRunClick={() => setView("picker")}
        onPrimary={role === "editing"
          ? () => setToast("Activate Trigger 在 Phase 6 接 scheduler 後啟用")
          : () => setToast("Run Skill 在 Phase 6 接上 — 目前 Locked 僅供唯讀")}
      />

      <EditorView
        skill={skill}
        thresholdOverrides={thresholdOverrides}
        highlightIndex={highlightIndex}
        stepRefs={stepRefs}
        role={role}
        onCancelEdit={() => setHighlightIndex(null)}
        onSaveThreshold={saveThreshold}
      />

      {view === "picker" && (
        <PickerOverlay
          skill={skill}
          cases={cases}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onCancel={() => { setView("editor"); setSelectedId(null); }}
          onStart={() => { if (selectedId) runDryRun(selectedId); }}
        />
      )}
      {view === "running" && (
        <RunningOverlay skill={skill} caseId={runCaseId} />
      )}
      {view === "report" && (
        <ReportOverlay
          skill={skill}
          stepResults={stepResults}
          runCaseId={runCaseId}
          cases={cases}
          expandedFails={expandedFails}
          onToggleExpand={(idx) =>
            setExpandedFails(prev => ({ ...prev, [idx]: !prev[idx] }))}
          onClose={() => setView("editor")}
          onRunAnother={() => setView("picker")}
          onSaveRegression={saveAsRegression}
          savingRegression={savingRegression}
          onEditStep={editStep}
          role={role}
        />
      )}

      {toast && <Toast text={toast} />}
    </>
  );
}

// ── Top App Bar (NEW vs old dry-run) ─────────────────────────────────────────

function TopAppBar({
  slug, role, onRoleChange, onDryRunClick, onPrimary,
}: {
  slug: string;
  role: Role;
  onRoleChange: (r: Role) => void;
  onDryRunClick: () => void;
  onPrimary: () => void;
}) {
  return (
    <div style={{
      position: "sticky", top: 0, zIndex: 30,
      background: "#fff",
      borderBottom: `1px solid ${TK.border}`,
      padding: "10px 24px",
      display: "flex", alignItems: "center", justifyContent: "space-between",
      gap: 12, flexWrap: "wrap",
    }}>
      <div style={{ font: `500 13px ${FONT.ui}`, color: TK.body, display: "flex", alignItems: "center", gap: 8 }}>
        <Link href="/skills" style={{ color: TK.body, textDecoration: "none" }}>Skills Library</Link>
        <span style={{ color: TK.faint }}>/</span>
        <Link href={`/skill-studio/${encodeURIComponent(slug)}`}
              style={{ color: TK.body, textDecoration: "none" }}>
          {slug}
        </Link>
        <span style={{ color: TK.faint }}>/</span>
        <span style={{ color: TK.title, fontWeight: 600 }}>Checklist Editor</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <RoleToggle role={role} onChange={onRoleChange} />
        <button onClick={onDryRunClick} style={{
          font: `600 12.5px ${FONT.ui}`, color: TK.ink,
          background: "#fff", border: `1px solid ${TK.pillBorder}`,
          padding: "7px 13px", borderRadius: 8, cursor: "pointer",
        }}>
          ▸ Dry-run
        </button>
        <button onClick={onPrimary} style={{
          font: `600 12.5px ${FONT.ui}`, color: "#fff",
          background: TK.blackPrimary, border: `1px solid ${TK.blackPrimary}`,
          padding: "7px 14px", borderRadius: 8, cursor: "pointer",
        }}>
          {role === "editing" ? "Activate Trigger" : "Run Skill"}
        </button>
      </div>
    </div>
  );
}

function RoleToggle({ role, onChange }: { role: Role; onChange: (r: Role) => void }) {
  return (
    <div style={{
      display: "flex", padding: 2, borderRadius: 8,
      background: "#f1f2f5", border: `1px solid ${TK.border}`,
    }}>
      <button
        onClick={() => onChange("editing")}
        style={roleTab(role === "editing")}
      >✎ Editing</button>
      <button
        onClick={() => onChange("locked")}
        style={roleTab(role === "locked")}
      >🔒 Locked</button>
    </div>
  );
}

function roleTab(active: boolean): React.CSSProperties {
  return {
    padding: "5px 11px",
    borderRadius: 6,
    border: "none",
    background: active ? "#fff" : "transparent",
    color: active ? TK.ink : TK.body,
    font: `600 12px ${FONT.ui}`,
    cursor: "pointer",
    boxShadow: active ? "0 1px 2px rgba(0,0,0,.1)" : "none",
  };
}

// ── Editor view ──────────────────────────────────────────────────────────────

function EditorView({
  skill, thresholdOverrides, highlightIndex, stepRefs, role,
  onCancelEdit, onSaveThreshold,
}: {
  skill: SkillDocument;
  thresholdOverrides: Record<number, number>;
  highlightIndex: number | null;
  stepRefs: React.RefObject<(HTMLDivElement | null)[]>;
  role: Role;
  onCancelEdit: () => void;
  onSaveThreshold: (idx: number, value: number) => void;
}) {
  const stepCount = skill.steps.length;
  const confirmedCount = skill.steps.filter(s => s.confirmed !== false).length;

  return (
    <div style={{ background: TK.page, minHeight: "calc(100vh - 56px)", padding: "32px 20px 80px" }}>
      <div style={{ maxWidth: 760, margin: "0 auto",
                     background: TK.card, borderRadius: 14,
                     boxShadow: SHADOW.card, overflow: "hidden" }}>
        {/* Header */}
        <div style={{ padding: "20px 22px 16px", borderBottom: `1px solid ${TK.border}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ ...MONO_EYEBROW, marginBottom: 6 }}>OOC DIAGNOSE · SKILL CHECKLIST</div>
              <h1 style={{ font: `650 19px ${FONT.ui}`, color: TK.title, margin: 0 }}>
                {skill.title || "事件發生時要檢查的項目"}
              </h1>
              <div style={{ fontSize: 13, color: TK.body, marginTop: 4 }}>
                {skill.slug} · {stepCount} 個檢查角度
              </div>
            </div>
            <span style={{
              font: `600 10.5px ${FONT.mono}`,
              padding: "5px 9px", borderRadius: 6,
              color: role === "editing" ? TK.accent : "#5b6470",
              background: role === "editing" ? TK.accentBg : "#eef0f3",
              whiteSpace: "nowrap", marginLeft: 12,
            }}>
              {role === "editing" ? "✎ 作者視角" : "🔒 現場視角"}
            </span>
          </div>
        </div>

        {/* Meta row */}
        <div style={{ padding: "13px 22px", background: "#fbfbfc",
                       borderBottom: `1px solid ${TK.divider}`,
                       display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={MONO_EYEBROW}>CHECKLIST · {stepCount} STEPS</span>
          <span style={{ ...MONO_EYEBROW, color: TK.monoLabel3 }}>
            {confirmedCount} / {stepCount} confirmed
          </span>
        </div>

        {/* Step rows */}
        <div style={{ padding: "6px 22px 10px" }}>
          {skill.steps.map((step, idx) => {
            const isHighlight = highlightIndex === idx;
            return (
              <div
                key={step.id || idx}
                ref={(el) => { stepRefs.current[idx] = el; }}
                style={{
                  borderBottom: `1px solid ${TK.divider}`,
                  borderRadius: isHighlight ? 11 : 0,
                  border: isHighlight ? `1.5px solid ${TK.highlightBorder}` : undefined,
                  background: isHighlight ? TK.highlightBg : "transparent",
                  marginBottom: isHighlight ? 8 : 0,
                  padding: isHighlight ? "6px 10px 0" : 0,
                  transition: "background .15s",
                }}
              >
                <StepRow step={step} index={idx} />
                {isHighlight && (
                  <InlineEditPanel
                    step={step}
                    index={idx}
                    initialValue={thresholdOverrides[idx] ?? step.threshold ?? 2}
                    onCancel={onCancelEdit}
                    onSave={(v) => onSaveThreshold(idx, v)}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Footer hint */}
        <div style={{ padding: "14px 22px", borderTop: `1px solid ${TK.border}`,
                       background: "#fbfbfc",
                       display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={SANDBOX_PILL}>✦ Sandboxed</span>
          <span style={{ fontSize: 12, color: TK.faint }}>
            Dry-run 在沙盒內執行，結果只在報告裡呈現，不會寫進這份 checklist，也不會發通知。
          </span>
        </div>
      </div>
    </div>
  );
}

function StepRow({ step, index }: { step: SkillStep; index: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 13, padding: "12px 4px" }}>
      <span style={{ fontFamily: FONT.mono, fontWeight: 600, fontSize: 12, color: TK.monoLabel3, width: 18 }}>
        {String(index + 1).padStart(2, "0")}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ font: `600 14px ${FONT.ui}`, color: TK.ink,
                       overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {step.text || step.id}
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: 7 }}>
          <span style={{ color: TK.accent, background: TK.accentBg, padding: "3px 8px", borderRadius: 6, font: `600 11px ${FONT.ui}` }}>✦ Pipeline Builder</span>
          <span style={{ color: "#7a7f88", background: "#f2f3f5", padding: "3px 8px", borderRadius: 6, font: `600 11px ${FONT.ui}` }}>pipeline ready</span>
        </div>
      </div>
      <span style={{
        font: `600 11px ${FONT.mono}`, color: TK.faint, border: `1px solid ${TK.pillBorder}`,
        padding: "5px 10px", borderRadius: 8, whiteSpace: "nowrap",
      }}>Pending</span>
      <button style={{
        font: `600 12px ${FONT.ui}`, color: "#42454d", background: "#fff",
        border: `1px solid ${TK.pillBorder}`, padding: "6px 11px", borderRadius: 8, cursor: "pointer",
      }}>View logic ⌄</button>
    </div>
  );
}

// ── Inline edit panel ────────────────────────────────────────────────────────

function InlineEditPanel({
  step, index, initialValue, onCancel, onSave,
}: {
  step: SkillStep;
  index: number;
  initialValue: number;
  onCancel: () => void;
  onSave: (value: number) => void;
}) {
  const [value, setValue] = useState<string>(String(initialValue));
  return (
    <div style={{
      background: TK.editPanelBg, border: `1px solid ${TK.editPanelBorder}`,
      borderRadius: 10, padding: "13px 14px", margin: "10px 0",
    }}>
      <div style={{ ...MONO_EYEBROW, marginBottom: 10 }}>
        EDIT THIS STEP · {step.dim ?? `第 ${index + 1} 步`} 角度
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 11, color: TK.body, marginBottom: 4 }}>Operator</div>
          <div style={{
            width: "100%", border: `1px solid ${TK.editInputBorder}`, borderRadius: 8,
            padding: "7px 10px", fontSize: 13, fontFamily: FONT.mono,
            background: "#fff", color: TK.faint, fontWeight: 600,
          }}>{step.operator ?? ">="}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: TK.body, marginBottom: 4 }}>Threshold（OOC 次數）</div>
          <input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            style={{
              width: "100%", border: `1px solid ${TK.editInputBorder}`, borderRadius: 8,
              padding: "7px 10px", fontSize: 13, fontFamily: FONT.mono, background: "#fff",
            }}
            autoFocus
          />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginBottom: 8 }}>
        <button onClick={onCancel} style={ghostButton}>Cancel</button>
        <button
          onClick={() => onSave(Number(value) || 0)}
          style={{ ...primaryButton, background: TK.accent, border: `1px solid ${TK.accent}` }}
        >
          Save threshold
        </button>
      </div>
      <div style={{ fontSize: 11, color: TK.faint }}>
        改完直接再 Dry-run 一次，報告會反映新門檻。
      </div>
    </div>
  );
}

// ── Picker overlay ───────────────────────────────────────────────────────────

function PickerOverlay({
  skill, cases, selectedId, onSelect, onCancel, onStart,
}: {
  skill: SkillDocument;
  cases: TestCase[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCancel: () => void;
  onStart: () => void;
}) {
  const selected = cases.find(c => c.id === selectedId) ?? cases[0];
  return (
    <Scrim onClose={onCancel} zIndex={40}>
      <div className="dryrun-dialog" style={dialogStyle(880)}>
        <div style={{ padding: "20px 22px 14px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
            <h2 style={{ font: `650 19px ${FONT.ui}`, color: TK.title, margin: 0 }}>
              Select test case for dry-run
            </h2>
            <span style={SANDBOX_PILL}>✦ Sandboxed</span>
          </div>
          <p style={{ fontSize: 13, color: TK.body, margin: 0 }}>
            這個 skill 將在沙盒內針對選擇的 test case 執行，所有結果僅供驗證與評估，不會寫入正式系統。
          </p>
          <div style={{ display: "flex", marginTop: 14, background: "#f1f2f5", borderRadius: 9, padding: 3, width: "fit-content" }}>
            <div style={tab(true)}>📁 From past event</div>
            <div style={tab(false)} title="Manual input — Phase 2">✍️ Manual input</div>
          </div>
        </div>

        {cases.length === 0 ? (
          <div style={{ padding: "40px 22px", color: TK.faint, fontSize: 13, textAlign: "center",
                         borderTop: `1px solid ${TK.border}` }}>
            這個 skill 沒有過去事件可供 dry-run。
          </div>
        ) : (
          <div className="dryrun-picker-body" style={{ display: "flex", borderTop: `1px solid ${TK.border}`, flex: 1, minHeight: 0 }}>
            <div className="dryrun-picker-list" style={{ width: "48%", overflowY: "auto", borderRight: `1px solid ${TK.border}`, padding: "12px 14px", maxHeight: "55vh" }}>
              {cases.map((tc) => {
                const isSelected = selected?.id === tc.id;
                return (
                  <div
                    key={tc.id}
                    onClick={() => onSelect(tc.id)}
                    style={{
                      padding: "11px 12px",
                      borderRadius: 9,
                      border: `1.5px solid ${isSelected ? TK.highlightBorder : TK.border}`,
                      background: isSelected ? "#f6f6fd" : "#fff",
                      marginBottom: 6,
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ width: 8, height: 8, borderRadius: 4, background: TK.amberDot, display: "inline-block" }} />
                      <span style={{ font: `600 13.5px ${FONT.mono}` }}>
                        {skill.slug} — {tc.label ?? tc.id}
                      </span>
                    </div>
                    <div style={{ fontSize: 12, color: TK.faint, marginTop: 3, marginLeft: 16 }}>
                      Past OOC on {tc.label ?? tc.id}
                    </div>
                  </div>
                );
              })}
            </div>
            <div style={{ flex: 1, background: "#f8f9fb", padding: "16px 18px", overflowY: "auto", maxHeight: "55vh" }}>
              <div style={MONO_EYEBROW}>PAYLOAD PREVIEW</div>
              <div style={{ font: `650 15px ${FONT.ui}`, color: TK.title, margin: "6px 0 12px" }}>
                {skill.slug} — {selected?.label ?? selected?.id ?? "—"}
              </div>
              <pre style={{
                background: "#fff", border: `1px solid ${TK.border}`, borderRadius: 10,
                padding: 14, font: `500 12px/1.7 ${FONT.mono}`, color: "#3a3d44",
                whiteSpace: "pre-wrap", wordBreak: "break-all", overflow: "auto",
                maxHeight: "40vh", margin: 0,
              }}>
                {JSON.stringify(selected?.payload ?? {}, null, 2)}
              </pre>
            </div>
          </div>
        )}

        <div style={{ padding: "14px 22px", borderTop: `1px solid ${TK.border}`,
                       display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 12, color: TK.faint2 }}>
            Test 結果不會發通知；若要保留為 regression case，跑完按 Save。
          </span>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={onCancel} style={ghostButton}>Cancel</button>
            <button
              onClick={onStart}
              disabled={!selected || cases.length === 0}
              style={{ ...primaryButton, opacity: !selected ? 0.5 : 1 }}
            >
              ▸ Start dry-run
            </button>
          </div>
        </div>
      </div>
    </Scrim>
  );
}

// ── Running overlay ──────────────────────────────────────────────────────────

function RunningOverlay({ skill, caseId }: { skill: SkillDocument; caseId: string | null }) {
  return (
    <Scrim zIndex={45}>
      <div style={{
        width: 260, height: 170, borderRadius: 14, background: "linear-gradient(180deg,#fbfbff,#f6f7fd)",
        boxShadow: SHADOW.running,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14,
      }}>
        <div style={{
          width: 30, height: 30, borderRadius: "50%",
          border: `3px solid #e3e3f3`, borderTopColor: TK.accent,
          animation: "spin .8s linear infinite",
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        <div style={{ font: `600 14px ${FONT.ui}`, color: TK.ink }}>Running dry-run in sandbox…</div>
        <div style={{ font: `500 11px ${FONT.mono}`, color: TK.faint2 }}>
          {caseId ?? "—"} · {skill.steps.length} checks
        </div>
      </div>
    </Scrim>
  );
}

// ── Report overlay ───────────────────────────────────────────────────────────

function ReportOverlay({
  skill, stepResults, runCaseId, cases, expandedFails, onToggleExpand,
  onClose, onRunAnother, onSaveRegression, savingRegression, onEditStep, role,
}: {
  skill: SkillDocument;
  stepResults: StepResult[];
  runCaseId: string | null;
  cases: TestCase[];
  expandedFails: Record<number, boolean>;
  onToggleExpand: (idx: number) => void;
  onClose: () => void;
  onRunAnother: () => void;
  onSaveRegression: () => void;
  savingRegression: boolean;
  onEditStep: (idx: number) => void;
  role: Role;
}) {
  const total = stepResults.length;
  const passCount = stepResults.filter(r => r.status === "pass").length;
  const failCount = stepResults.filter(r => r.status === "fail").length;
  const isAlarm = failCount > 0;
  const tc = cases.find(c => c.id === runCaseId);

  return (
    <Scrim onClose={onClose} zIndex={50} alignTop>
      <div className="dryrun-report-card" style={{
        maxWidth: 620, width: "100%", borderRadius: 15, background: "#fff",
        boxShadow: SHADOW.report, overflow: "hidden",
        animation: "dryrunReport .2s ease-out",
      }}>
        <style>{`@keyframes dryrunReport { from { transform: translateY(7px); } to { transform: translateY(0); } }`}</style>

        <div style={{ padding: "18px 20px 16px", borderBottom: `1px solid ${TK.border}` }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
            <div style={{
              width: 34, height: 34, borderRadius: 9,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 17, fontWeight: 700,
              background: isAlarm ? "#fbe9e6" : TK.passBadgeBg,
              color: isAlarm ? TK.fail : TK.pass,
            }}>{isAlarm ? "⚡" : "✓"}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={MONO_EYEBROW}>DIAGNOSTIC REPORT · DRY-RUN</span>
                <button onClick={onClose} style={{
                  background: "transparent", border: "none", color: TK.faint,
                  fontSize: 22, cursor: "pointer", padding: 0, lineHeight: 1,
                }}>×</button>
              </div>
              <h2 style={{ font: `650 18px ${FONT.ui}`,
                            color: isAlarm ? TK.fail : TK.pass, margin: "6px 0 4px" }}>
                {isAlarm
                  ? `ALARM RAISED · ${failCount} findings flagged`
                  : `NO ALARM · all ${total} checks passed`}
              </h2>
              <div style={{ fontSize: 12.5, color: TK.body }}>
                {isAlarm
                  ? `${passCount} of ${total} checks passed · 請依下方建議行動處理。`
                  : `所有 checklist 都 pass — 沒有需要工程師處理的事項。`}
              </div>
              <div style={{ ...MONO_EYEBROW, color: "#aeb2ba", marginTop: 8,
                             display: "flex", alignItems: "center", gap: 8 }}>
                <span>Test case · {skill.slug} — {tc?.label ?? tc?.id ?? "—"}</span>
                <span style={SANDBOX_PILL}>✦ Sandboxed</span>
              </div>
            </div>
          </div>
        </div>

        <div style={{ padding: "11px 20px", background: "#f8f9fb",
                       borderBottom: `1px solid ${TK.border}`, fontSize: 12.5 }}>
          ⚙ Checklist ·{" "}
          <span style={{ color: TK.pass, fontWeight: 700 }}>{passCount} pass</span>
          {" / "}
          <span style={{ color: failCount > 0 ? TK.fail : "#9aa0a8", fontWeight: 700 }}>
            {failCount} fail
          </span>
        </div>

        <div style={{ padding: "14px 20px 6px" }}>
          <div style={{ ...MONO_EYEBROW, marginBottom: 10 }}>CHECKLIST · {total} STEPS</div>
          {stepResults.length === 0 && (
            <div style={{ fontSize: 13, color: TK.faint, padding: "10px 0" }}>
              沒有任何 step result 回傳 — 可能 skill 沒綁 pipeline。
            </div>
          )}
          {stepResults.map((r, idx) => {
            const step = skill.steps[idx];
            const stepNo = String(idx + 1).padStart(2, "0");
            if (r.status !== "fail") {
              return (
                <div key={idx} style={{
                  border: `1px solid ${TK.passBoxBorder}`, background: TK.passBoxBg,
                  borderRadius: 10, padding: "10px 12px", marginBottom: 8,
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{
                      color: TK.pass, background: TK.passBadgeBg,
                      border: `1px solid ${TK.passBadgeBorder}`,
                      font: `600 10px ${FONT.mono}`, padding: "4px 8px", borderRadius: 6, whiteSpace: "nowrap",
                    }}>{stepNo} · PASS</span>
                    <span style={{ flex: 1, font: `600 13.5px ${FONT.ui}`, color: TK.ink,
                                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {step?.text ?? r.step_id}
                    </span>
                    {r.note && (
                      <span style={{ font: `500 12px ${FONT.mono}`, color: "#7c8089" }}>{r.note}</span>
                    )}
                  </div>
                  <StepCharts result={r} />
                </div>
              );
            }
            const expanded = expandedFails[idx];
            return (
              <div key={idx} style={{
                border: `1.5px solid ${TK.failBoxBorder}`, background: TK.failBoxBg,
                borderRadius: 10, padding: "10px 12px", marginBottom: 8,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}
                      onClick={() => onToggleExpand(idx)}>
                  <span style={{
                    color: TK.fail, background: TK.failBadgeBg,
                    border: `1px solid ${TK.failBadgeBorder}`,
                    font: `600 10px ${FONT.mono}`, padding: "4px 8px", borderRadius: 6, whiteSpace: "nowrap",
                  }}>{stepNo} · FAIL</span>
                  <span style={{ flex: 1, font: `600 13.5px ${FONT.ui}`, color: TK.ink,
                                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {step?.text ?? r.step_id}
                  </span>
                  {role === "editing" ? (
                    <button onClick={(e) => { e.stopPropagation(); onEditStep(idx); }} style={{
                      font: `600 12.5px ${FONT.ui}`, color: TK.accentLink, background: "transparent",
                      border: "none", cursor: "pointer", padding: 0, whiteSpace: "nowrap",
                    }}>
                      Edit this step →
                    </button>
                  ) : (
                    <span style={{ font: `500 11px ${FONT.ui}`, color: TK.faint, whiteSpace: "nowrap" }}>
                      🔒 需作者權限
                    </span>
                  )}
                </div>
                {expanded && (
                  <div style={{
                    background: "#fff", border: `1px solid ${TK.failDetailBorder}`,
                    borderRadius: 8, padding: "11px 13px", marginTop: 8,
                  }}>
                    <KV k="value" v={String(r.value ?? "—")} mono />
                    <KV k="operator" v={String(r.operator ?? ">=")} mono />
                    <KV k="threshold" v={String(r.threshold ?? "—")} mono />
                    {r.note && <KV k="note" v={r.note} mono color={TK.fail} />}
                  </div>
                )}
                <StepCharts result={r} />
              </div>
            );
          })}
        </div>

        <div style={{ padding: "14px 20px", borderTop: `1px solid ${TK.border}`,
                       display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <button onClick={onClose} style={ghostButton}>← Back to editor</button>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={onRunAnother} style={ghostButton}>Run another case</button>
            <button onClick={onSaveRegression} disabled={savingRegression} style={primaryButton}>
              {savingRegression ? "Saving…" : "Save as regression"}
            </button>
          </div>
        </div>
      </div>
    </Scrim>
  );
}

// ── Helpers + shared bits ────────────────────────────────────────────────────

function StepCharts({ result }: { result: StepResult }) {
  const charts = result.result_summary?.charts ?? [];
  if (charts.length === 0) return null;
  return (
    <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 10 }}>
      {charts.map((c, i) => (
        <div key={`${c.node_id}-${i}`} style={{
          background: "#fff",
          border: `1px solid ${TK.border}`,
          borderRadius: 8,
          padding: "10px 12px",
        }}>
          {c.title && (
            <div style={{ ...MONO_EYEBROW, marginBottom: 6 }}>{c.title}</div>
          )}
          <ChartRenderer spec={c.chart_spec} height={220} />
        </div>
      ))}
    </div>
  );
}

function Scrim({
  children, onClose, zIndex, alignTop,
}: {
  children: React.ReactNode;
  onClose?: () => void;
  zIndex: number;
  alignTop?: boolean;
}) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex,
        background: zIndex >= 50 ? TK.scrimHeavy : TK.scrimMid,
        display: "flex",
        alignItems: alignTop ? "flex-start" : "center",
        justifyContent: "center",
        padding: alignTop ? "36px 24px" : 28,
        overflow: "auto",
      }}
    >
      <div onClick={(e) => e.stopPropagation()} style={{ width: "100%", maxWidth: "100%", display: "flex", justifyContent: "center" }}>
        {children}
      </div>
    </div>
  );
}

function Toast({ text }: { text: string }) {
  return (
    <div style={{
      position: "fixed", bottom: 28, left: "50%", transform: "translateX(-50%)",
      background: TK.blackPrimary, color: "#fff", padding: "10px 16px", borderRadius: 9,
      fontSize: 13, boxShadow: "0 8px 24px rgba(0,0,0,.25)", zIndex: 60,
      maxWidth: 480,
    }}>{text}</div>
  );
}

function KV({ k, v, mono, color }: {
  k: string;
  v: string;
  mono?: boolean;
  color?: string;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: 6, fontSize: 12.5, marginBottom: 4 }}>
      <span style={{ fontFamily: FONT.mono, color: "#a08a86" }}>{k}</span>
      <span style={{ fontFamily: mono ? FONT.mono : FONT.ui, color: color ?? TK.ink }}>{v}</span>
    </div>
  );
}

function CenteredMessage({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ background: TK.page, minHeight: "100vh",
                   display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ background: TK.card, padding: "30px 36px", borderRadius: 14, boxShadow: SHADOW.card,
                     fontSize: 14, color: TK.body, maxWidth: 460 }}>{children}</div>
    </div>
  );
}

function safeJson<T>(input: unknown, fallback: T): T {
  if (typeof input !== "string") return (input as T) ?? fallback;
  if (!input) return fallback;
  try { return JSON.parse(input) as T; } catch { return fallback; }
}

function adaptPastEvent(raw: unknown): TestCase {
  const obj = (raw ?? {}) as Record<string, unknown>;
  const equip = String(obj.equipment_id ?? obj.tool_id ?? obj.id ?? "case");
  return {
    id: String(obj.id ?? `${equip}-${Math.random().toString(36).slice(2, 8)}`),
    label: equip,
    severity: typeof obj.severity === "string" ? obj.severity : null,
    payload: (obj.payload as Record<string, unknown>) ?? obj,
  };
}

interface SseFrame { name: string; data: unknown; }

function parseSseFrame(frame: string): SseFrame | null {
  let name = "";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!name && dataLines.length === 0) return null;
  let data: unknown = dataLines.join("\n");
  try { data = JSON.parse(dataLines.join("\n")); } catch { /* keep as string */ }
  return { name, data };
}

function adaptStepDone(data: unknown): StepResult | null {
  if (!data || typeof data !== "object") return null;
  const d = data as Record<string, unknown>;
  const sr = (d.step_result as Record<string, unknown>) ?? d;
  const status = String(sr.status ?? "skipped");
  if (!["pass", "fail", "skipped"].includes(status)) return null;
  return {
    step_id: String(sr.step_id ?? d.step_id ?? ""),
    status: status as StepResult["status"],
    value: sr.value as number | string | undefined,
    threshold: sr.threshold as number | string | undefined,
    operator: sr.operator as string | undefined,
    note: sr.note as string | undefined,
    result_summary: (sr.result_summary as StepResult["result_summary"]) ?? null,
  };
}

function tab(active: boolean): React.CSSProperties {
  return {
    padding: "7px 14px", borderRadius: 7,
    font: `600 12.5px ${FONT.ui}`,
    color: active ? TK.title : "#73777f",
    background: active ? "#fff" : "transparent",
    boxShadow: active ? "0 1px 2px rgba(0,0,0,.1)" : "none",
    cursor: active ? "default" : "not-allowed",
    whiteSpace: "nowrap",
  };
}

const dialogStyle = (maxWidth: number): React.CSSProperties => ({
  width: "100%", maxWidth, maxHeight: "88vh",
  background: "#fff", borderRadius: 15, boxShadow: SHADOW.dialog,
  display: "flex", flexDirection: "column",
});

const primaryButton: React.CSSProperties = {
  background: TK.blackPrimary, color: "#fff", padding: "9px 15px", borderRadius: 9,
  font: `600 13px ${FONT.ui}`, border: "1px solid " + TK.blackPrimary, cursor: "pointer",
};

const ghostButton: React.CSSProperties = {
  background: "transparent", color: TK.ink, padding: "8px 13px", borderRadius: 8,
  font: `600 12.5px ${FONT.ui}`, border: `1px solid ${TK.pillBorder}`, cursor: "pointer",
};
