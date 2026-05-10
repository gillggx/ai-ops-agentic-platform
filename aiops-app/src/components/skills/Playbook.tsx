"use client";

/**
 * Skill Playbook — port of prototype `Skill Playbook.html` + `app.jsx`.
 *
 * Two modes:
 *   - author (URL /skills/[slug]/edit): editable text, TriggerConfig open,
 *     pipeline expand, "Confirm pipeline" / "Edit blocks" / "Open Builder",
 *     bottom AddStep input.
 *   - run    (URL /skills/[slug]):     read-only steps, status pills,
 *     SummaryReport after run, RunTimeline rail.
 *
 * Both share the same StepBlock/ExpandedPipeline/SuggestionPanel components
 * (matches prototype's design where switching is a `t.mode` flag).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Icon, Badge, Btn, safeParse,
  type SkillDetail, type SkillStep, type TriggerConfig as TC, type SuggestedAction,
  type ConfirmCheck,
} from "./atoms";
import { TriggerConfigEditor, migrateTrigger } from "./TriggerConfig";
import PipelineCanvasMini, { type MiniBlock } from "./PipelineCanvasMini";
import TestCaseSelector, { type TestCase } from "./TestCaseSelector";

interface ApiDetail { ok: boolean; data: SkillDetail; error?: { message: string } | null }

/** Phase 11 v9 — full SSE step_done payload from SkillRunnerService.parseRunResult.
 *  threshold / operator / duration_ms were previously dropped by the
 *  frontend; SummaryReport now needs them to render a real pipeline-result
 *  table (per user feedback「report 應該看得到 pipeline 結果」). */
/** Per-node dataframe preview from sidecar (passed through Java
 *  SkillRunner.extractDataViews). Compatible-ish with alarms' DataView
 *  but with extra node_id/block/port for context. */
type SkillDataView = {
  node_id: string;
  block: string;
  port: string;
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
};

type StepRunResult = {
  status: "pass" | "fail";
  value: string;
  note: string;
  threshold?: string | number | null;
  operator?: string | null;
  duration_ms?: number | null;
  data_views?: SkillDataView[];
};

function parseRunResult(data: Record<string, unknown>): StepRunResult {
  const rawDvs = (data.data_views as unknown[]) ?? [];
  const data_views: SkillDataView[] = Array.isArray(rawDvs)
    ? rawDvs
        .filter((d): d is Record<string, unknown> => !!d && typeof d === "object")
        .map((d) => ({
          node_id: String(d.node_id ?? ""),
          block: String(d.block ?? ""),
          port: String(d.port ?? ""),
          columns: Array.isArray(d.columns) ? (d.columns as unknown[]).map(String) : [],
          rows: Array.isArray(d.rows) ? (d.rows as Record<string, unknown>[]) : [],
          total: typeof d.total === "number" ? d.total : 0,
        }))
    : [];
  return {
    status: (data.status as "pass" | "fail") || "pass",
    value: (data.value as string) ?? "",
    note: (data.note as string) ?? "",
    threshold: (data.threshold as string | number | null | undefined) ?? null,
    operator: (data.operator as string | null | undefined) ?? null,
    duration_ms: (data.duration_ms as number | null | undefined) ?? null,
    data_views,
  };
}

export default function Playbook({
  slug, mode,
}: {
  slug: string;
  mode: "author" | "run";
}) {
  const router = useRouter();
  const [skill, setSkill] = useState<SkillDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Local edits
  const [title, setTitle] = useState("");
  const [trigger, setTrigger] = useState<TC>({
    type: "event", event: "OOC", target: { kind: "all", ids: [] },
  });
  const [steps, setSteps] = useState<SkillStep[]>([]);
  const [confirmCheck, setConfirmCheck] = useState<ConfirmCheck | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(dirty);
  useEffect(() => { dirtyRef.current = dirty; }, [dirty]);

  // Run state
  const [runStatuses, setRunStatuses] = useState<Record<string, "queued" | "running" | "done">>({});
  const [runActiveStep, setRunActiveStep] = useState<string | null>(null);
  const [runState, setRunState] = useState<"idle" | "running" | "done">("idle");
  const [runResults, setRunResults] = useState<Record<string, StepRunResult>>({});
  // Phase 11 v7 — Confirm step has its own status/result so the timeline can
  // show「正在跑 C1…」instead of UI 看起來卡死（之前 SSE confirm_* 事件被丟掉）
  const [confirmRunStatus, setConfirmRunStatus] = useState<"queued" | "running" | "done" | null>(null);
  const [confirmRunResult, setConfirmRunResult] = useState<StepRunResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [showCaseSelector, setShowCaseSelector] = useState(false);
  const [selectedCase, setSelectedCase] = useState<TestCase | null>(null);
  const [showSummary, setShowSummary] = useState(false);

  /* Load (extracted into a callback so children can trigger re-fetch
     after an external bind — e.g. Pipeline Builder tab confirms back). */
  const reload = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    fetch(`/api/skill-documents/${encodeURIComponent(slug)}`, { cache: "no-store" })
      .then(async (res) => {
        const json = (await res.json()) as ApiDetail;
        if (cancelled) return;
        if (!res.ok || !json.ok) throw new Error(json.error?.message || `HTTP ${res.status}`);
        setSkill(json.data);
        setTitle(json.data.title);
        setTrigger(migrateTrigger(safeParse<TC>(
          json.data.trigger_config,
          { type: "event", event: "OOC", target: { kind: "all", ids: [] } },
        )));
        setSteps(safeParse<SkillStep[]>(json.data.steps, []));
        setConfirmCheck(json.data.confirm_check
          ? safeParse<ConfirmCheck | null>(json.data.confirm_check, null)
          : null);
        setDirty(false);
      })
      .catch((e: Error) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  useEffect(() => { return reload(); }, [reload]);

  /* Author mode auto-expand pending step */
  useEffect(() => {
    if (mode === "author" && expandedId === null) {
      const pending = steps.find((s) => s.pending && !s.confirmed);
      if (pending) setExpandedId(pending.id);
    }
  }, [mode, steps, expandedId]);

  const markDirty = () => setDirty(true);

  /* Save */
  const onSave = async () => {
    if (!skill) return;
    const body = {
      title,
      trigger_config: JSON.stringify(trigger),
      steps: JSON.stringify(steps),
    };
    const res = await fetch(`/api/skill-documents/${encodeURIComponent(slug)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const json = await res.json();
    if (!res.ok || !json.ok) {
      alert("儲存失敗：" + (json.error?.message || res.status));
      return;
    }
    setDirty(false);
  };

  const onPublish = async () => {
    if (!skill) return;
    // Phase 11 v7 — copy clarified: this is "啟用 trigger 自動執行", not
    // marketplace-style sharing. DB status field still flips draft → stable.
    const isAlreadyActive = skill.status === "stable";
    const msg = isAlreadyActive
      ? "這個 Skill 已經是 Active 狀態。重新儲存並重新登錄 trigger？"
      : "啟用後系統會在 trigger 條件成立時自動執行此 Skill。\nDraft 狀態下只能手動 Run / Test。\n\n確認啟用？";
    if (!confirm(msg)) return;
    await onSave();
    const res = await fetch(`/api/skill-documents/${encodeURIComponent(slug)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "stable" }),
    });
    if (res.ok) router.refresh();
  };

  const onDelete = async () => {
    if (!skill) return;
    const stepCount = steps.length;
    const hasConfirm = !!confirmCheck;
    const pipelineCount = steps.filter((s) => s.pipeline_id != null).length + (hasConfirm && confirmCheck.pipeline_id ? 1 : 0);
    const summary = `這個 skill 有 ${stepCount} 個 checklist step` +
                    (hasConfirm ? "、1 個 confirm check" : "") +
                    `、共 ${pipelineCount} 條 pipeline 會一起被刪除。`;
    if (!confirm(`確認刪除「${title || slug}」？\n\n${summary}\n\n此動作不可還原。`)) return;
    const res = await fetch(`/api/skill-documents/${encodeURIComponent(slug)}`, { method: "DELETE" });
    if (res.ok) {
      router.replace("/skills");
    } else {
      const j = await res.json().catch(() => ({}));
      alert("刪除失敗：" + (j?.error?.message ?? `HTTP ${res.status}`));
    }
  };

  /* Run + test simulation */
  const onRunClick = () => {
    setShowSummary(false);
    setShowCaseSelector(true);
  };

  const runSkill = async (testCase: TestCase | null, triggerPayload: Record<string, unknown>) => {
    setSelectedCase(testCase);
    setShowCaseSelector(false);
    setShowSummary(false);
    setRunState("running");
    setRunStatuses(Object.fromEntries(steps.map((s) => [s.id, "queued"])));
    setRunResults({});
    setConfirmRunStatus(confirmCheck ? "queued" : null);
    setConfirmRunResult(null);
    setRunError(null);

    try {
      const res = await fetch(`/api/skill-documents/${encodeURIComponent(slug)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          trigger_payload: triggerPayload,
          is_test: testCase != null,
        }),
      });
      if (!res.ok || !res.body) {
        // Phase 11 v7 — drop the silent client-simulation fallback. Surface the
        // real upstream error instead so user can see what's broken.
        const txt = await res.text().catch(() => "");
        setRunError(`執行失敗 (HTTP ${res.status})${txt ? ` · ${txt.slice(0, 240)}` : ""}`);
        setRunState("idle");
        return;
      }
      // SSE consumer — backend events: run_start / confirm_start / confirm_done
      // / step_start / step_done / done / error. All seven now handled (v6
      // only handled 3, which is why Re-run looked stuck during confirm phase).
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        // eslint-disable-next-line no-cond-assign
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          if (!frame.trim()) continue;
          let evt = "message"; const dataLines: string[] = [];
          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) evt = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          let data: Record<string, unknown> = {};
          try { data = JSON.parse(dataLines.join("\n")); } catch { /* ignore */ }
          if (evt === "run_start") {
            // Reserved — payload contains run_id + step_count, no UI need yet.
          } else if (evt === "confirm_start") {
            setConfirmRunStatus("running");
            setRunActiveStep("__confirm__");
          } else if (evt === "confirm_done") {
            setConfirmRunStatus("done");
            setConfirmRunResult(parseRunResult(data));
          } else if (evt === "step_start") {
            const sid = data.step_id as string;
            setRunActiveStep(sid);
            setRunStatuses((prev) => ({ ...prev, [sid]: "running" }));
          } else if (evt === "step_done") {
            const sid = data.step_id as string;
            setRunStatuses((prev) => ({ ...prev, [sid]: "done" }));
            setRunResults((prev) => ({ ...prev, [sid]: parseRunResult(data) }));
          } else if (evt === "done") {
            setRunState("done");
            setRunActiveStep(null);
            setShowSummary(true);
          } else if (evt === "error") {
            setRunError(String(data.message ?? "unknown error"));
            setRunState("idle");
            setRunActiveStep(null);
          }
        }
      }
    } catch (e) {
      console.error("run failed:", e);
      setRunError(`執行中斷：${String(e)}`);
      setRunState("idle");
      setRunActiveStep(null);
    }
  };

  const resetRun = () => {
    setRunState("idle");
    setRunStatuses({});
    setRunActiveStep(null);
    setRunResults({});
    setConfirmRunStatus(null);
    setConfirmRunResult(null);
    setRunError(null);
  };

  // Phase 11 v5 — sign-off removed. step.confirmed is now set automatically
  // by bind-pipeline (binding from Builder = confirmed). No manual toggle.

  const updateStepText = (id: string, text: string) => {
    setSteps((prev) => prev.map((s) => s.id === id ? { ...s, text } : s));
    markDirty();
  };

  const updateStepActions = (id: string, actions: SuggestedAction[]) => {
    setSteps((prev) => prev.map((s) => s.id === id ? { ...s, suggested_actions: actions } : s));
    markDirty();
  };

  const removeStep = (id: string) => {
    setSteps((prev) => prev.filter((s) => s.id !== id));
    markDirty();
  };

  /** Phase 11 v5 — open Pipeline Builder for any slot (confirm | step:NEW |
   *  step:<id>). Replaces the silent AI translate. The Builder Confirm
   *  banner POSTs back to /bind-pipeline; window-focus refresh on this page
   *  picks up the new pipeline_id. */
  const openSlotInBuilder = useCallback(async (slot: string, instruction: string) => {
    if (!instruction.trim() && slot.startsWith("step:NEW")) return;
    try {
      const r = await fetch(
        `/api/skill-documents/${encodeURIComponent(slug)}/builder-url?`
        + `slot=${encodeURIComponent(slot)}`
        + `&instruction=${encodeURIComponent(instruction)}`,
      );
      const j = await r.json();
      if (!r.ok) throw new Error(j?.error?.message ?? `HTTP ${r.status}`);
      const url = j.data?.builder_url ?? j.builder_url;
      if (!url) throw new Error("builder_url missing");
      window.open(url, "_blank", "noopener");
    } catch (e) {
      alert("Open Builder failed: " + String(e));
    }
  }, [slug]);

  const addStep = async (text: string) => {
    await openSlotInBuilder("step:NEW", text);
  };

  /** Phase 11 v7 — read-only Inspect link to Pipeline Builder. Without this,
   *  BuilderLayout's "← back" defaults to /admin/pipeline-builder which
   *  redirects to /skills (Library) — user reported they "leave but end up
   *  in skill list, not the skill". Writing this lightweight ctx makes
   *  the back button return to the originating Skill page. */
  const openInspect = useCallback((pipelineId: number) => {
    if (typeof window !== "undefined") {
      try {
        sessionStorage.setItem("pb:back_to_skill", JSON.stringify({
          skill_slug: slug,
          mode,
        }));
      } catch { /* ignore */ }
    }
    window.open(`/admin/pipeline-builder/${pipelineId}`, "_blank", "noopener");
  }, [slug, mode]);

  if (loading) {
    return (
      <div className="skill-surface" style={{ padding: 60, textAlign: "center", color: "var(--ink-3)" }}>
        <span className="skill-spinner" style={{ marginRight: 8 }}/> 載入中…
      </div>
    );
  }
  if (error) {
    return (
      <div className="skill-surface" style={{ padding: 60, textAlign: "center" }}>
        <div style={{ color: "var(--fail)", fontSize: 14, fontWeight: 500 }}>載入失敗：{error}</div>
        <Link href="/skills" style={{ marginTop: 12, display: "inline-block", color: "var(--ink-2)", textDecoration: "underline" }}>
          回 Library
        </Link>
      </div>
    );
  }
  if (!skill) return null;

  return (
    <div className="skill-surface">
      <TopBar
        slug={slug}
        title={title}
        mode={mode}
        runState={runState}
        dirty={dirty}
        onTitleChange={(v) => { setTitle(v); markDirty(); }}
        onSave={onSave}
        onPublish={onPublish}
        onRun={onRunClick}
        onReset={resetRun}
        onDelete={onDelete}
      />

      <div style={{
        display: "flex", justifyContent: "center",
        gap: 0, maxWidth: 1400, margin: "0 auto",
      }}>
        <main style={{ flex: 1, maxWidth: 860, padding: "0 28px 80px" }}>
          <PlaybookHeader
            skill={skill}
            title={title}
            trigger={trigger}
            setTrigger={(t) => { setTrigger(t); markDirty(); }}
            mode={mode}
            hasConfirm={!!confirmCheck}
            stepCount={steps.length}
          />

          {showSummary && runState === "done" && (
            <SummaryReport
              steps={steps}
              results={runResults}
              testCase={selectedCase}
              onRerun={() => { setShowSummary(false); setShowCaseSelector(true); }}
              onClose={() => setShowSummary(false)}
              confirmCheck={confirmCheck}
              confirmRunResult={confirmRunResult}
              onInspect={openInspect}
            />
          )}

          {/* Phase 11 v2 — CONFIRMATION (optional gating step). Author mode
              shows the slot even when empty (so user can add); Run mode hides
              the section entirely if no confirm step is configured. */}
          {(mode === "author" || confirmCheck) && (
            <ConfirmSection
              slug={slug}
              mode={mode}
              confirmCheck={confirmCheck}
              onSet={(cc) => { setConfirmCheck(cc); markDirty(); }}
              onReload={reload}
              onInspect={openInspect}
            />
          )}

          <div style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: "10px 0 18px", marginTop: 6,
          }}>
            <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-3)", letterSpacing: "0.08em" }}>
              CHECKLIST · {steps.length} STEP{steps.length === 1 ? "" : "S"}
            </span>
            <span style={{ flex: 1, height: 1, background: "var(--line)" }}/>
            <span style={{ fontSize: 11, color: "var(--ink-3)" }}>
              {steps.filter((s) => s.confirmed).length} / {steps.length} confirmed
            </span>
          </div>

          {steps.map((s, i) => (
            <StepBlock
              key={s.id}
              step={s} index={i}
              mode={mode}
              expanded={expandedId === s.id}
              onToggle={() => setExpandedId(expandedId === s.id ? null : s.id)}
              runStatus={runStatuses[s.id]}
              runResult={runResults[s.id]}
              onTextChange={(t) => updateStepText(s.id, t)}
              onActionsChange={(a) => updateStepActions(s.id, a)}
              onRemove={() => removeStep(s.id)}
              onOpenInBuilder={(text) => void openSlotInBuilder(`step:${s.id}`, text)}
              onInspect={openInspect}
              onActionsExpand={() => setExpandedId(expandedId === s.id ? null : s.id)}
              actionsExpanded={expandedId === s.id}
            />
          ))}

          {steps.length === 0 && mode === "run" && (
            <div style={{
              marginTop: 30, padding: "32px 18px", textAlign: "center",
              border: "1px dashed var(--line-strong)", borderRadius: 10,
              color: "var(--ink-3)", fontSize: 13,
            }}>
              這個 skill 還沒有任何 step — 請先在 Author 模式新增。
            </div>
          )}

          {/* Phase 11 v10 — AddStep available in BOTH modes (per user
              feedback: 兩個 mode 的功能應該一致 — operator 在 Execute 時
              也想加新 check). */}
          <AddStep onAdd={addStep}/>
        </main>

        {runState !== "idle" && (
          <RunTimeline
            steps={steps}
            runState={runState}
            activeStepId={runActiveStep}
            runStatuses={runStatuses}
            runResults={runResults}
            confirmCheck={confirmCheck}
            confirmRunStatus={confirmRunStatus}
            confirmRunResult={confirmRunResult}
          />
        )}
      </div>

      {runError && (
        <div style={{
          maxWidth: 1400, margin: "12px auto 0", padding: "10px 28px",
        }}>
          <div style={{
            padding: "10px 14px", borderRadius: 8,
            background: "var(--fail-bg)", border: "1px solid var(--fail)",
            color: "var(--fail)", fontSize: 12.5, lineHeight: 1.5,
            display: "flex", alignItems: "flex-start", gap: 10,
          }}>
            <span style={{ fontSize: 14, lineHeight: 1 }}>⚠</span>
            <div style={{ flex: 1 }}>
              <strong>Skill 執行失敗</strong>
              <div style={{ marginTop: 4, color: "var(--ink-2)", fontFamily: "ui-monospace, monospace", fontSize: 11.5 }}>
                {runError}
              </div>
            </div>
            <button onClick={() => setRunError(null)} aria-label="dismiss"
              style={{
                all: "unset", cursor: "pointer", padding: 4, color: "var(--fail)",
              }}>×</button>
          </div>
        </div>
      )}

      <TestCaseSelector
        open={showCaseSelector}
        slug={slug}
        skillTriggerType={
          trigger.type === "event" || trigger.type === "system" ? "system"
          : trigger.type === "user" ? "user" : "schedule"
        }
        eventType={trigger.event ?? trigger.event_type}
        onClose={() => setShowCaseSelector(false)}
        onStart={(testCase, payload) => runSkill(testCase, payload)}
      />
    </div>
  );
}

function TopBar({
  slug, title, mode, runState, dirty, onTitleChange, onSave, onPublish, onRun, onReset, onDelete,
}: {
  slug: string;
  title: string;
  mode: "author" | "run";
  runState: "idle" | "running" | "done";
  dirty: boolean;
  onTitleChange: (v: string) => void;
  onSave: () => void;
  onPublish: () => void;
  onRun: () => void;
  onReset: () => void;
  onDelete: () => void;
}) {
  return (
    <div style={{
      position: "sticky", top: 0, zIndex: 20,
      background: "var(--bg)",
      borderBottom: "1px solid var(--line)",
      padding: "10px 28px",
      display: "flex", alignItems: "center", gap: 16,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "var(--ink-3)" }}>
        <Link href="/skills" style={{ cursor: "pointer" }}>Skills Library</Link>
        <span style={{ color: "var(--ink-4)" }}>/</span>
        {mode === "author"
          ? <input value={title} onChange={(e) => onTitleChange(e.target.value)}
              style={{ border: "none", background: "transparent", color: "var(--ink)", fontWeight: 500, outline: "none", fontFamily: "inherit", fontSize: 12.5, minWidth: 240 }}/>
          : <span style={{ color: "var(--ink)", fontWeight: 500 }}>{title}</span>}
      </div>

      <div style={{ flex: 1 }} />

      <div style={{
        display: "flex", padding: 2, borderRadius: 8,
        background: "var(--surface-2)", border: "1px solid var(--line)",
      }}>
        <Link href={`/skills/${encodeURIComponent(slug)}/edit`} style={{
          padding: "5px 12px", borderRadius: 6, border: "none",
          background: mode === "author" ? "var(--surface)" : "transparent",
          color: mode === "author" ? "var(--ink)" : "var(--ink-3)",
          fontSize: 12, fontWeight: 500, cursor: "pointer",
          boxShadow: mode === "author" ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
          textDecoration: "none",
        }}>Author</Link>
        <Link href={`/skills/${encodeURIComponent(slug)}`} style={{
          padding: "5px 12px", borderRadius: 6, border: "none",
          background: mode === "run" ? "var(--surface)" : "transparent",
          color: mode === "run" ? "var(--ink)" : "var(--ink-3)",
          fontSize: 12, fontWeight: 500, cursor: "pointer",
          boxShadow: mode === "run" ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
          textDecoration: "none",
        }}>Execute</Link>
      </div>

      <div style={{ width: 1, height: 20, background: "var(--line)" }}/>

      {/* Phase 11 v9 — toolbar buttons identical across Author + Execute
          (per user feedback: 兩個 mode 的功能應該一致). Execute mode previously
          hid Save / Activate / ⋯ which forced operators to switch tabs to
          deactivate or delete. */}
      <Btn kind="ghost" onClick={onSave} disabled={!dirty}>{dirty ? "Save Draft" : "Saved"}</Btn>
      <Btn kind="secondary" onClick={onPublish}>
        Activate Trigger
      </Btn>
      {runState === "idle" || runState === "done" ? (
        <Btn kind="primary" icon={<Icon.Play/>} onClick={onRun}>
          {runState === "done" ? "Re-run Skill" : (mode === "author" ? "Test Skill" : "Run Skill")}
        </Btn>
      ) : (
        <Btn kind="secondary" icon={<Icon.Loop/>} onClick={onReset}>Stop</Btn>
      )}

      <StepActionMenu items={[
        { label: "Delete this skill", icon: <Icon.X/>, danger: true,
          onClick: onDelete },
      ]}/>
    </div>
  );
}

/** Phase 11 v8 — overview chips + arrows showing the playbook flow:
 *  TRIGGER → ALARM GATE (if any) → CHECKLIST → OUTCOME (advisory only).
 *  Pure-presentational, derives from existing trigger/confirm/steps state. */
function FlowDiagram({
  triggerLabel, hasAlarmGate, alarmGateSteps, checklistSteps,
}: {
  triggerLabel: string;
  hasAlarmGate: boolean;
  alarmGateSteps: number;
  checklistSteps: number;
}) {
  const Chip = ({ kind, label, mono = false }: { kind: "trigger" | "gate" | "list" | "outcome"; label: React.ReactNode; mono?: boolean }) => {
    const dot = {
      trigger: "var(--fail)",
      gate:    "var(--ai)",
      list:    "var(--warn)",
      outcome: "var(--ai)",
    }[kind];
    const small = {
      trigger: "TRIGGER",
      gate:    `ALARM GATE · ${alarmGateSteps} STEP${alarmGateSteps === 1 ? "" : "S"}`,
      list:    "CHECKLIST",
      outcome: "OUTCOME",
    }[kind];
    return (
      <div style={{
        display: "inline-flex", flexDirection: "column", gap: 4,
        padding: "8px 14px", borderRadius: 8,
        background: "var(--surface)", border: "1px solid var(--line)",
        minWidth: 130,
      }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 6, height: 6, borderRadius: 999, background: dot }}/>
          <span className="mono" style={{ fontSize: 9.5, color: "var(--ink-3)", letterSpacing: "0.06em" }}>
            {small}
          </span>
        </span>
        <span className={mono ? "mono" : undefined} style={{
          fontSize: mono ? 12 : 12.5, color: "var(--ink)", fontWeight: 500,
        }}>{label}</span>
      </div>
    );
  };
  const Arrow = ({ note }: { note?: string }) => (
    <span style={{
      display: "inline-flex", flexDirection: "column", alignItems: "center", gap: 2,
      color: "var(--ink-3)", fontSize: 16, padding: "0 4px",
    }}>
      {note && <span className="mono" style={{ fontSize: 9.5, lineHeight: 1.2 }}>{note}</span>}
      <span style={{ fontSize: 18, lineHeight: 1 }}>→</span>
    </span>
  );
  return (
    <div style={{
      marginTop: 18, padding: "14px 16px",
      background: "var(--surface-2)", border: "1px solid var(--line)",
      borderRadius: 10,
      display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap",
    }}>
      <Chip kind="trigger" label={triggerLabel || "—"} mono/>
      <Arrow/>
      {hasAlarmGate ? (
        <>
          <Chip kind="gate" label="進一步確認 · 達標才告警"/>
          <Arrow note="if all pass → alarm"/>
        </>
      ) : null}
      <Chip kind="list" label={`診斷 · ${checklistSteps} step${checklistSteps === 1 ? "" : "s"}`}/>
      <Arrow/>
      <Chip kind="outcome" label="advisory only"/>
    </div>
  );
}

function PlaybookHeader({
  skill, title, trigger, setTrigger, mode, hasConfirm, stepCount,
}: {
  skill: SkillDetail;
  title: string;
  trigger: TC;
  setTrigger: (t: TC) => void;
  mode: "author" | "run";
  hasConfirm: boolean;
  stepCount: number;
}) {
  return (
    <div style={{ padding: "44px 0 28px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)", letterSpacing: "0.06em" }}>
          SKILL · {(skill.stage || "").toUpperCase()} · ADVISORY
        </span>
        <Badge kind="muted" dim>v{skill.version} · {skill.status === "stable" ? "active" : skill.status}</Badge>
        {skill.domain && <Badge kind="muted" dim>Domain · {skill.domain}</Badge>}
      </div>

      <h1 style={{
        margin: 0, fontSize: 32, fontWeight: 600, letterSpacing: "-0.015em",
        color: "var(--ink)", lineHeight: 1.15,
      }}>
        {title}
      </h1>

      <div style={{
        display: "flex", alignItems: "center", gap: 18, marginTop: 16,
        fontSize: 12.5, color: "var(--ink-2)",
      }}>
        {skill.certified_by && <Badge kind="pass" icon={<Icon.Check/>}>Certified by {skill.certified_by}</Badge>}
        {skill.certified_by && <span style={{ color: "var(--ink-4)" }}>·</span>}
        <span style={{ color: "var(--ink-3)" }}>Updated <span className="mono">{skill.updated_at ? new Date(skill.updated_at).toLocaleDateString() : "—"}</span></span>
      </div>

      <TriggerConfigEditor trigger={trigger} setTrigger={setTrigger} mode={mode}/>

      {/* Phase 11 v8 — flow overview chips so reader sees TRIGGER → ALARM
          GATE → CHECKLIST → OUTCOME at a glance, instead of having to
          scroll through three sections to figure out the playbook shape. */}
      <FlowDiagram
        triggerLabel={
          trigger.type === "event" || trigger.type === "system"
            ? (trigger.event ?? trigger.event_type ?? "(none)")
            : trigger.type === "user" ? (trigger.name ?? "user-triggered")
            : (trigger.schedule?.mode === "daily"
              ? `daily ${trigger.schedule.time ?? "08:00"}`
              : trigger.schedule?.mode === "hourly"
                ? `every ${trigger.schedule.every ?? 4}h`
                : trigger.cron ?? "schedule")
        }
        hasAlarmGate={hasConfirm}
        alarmGateSteps={hasConfirm ? 1 : 0}
        checklistSteps={stepCount}
      />

      {skill.description && (
        <p style={{
          marginTop: 22, marginBottom: 0,
          fontSize: 14.5, lineHeight: 1.65, color: "var(--ink-2)",
          textWrap: "pretty", maxWidth: 720,
        }}>
          {skill.description}
        </p>
      )}
    </div>
  );
}

/** Phase 11 v5 — trailing per-step action menu. Shows a ⋯ button by default;
 *  on click reveals a small absolute-positioned dropdown. Used in author mode
 *  so each step row can be a single prose line + this discreet menu. */
function StepActionMenu({ items }: {
  items: Array<{ label: string; icon?: React.ReactNode; onClick: () => void; danger?: boolean }>;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        type="button"
        aria-label="step actions"
        onClick={() => setOpen(!open)}
        style={{
          all: "unset", cursor: "pointer",
          width: 26, height: 26, borderRadius: 5,
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          color: open ? "var(--ink)" : "var(--ink-3)",
          background: open ? "var(--surface-2)" : "transparent",
        }}>
        <Icon.MoreH/>
      </button>
      {open && (
        <div style={{
          position: "absolute", top: "100%", right: 0, marginTop: 4,
          minWidth: 200, padding: 4,
          background: "var(--surface)", border: "1px solid var(--line-strong)",
          borderRadius: 8, boxShadow: "0 6px 24px rgba(0,0,0,0.08)",
          zIndex: 20,
        }}>
          {items.map((it, i) => (
            <button key={i}
              onClick={() => { setOpen(false); it.onClick(); }}
              style={{
                all: "unset", cursor: "pointer",
                display: "flex", alignItems: "center", gap: 9,
                padding: "7px 10px", borderRadius: 5,
                fontSize: 12.5,
                color: it.danger ? "var(--fail)" : "var(--ink)",
                width: "calc(100% - 0px)", boxSizing: "border-box",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--surface-2)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
              {it.icon && <span style={{ width: 14, display: "inline-flex" }}>{it.icon}</span>}
              <span>{it.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Phase 11 v8 — small "✨ pipeline ready" badge so author/operator sees
 *  at-a-glance that a step is wired (matches new mock).  Only shown when
 *  pipeline_id is bound. */
function PipelineReadyBadge() {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 999,
      background: "var(--ai-bg)", color: "var(--ai)",
      fontSize: 11, fontWeight: 500, whiteSpace: "nowrap",
    }}>
      <Icon.Spark/> pipeline ready
    </span>
  );
}

/** Phase 11 v8 — render a step's suggested_actions inline beneath the step
 *  prose (Author: subtle "└ 若符合 · …" lines; Execute: HALT-style callout
 *  for confidence=high, plain row otherwise). Replaces the previous design
 *  which hid actions behind ⋯ menu count. detail-first: title is optional
 *  (legacy data has it, new entries can leave blank). */
function InlineActions({
  actions, mode,
}: {
  actions: SuggestedAction[];
  mode: "author" | "run";
}) {
  if (!actions || actions.length === 0) return null;
  if (mode === "author") {
    return (
      <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
        {actions.map((a) => (
          <div key={a.id} style={{
            fontSize: 12.5, color: "var(--ink-3)", lineHeight: 1.5,
            paddingLeft: 4,
          }}>
            <span style={{ color: "var(--ink-4)", marginRight: 6 }}>└ 若符合 ·</span>
            <span style={{ color: "var(--ink-2)" }}>{a.detail || a.title || "(empty action)"}</span>
            {a.detail && a.title && (
              <span style={{ color: "var(--ink-4)", marginLeft: 6, fontSize: 11 }}>· {a.title}</span>
            )}
          </div>
        ))}
      </div>
    );
  }
  // Execute mode — high-confidence actions render as a HALT callout with
  // a red border-left bar (matches new mock); med/low render as a softer row.
  return (
    <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
      {actions.map((a) => {
        const isHalt = a.confidence === "high";
        return (
          <div key={a.id} style={{
            padding: "10px 14px", borderRadius: 8,
            background: isHalt ? "var(--fail-bg)" : "var(--surface-2)",
            borderLeft: isHalt ? "3px solid var(--fail)" : "3px solid var(--line-strong)",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 4 }}>
              {isHalt ? (
                <span className="mono" style={{
                  fontSize: 10, fontWeight: 600,
                  color: "var(--fail)",
                  padding: "2px 8px", borderRadius: 4,
                  background: "var(--surface)", border: "1px solid var(--fail)",
                }}>HALT</span>
              ) : (
                <span className="mono" style={{
                  fontSize: 10, color: "var(--ink-3)",
                  padding: "2px 8px", borderRadius: 4,
                  background: "var(--surface)", border: "1px solid var(--line)",
                }}>{(a.confidence || "med").toUpperCase()}</span>
              )}
              <span style={{ fontSize: 11, color: isHalt ? "var(--fail)" : "var(--ink-3)" }}>
                {isHalt ? "若 fail → 停機 / 禁用" : "若 fail → 建議行動"}
              </span>
            </div>
            <div style={{ fontSize: 13.5, color: "var(--ink)", fontWeight: 500, lineHeight: 1.5 }}>
              {a.detail || a.title || "(empty action)"}
            </div>
            {a.rationale && (
              <div className="mono" style={{ marginTop: 4, fontSize: 11, color: "var(--ink-3)", lineHeight: 1.5 }}>
                ✨ why · {a.rationale}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function StepBlock({
  step, index, mode, expanded, onToggle, runStatus, runResult,
  onTextChange, onActionsChange, onRemove,
  onOpenInBuilder, onInspect,
  onActionsExpand, actionsExpanded,
}: {
  step: SkillStep;
  index: number;
  mode: "author" | "run";
  expanded: boolean;
  onToggle: () => void;
  runStatus?: "queued" | "running" | "done";
  runResult?: StepRunResult;
  onTextChange: (t: string) => void;
  onActionsChange: (a: SuggestedAction[]) => void;
  onRemove: () => void;
  onOpenInBuilder: (instruction: string) => void;
  onInspect: (pipelineId: number) => void;
  onActionsExpand: () => void;
  actionsExpanded: boolean;
}) {
  const isRunning = runStatus === "running";
  const isDone = runStatus === "done";

  const runPill = (() => {
    if (mode !== "run") return null;
    if (isRunning) return <Badge kind="muted" icon={<span className="skill-spinner"/>}>Running…</Badge>;
    if (!isDone) return <Badge kind="muted" dim>Pending</Badge>;
    if (runResult?.status === "pass") return <Badge kind="pass" icon={<Icon.Check/>}>Pass</Badge>;
    if (runResult?.status === "fail") return <Badge kind="fail" icon={<Icon.X/>}>Fail</Badge>;
    return null;
  })();

  const hasPipeline = step.pipeline_id != null;
  const actionsCount = step.suggested_actions?.length ?? 0;

  // Phase 11 v5 — Author mode = slim doc-style row. Trailing area is either:
  //   ● [✨ Build →] CTA when there's no pipeline yet, OR
  //   ● ⋯ menu (Refine / Inspect / Suggested actions / Remove) when bound.
  // No pipeline canvas mini, no "AI summary" string, no "Awaiting your
  // confirmation" badge — those are Execute-only. Sign-off is implicit:
  // binding from Builder = confirmed.
  if (mode === "author") {
    return (
      <div style={{
        position: "relative",
        padding: "16px 0",
        borderTop: index === 0 ? "1px solid var(--line)" : "none",
        borderBottom: "1px solid var(--line)",
      }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
          <div style={{
            flexShrink: 0,
            width: 28, height: 28, borderRadius: 6,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: "var(--surface-2)", color: "var(--ink-2)",
            border: "1px solid var(--line)",
            fontSize: 12, fontWeight: 600, marginTop: 1,
          }} className="mono">
            {String(index + 1).padStart(2, "0")}
          </div>

          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
              <textarea
                value={step.text}
                onChange={(e) => onTextChange(e.target.value)}
                rows={1}
                style={{
                  flex: 1,
                  fontSize: 16, lineHeight: 1.55, color: "var(--ink)",
                  fontWeight: 450, outline: "none", padding: "1px 0",
                  border: "none", background: "transparent", resize: "vertical",
                  fontFamily: "inherit",
                }}
                placeholder="描述這個檢查步驟…"
              />
              {!hasPipeline ? (
                <button
                  onClick={() => onOpenInBuilder(step.text)}
                  style={{
                    flexShrink: 0,
                    display: "inline-flex", alignItems: "center", gap: 5,
                    padding: "5px 11px", borderRadius: 6,
                    background: "var(--ai)", color: "#fff",
                    border: "none", cursor: "pointer",
                    fontSize: 12, fontWeight: 500,
                  }}>
                  <Icon.Spark/> Build →
                </button>
              ) : (
                <>
                  {/* Phase 11 v8 — green chip so author sees at a glance the
                      step has a pipeline bound. Replaces the silent "no
                      indication" state where only the ⋯ menu hinted. */}
                  <PipelineReadyBadge/>
                  <StepActionMenu items={[
                    { label: "Refine in Pipeline Builder", icon: <Icon.Spark/>,
                      onClick: () => onOpenInBuilder(step.text) },
                    { label: "Inspect blocks ↗", icon: <Icon.Pencil/>,
                      onClick: () => { if (step.pipeline_id != null) onInspect(step.pipeline_id); } },
                    { label: actionsExpanded ? "Hide suggested actions editor" : `Edit suggested actions (${actionsCount})`,
                      icon: <Icon.Spark/>, onClick: onActionsExpand },
                    { label: "Remove step", icon: <Icon.X/>, danger: true, onClick: onRemove },
                  ]}/>
                </>
              )}
            </div>

            {/* Phase 11 v8 — actions render inline so reader doesn't need to
                open ⋯ menu to discover them. ⋯ menu still has the editor. */}
            <InlineActions actions={step.suggested_actions ?? []} mode="author"/>

            {actionsExpanded && (
              <SuggestedActionsEditor
                actions={step.suggested_actions ?? []}
                onChange={onActionsChange}
                onClose={onActionsExpand}
              />
            )}
          </div>
        </div>
      </div>
    );
  }

  // Execute mode — keep rich rendering with pipeline canvas mini, AI summary,
  // run pill, expand toggle. Sign-off button is gone (bind = confirmed).
  return (
    <div style={{
      position: "relative",
      padding: "18px 0",
      borderTop: index === 0 ? "1px solid var(--line)" : "none",
      borderBottom: "1px solid var(--line)",
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
        <div style={{
          flexShrink: 0,
          width: 28, height: 28, borderRadius: 6,
          display: "flex", alignItems: "center", justifyContent: "center",
          background: expanded ? "var(--accent)" : "var(--surface-2)",
          color: expanded ? "var(--bg)" : "var(--ink-2)",
          border: `1px solid ${expanded ? "var(--accent)" : "var(--line)"}`,
          fontSize: 12, fontWeight: 600, marginTop: 1,
          transition: "all 120ms",
        }} className="mono">
          {String(index + 1).padStart(2, "0")}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, lineHeight: 1.55, color: "var(--ink)", fontWeight: 450 }}>
            {step.text}
          </div>

          <div style={{
            marginTop: 10,
            display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
          }}>
            <Badge kind="ai" icon={<Icon.Spark/>}>{step.badge?.label || "AI Generated"}</Badge>
            <span className="mono" style={{
              fontSize: 11, color: "var(--ink-3)",
              display: "inline-flex", alignItems: "center", gap: 5,
            }}>
              <Icon.Spark/>
              {step.ai_summary || "(no summary)"}
            </span>

            <span style={{ flex: 1 }}/>

            {runPill}

            <button onClick={onToggle} style={{
              border: "1px solid var(--sys-line)", background: "var(--surface)",
              padding: "3px 8px", borderRadius: 6, cursor: "pointer",
              fontSize: 11.5, color: "var(--ink-2)",
              display: "inline-flex", alignItems: "center", gap: 4,
            }}>
              <Icon.Spark/>
              <span className="mono" style={{ fontSize: 10.5 }}>
                {expanded ? "Hide" : "View logic"}
              </span>
              <Icon.Chevron/>
            </button>

            {/* Phase 11 v6 — actions are available in BOTH modes (per spec:
                Execute = same actions + extra views). Author hides views;
                here we keep both views (canvas mini below) AND the action
                menu so an operator can still Refine / Inspect / etc. */}
            {hasPipeline && (
              <>
                <PipelineReadyBadge/>
                <StepActionMenu items={[
                  { label: "Refine in Pipeline Builder", icon: <Icon.Spark/>,
                    onClick: () => onOpenInBuilder(step.text) },
                  { label: "Inspect blocks ↗", icon: <Icon.Pencil/>,
                    onClick: () => { if (step.pipeline_id != null) onInspect(step.pipeline_id); } },
                  { label: actionsExpanded ? "Hide suggested actions editor" : `Edit suggested actions (${actionsCount})`,
                    icon: <Icon.Spark/>, onClick: onActionsExpand },
                  { label: "Remove step", icon: <Icon.X/>, danger: true, onClick: onRemove },
                ]}/>
              </>
            )}
            {!hasPipeline && (
              <button
                onClick={() => onOpenInBuilder(step.text)}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 5,
                  padding: "5px 11px", borderRadius: 6,
                  background: "var(--ai)", color: "#fff",
                  border: "none", cursor: "pointer",
                  fontSize: 12, fontWeight: 500,
                }}>
                <Icon.Spark/> Build →
              </button>
            )}
          </div>

          {expanded && (
            <ExpandedPipeline
              step={step}
              isRunning={isRunning}
              onInspect={onInspect}
            />
          )}

          {/* Phase 11 v8 — operator-facing inline action callouts.
              high confidence → HALT red bar; med/low → softer row. */}
          <InlineActions actions={step.suggested_actions ?? []} mode="run"/>

          {/* Phase 11 v6 — Suggested actions editor in Execute mode too
              (operator can record action notes during a run / triage).
              Same toggle as Author's ⋯ menu item. */}
          {actionsExpanded && (
            <SuggestedActionsEditor
              actions={step.suggested_actions ?? []}
              onChange={onActionsChange}
              onClose={onActionsExpand}
            />
          )}

          {isDone && runResult && (
            <RunResultInline result={runResult} step={step}/>
          )}
        </div>
      </div>
    </div>
  );
}

/** Phase 11 v5 — Execute-only, read-only pipeline mini canvas. Author mode
 *  no longer renders this (use ⋯ → Inspect blocks instead). */
function ExpandedPipeline({
  step, isRunning, onInspect,
}: {
  step: SkillStep;
  isRunning: boolean;
  onInspect: (pipelineId: number) => void;
}) {
  void isRunning;
  // Synthesize a simple block diagram from step.pipeline_id metadata.
  const blocks: MiniBlock[] = step.pipeline_id != null ? [
    { id: "src",   kind: "source",    title: "Pipeline #" + step.pipeline_id, params: "(loaded from Builder)" },
    { id: "chk",   kind: "check",     title: "block_step_check",              params: "" },
  ] : [
    { id: "stub",  kind: "transform", title: "(尚未生成 pipeline)", params: "" },
  ];

  return (
    <div style={{
      marginTop: 14,
      background: "var(--sys-bg)",
      border: "1px solid var(--sys-line)", borderRadius: 10,
      overflow: "hidden",
      boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.4)",
    }}>
      <div style={{
        padding: "10px 14px",
        display: "flex", alignItems: "center", gap: 8,
        borderBottom: "1px solid var(--sys-line)",
        background: "var(--surface)",
      }}>
        <Icon.Spark/>
        <span className="mono" style={{ fontSize: 11, color: "var(--ink-2)", fontWeight: 500, letterSpacing: "0.04em", textTransform: "uppercase" }}>
          AI-translated pipeline
        </span>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-3)" }}>
          · {blocks.length} blocks
        </span>
        <span style={{ flex: 1 }}/>
        {step.pipeline_id != null && (
          <button
            type="button"
            onClick={() => { if (step.pipeline_id != null) onInspect(step.pipeline_id); }}
            style={{
              all: "unset", cursor: "pointer",
              fontSize: 11, color: "var(--ai)", textDecoration: "none",
              display: "inline-flex", alignItems: "center", gap: 4,
            }}>
            Inspect ↗
          </button>
        )}
      </div>

      <div style={{ padding: "8px 14px", background: "var(--bg-soft)" }}>
        <PipelineCanvasMini blocks={blocks} dense/>
      </div>
    </div>
  );
}

function SuggestedActionsEditor({
  actions, onChange, onClose,
}: {
  actions: SuggestedAction[];
  onChange: (a: SuggestedAction[]) => void;
  onClose?: () => void;     // Phase 11 v6 — close the editor (× button + ESC)
}) {
  const upd = (i: number, patch: Partial<SuggestedAction>) => {
    onChange(actions.map((a, idx) => idx === i ? { ...a, ...patch } : a));
  };
  const del = (i: number) => onChange(actions.filter((_, idx) => idx !== i));
  const add = () => onChange([
    ...actions,
    { id: "a" + Date.now().toString(36), title: "", detail: "", rationale: "", confidence: "med" },
  ]);

  // ESC closes the editor — fires only when this editor is mounted.
  useEffect(() => {
    if (!onClose) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div style={{ padding: "12px 14px", borderTop: "1px solid var(--line)", background: "var(--surface)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8,
                    fontSize: 10.5, fontWeight: 600, letterSpacing: "0.06em",
                    color: "var(--ink-3)", textTransform: "uppercase" }}>
        <Icon.Spark/> Suggested next actions (when this step fails)
        <span style={{ flex: 1 }}/>
        <span style={{ fontSize: 10, color: "var(--ink-4)", textTransform: "none", fontWeight: 400, letterSpacing: 0 }}>
          ✨ advisory only · 不會自動執行
        </span>
        {onClose && (
          <button
            type="button"
            aria-label="close suggested actions"
            onClick={onClose}
            title="ESC to close"
            style={{
              all: "unset", cursor: "pointer",
              padding: "0 4px", marginLeft: 8,
              fontSize: 14, lineHeight: 1, color: "var(--ink-3)",
              borderRadius: 3,
            }}
          >×</button>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {actions.map((a, i) => (
          <div key={a.id} style={{
            padding: "8px 10px", background: "var(--surface-2)",
            border: "1px solid var(--line)", borderRadius: 6,
            display: "flex", flexDirection: "column", gap: 6,
          }}>
            {/* Phase 11 v8 — DETAIL is now the primary field (shown inline
                on the step row). TITLE is optional; legacy data keeps it
                but new entries can leave blank. confidence drives HALT. */}
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input value={a.detail} onChange={(e) => upd(i, { detail: e.target.value })}
                placeholder="若 step fail 時建議的行動（e.g. 禁用該 chamber · 轉排生產至其他 chamber）"
                style={{ flex: 1, padding: "5px 8px", border: "1px solid var(--line)", borderRadius: 4,
                         fontSize: 12.5, background: "var(--surface)", outline: "none", fontFamily: "inherit" }}/>
              <select value={a.confidence} onChange={(e) => upd(i, { confidence: e.target.value as "high" | "med" | "low" })}
                title="high → HALT 紅色 callout；med/low → 一般灰色"
                style={{ padding: "5px 8px", border: "1px solid var(--line)", borderRadius: 4, fontSize: 11.5, fontFamily: "inherit" }}>
                <option value="high">high (HALT)</option>
                <option value="med">med</option>
                <option value="low">low</option>
              </select>
              <button onClick={() => del(i)} style={{
                border: "1px solid var(--line)", background: "var(--surface)",
                color: "var(--fail)", padding: "4px 8px", borderRadius: 4,
                cursor: "pointer", fontSize: 11,
              }}>delete</button>
            </div>
            <input value={a.title} onChange={(e) => upd(i, { title: e.target.value })}
              placeholder="(可省略) 短標題 — 預設用上方描述當標題"
              style={{ padding: "5px 8px", border: "1px solid var(--line)", borderRadius: 4,
                       fontSize: 11.5, background: "var(--surface)", outline: "none", color: "var(--ink-3)", fontFamily: "inherit" }}/>
            <input value={a.rationale ?? ""} onChange={(e) => upd(i, { rationale: e.target.value })}
              placeholder="✨ Why（e.g. APC recipe 異動時間與 OOC 高度重疊）"
              className="mono"
              style={{ padding: "5px 8px", border: "1px solid var(--line)", borderRadius: 4,
                       fontSize: 11, background: "var(--surface)", outline: "none", color: "var(--ink-3)" }}/>
          </div>
        ))}
      </div>
      <button onClick={add} style={{
        marginTop: 8,
        all: "unset", cursor: "pointer",
        padding: "6px 11px", borderRadius: 6,
        background: "var(--surface-2)", color: "var(--ink-2)",
        border: "1px dashed var(--line-strong)",
        fontSize: 12, display: "inline-flex", alignItems: "center", gap: 6,
      }}>
        <Icon.Plus/> Add suggested action
      </button>
    </div>
  );
}

function RunResultInline({
  result, step,
}: {
  result: StepRunResult;
  step: SkillStep;
}) {
  const isFail = result.status === "fail";
  return (
    <div style={{
      marginTop: 12,
      padding: "12px 14px",
      borderRadius: 8,
      background: isFail ? "var(--fail-bg)" : "var(--pass-bg)",
      border: `1px solid ${isFail ? "var(--fail)" : "var(--pass)"}`,
      borderLeftWidth: 3,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ color: isFail ? "var(--fail)" : "var(--pass)", display: "inline-flex" }}>
          {isFail ? <Icon.X/> : <Icon.Check/>}
        </span>
        <strong style={{ fontSize: 13, color: "var(--ink)" }}>{result.value}</strong>
        <span style={{ fontSize: 12, color: "var(--ink-2)" }}>· {result.note}</span>
      </div>
      {isFail && step.suggested_actions && step.suggested_actions.length > 0 && (
        <SuggestionPanel actions={step.suggested_actions}/>
      )}
    </div>
  );
}

function SuggestionPanel({ actions }: { actions: SuggestedAction[] }) {
  return (
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid color-mix(in oklch, var(--fail), transparent 80%)" }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 10.5, fontWeight: 600, letterSpacing: "0.06em",
        color: "var(--ink-3)", textTransform: "uppercase", marginBottom: 10,
      }}>
        <Icon.Spark/> Suggested next actions
        <span style={{ flex: 1 }}/>
        <span style={{ fontSize: 10, color: "var(--ink-4)", textTransform: "none", fontWeight: 400, letterSpacing: 0 }}>
          ✨ advisory only · not executed automatically
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {actions.map((a) => (
          <div key={a.id} style={{
            display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 12, alignItems: "flex-start",
            padding: "10px 12px",
            background: "var(--surface)",
            border: "1px solid var(--line)",
            borderLeft: `2px solid ${a.confidence === "high" ? "var(--ai)" : "var(--line-strong)"}`,
            borderRadius: 6,
          }}>
            <span style={{
              width: 20, height: 20, borderRadius: 5, marginTop: 1,
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              background: a.confidence === "high" ? "var(--ai-bg)" : "var(--surface-2)",
              color: a.confidence === "high" ? "var(--ai)" : "var(--ink-3)",
            }}><Icon.Spark/></span>
            <div>
              <div style={{ fontSize: 12.5, color: "var(--ink)", fontWeight: 500 }}>{a.detail || a.title}</div>
              {a.detail && a.title && (
                <div style={{ fontSize: 11, color: "var(--ink-4)", marginTop: 2 }}>{a.title}</div>
              )}
              {a.rationale && (
                <div className="mono" style={{ fontSize: 10.5, color: "var(--ink-4)", marginTop: 6, lineHeight: 1.5 }}>
                  ✨ why · {a.rationale}
                </div>
              )}
            </div>
            <span className="mono" style={{
              fontSize: 10, padding: "2px 7px", borderRadius: 999,
              background: "var(--surface-2)", color: "var(--ink-3)",
              border: "1px solid var(--line)", whiteSpace: "nowrap",
            }}>
              {a.confidence}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AddStep({ onAdd }: { onAdd: (text: string) => Promise<void> }) {
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);

  const submit = async () => {
    if (!draft.trim()) return;
    setThinking(true);
    try {
      await onAdd(draft.trim());
      setDraft("");
    } finally {
      setThinking(false);
    }
  };

  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div style={{ padding: "20px 0 64px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 0" }}>
        {/* Phase 11 v2 — was a decorative div; now a real button that
            focuses the input. User feedback 2026-05-09: 「我就是不能點 +」 */}
        <button
          type="button"
          aria-label="新增檢查步驟"
          onClick={() => inputRef.current?.focus()}
          style={{
            flexShrink: 0,
            width: 28, height: 28, borderRadius: 6,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: "var(--surface)", border: "1px dashed var(--line-strong)",
            color: "var(--ink-3)", cursor: "pointer", padding: 0,
          }}>
          <Icon.Plus/>
        </button>
        <input
          ref={inputRef}
          value={draft}
          disabled={thinking}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void submit(); }}
          placeholder="新增一個檢查步驟，用自然語言描述即可…"
          style={{
            flex: 1, fontSize: 15, padding: "6px 0",
            border: "none", background: "transparent",
            color: "var(--ink)", outline: "none",
            fontFamily: "inherit",
          }}
        />
        {thinking ? (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--ai)" }}>
            <span className="skill-spinner"/>
            Opening Builder…
          </span>
        ) : (
          <Btn kind="ghost" onClick={() => void submit()} disabled={!draft.trim()} icon={<Icon.Spark/>}>
            Build →
          </Btn>
        )}
      </div>
      <div style={{ paddingLeft: 42, fontSize: 11.5, color: "var(--ink-4)" }}>
        Tip · 寫一句檢查邏輯，按 Build 會開 Pipeline Builder 帶你完成。
      </div>
    </div>
  );
}

function RunTimeline({
  steps, runState, activeStepId, runStatuses, runResults,
  confirmCheck, confirmRunStatus, confirmRunResult,
}: {
  steps: SkillStep[];
  runState: "idle" | "running" | "done";
  activeStepId: string | null;
  runStatuses: Record<string, "queued" | "running" | "done">;
  runResults: Record<string, StepRunResult>;
  confirmCheck: ConfirmCheck | null;
  confirmRunStatus: "queued" | "running" | "done" | null;
  confirmRunResult: StepRunResult | null;
}) {
  void activeStepId;
  // Phase 11 v7 — render the C1 confirm row first when a confirm step exists,
  // so user 看得到 confirm 階段的進度（之前 confirm 期間 UI 完全沒變化）.
  const confirmDot = confirmRunStatus === "done"
    ? (confirmRunResult?.status === "fail" ? "var(--fail)" : "var(--pass)")
    : confirmRunStatus === "running" ? "var(--ai)"
    : "var(--line-strong)";
  return (
    <aside style={{
      position: "sticky", top: 56,
      width: 280, flexShrink: 0,
      padding: 18,
      maxHeight: "calc(100vh - 70px)",
      overflowY: "auto",
    }}>
      <div style={{
        background: "var(--surface)",
        border: "1px solid var(--line)", borderRadius: 10,
        padding: "14px 14px 10px",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <span style={{ width: 6, height: 6, borderRadius: 999, background: runState === "done" ? "var(--pass)" : "var(--ai)" }}/>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>
            {runState === "done" ? "Execution complete" : "Executing skill"}
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          {confirmCheck && (
            <div style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "8px 0" }}>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                <span style={{
                  width: 9, height: 9, borderRadius: 999, background: confirmDot,
                  boxShadow: confirmRunStatus === "running" ? "0 0 0 4px var(--ai-bg)" : "none",
                  transition: "all 200ms",
                }}/>
                {steps.length > 0 && (
                  <div style={{ width: 1, flex: 1, minHeight: 18, background: "var(--line)", marginTop: 2 }}/>
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, color: "var(--ai)", fontWeight: 600, lineHeight: 1.35 }}>
                  C1 · Confirm
                </div>
                <div style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 2, lineHeight: 1.4 }}>
                  {confirmRunStatus == null && "Queued"}
                  {confirmRunStatus === "queued" && "Queued"}
                  {confirmRunStatus === "running" && "Running…"}
                  {confirmRunStatus === "done" && confirmRunResult?.status === "pass" && (confirmRunResult.value || "Pass · 繼續 checklist")}
                  {confirmRunStatus === "done" && confirmRunResult?.status === "fail" && (
                    <span style={{ color: "var(--fail)" }}>
                      {confirmRunResult.value || "Fail"} · checklist 已跳過
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}
          {steps.map((s, i) => {
            const st = runStatuses[s.id] || "queued";
            const result = runResults[s.id];
            const dotColor = st === "done"
              ? (result?.status === "fail" ? "var(--fail)" : "var(--pass)")
              : st === "running" ? "var(--ai)"
              : "var(--line-strong)";
            return (
              <div key={s.id} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "8px 0" }}>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                  <span style={{
                    width: 9, height: 9, borderRadius: 999, background: dotColor,
                    boxShadow: st === "running" ? "0 0 0 4px var(--ai-bg)" : "none",
                    transition: "all 200ms",
                  }}/>
                  {i < steps.length - 1 && (
                    <div style={{ width: 1, flex: 1, minHeight: 18, background: "var(--line)", marginTop: 2 }}/>
                  )}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: "var(--ink-2)", fontWeight: 500, lineHeight: 1.35 }}>
                    Step {i + 1}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 2, lineHeight: 1.4 }}>
                    {st === "queued" && "Queued"}
                    {st === "running" && "Running…"}
                    {st === "done" && result?.status === "pass" && (result.value || "Pass")}
                    {st === "done" && result?.status === "fail" && <span style={{ color: "var(--fail)" }}>{result.value}</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
}

/* ── Phase 11 v9 — Summary Report (alarm-center pattern) ───────────────
 *  Replaces the v8 thin "FINDINGS" list. Now renders:
 *    1. VerdictHeader   — pass/fail banner (alarm raised vs no alarm)
 *    2. SynthesisStrip  — derived two-line summary (gate + checklist)
 *    3. GateResultCard  — C1 detail with pipeline result table (if any)
 *    4. Per-step card   — pipeline result + InlineActions
 *  All data sourced from existing SSE payload (status/value/note/threshold/
 *  operator/duration_ms) plus step.suggested_actions. No backend change. */

/** Phase 11 v10 — render one dataframe preview as a compact table.
 *  Mirrors alarm-center DataViewTable styling with skill-specific header
 *  (node_id · block · port · row count). Cap visual to 8 cols × 20 rows. */
function SkillDataViewTable({ dv }: { dv: SkillDataView }) {
  const cols = dv.columns.slice(0, 8);
  const rows = dv.rows.slice(0, 20);
  if (cols.length === 0 && rows.length === 0) return null;
  const fmt = (v: unknown): string => {
    if (v === null || v === undefined) return "—";
    if (typeof v === "object") return JSON.stringify(v);
    if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3);
    return String(v);
  };
  return (
    <div style={{
      marginTop: 8, border: "1px solid var(--line)", borderRadius: 6,
      background: "var(--surface)", overflow: "hidden",
    }}>
      <div style={{
        padding: "6px 10px", background: "var(--bg-soft)",
        borderBottom: "1px solid var(--line)",
        display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
        fontSize: 11,
      }}>
        <span style={{ color: "var(--ink-2)", fontWeight: 600 }}>📋 {dv.block || dv.node_id}</span>
        <span className="mono" style={{ color: "var(--ink-3)" }}>·{dv.port}</span>
        <span style={{ flex: 1 }}/>
        <span className="mono" style={{ color: "var(--ink-3)" }}>
          {rows.length}{dv.total > rows.length ? ` / ${dv.total}` : ""} rows
        </span>
      </div>
      <div style={{ overflowX: "auto", maxHeight: 320 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, fontFamily: "ui-monospace, monospace" }}>
          <thead>
            <tr style={{ background: "var(--bg-soft)" }}>
              {cols.map((c) => (
                <th key={c} style={{
                  padding: "5px 8px", textAlign: "left", color: "var(--ink-3)",
                  borderBottom: "1px solid var(--line)", fontWeight: 600,
                  whiteSpace: "nowrap", position: "sticky", top: 0, background: "var(--bg-soft)",
                }}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} style={{ borderBottom: "1px solid var(--line)" }}>
                {cols.map((c) => {
                  const v = row[c];
                  // Highlight OOC-ish cells (matches alarm-center convention).
                  const highlight =
                    (c === "spc_status" && v === "OOC") ||
                    (c.endsWith("_is_ooc") && v === true) ||
                    (c === "triggered_row" && v === true);
                  return (
                    <td key={c} style={{
                      padding: "5px 8px", whiteSpace: "nowrap",
                      color: highlight ? "var(--fail)" : "var(--ink)",
                      background: highlight ? "var(--fail-bg)" : "transparent",
                      fontWeight: highlight ? 600 : 400,
                    }}>{fmt(v)}</td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Phase 11 v10 — section header + list of data view tables.
 *  Returns null when there's nothing to show, to keep cards compact. */
function PipelineDataSection({ views }: { views: SkillDataView[] | undefined }) {
  if (!views || views.length === 0) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <div className="mono" style={{
        fontSize: 9.5, letterSpacing: "0.06em", color: "var(--ink-3)", marginBottom: 6,
      }}>
        📊 PIPELINE DATA · {views.length} VIEW{views.length === 1 ? "" : "S"}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {views.map((dv, i) => <SkillDataViewTable key={i} dv={dv}/>)}
      </div>
    </div>
  );
}

function PipelineResultTable({ result }: { result: StepRunResult }) {
  const rows: [string, React.ReactNode][] = [];
  if (result.value !== "" && result.value != null) rows.push(["value", result.value]);
  if (result.operator) rows.push(["operator", result.operator]);
  if (result.threshold != null && result.threshold !== "") rows.push(["threshold", String(result.threshold)]);
  if (result.note) rows.push(["note", result.note]);
  if (result.duration_ms != null) rows.push(["elapsed", `${result.duration_ms} ms`]);
  if (rows.length === 0) {
    return (
      <div style={{ padding: "8px 12px", color: "var(--ink-3)", fontSize: 11.5, fontStyle: "italic" }}>
        (pipeline 沒回傳明細)
      </div>
    );
  }
  return (
    <div className="mono" style={{
      marginTop: 10,
      padding: "8px 12px", borderRadius: 6,
      background: "var(--bg-soft)", border: "1px solid var(--line)",
      fontSize: 11.5, color: "var(--ink-2)",
      display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 12px",
    }}>
      {rows.map(([k, v]) => (
        <React.Fragment key={k}>
          <span style={{ color: "var(--ink-3)" }}>{k}:</span>
          <span style={{ wordBreak: "break-word" }}>{v}</span>
        </React.Fragment>
      ))}
    </div>
  );
}

function VerdictHeader({
  verdict, testCase, onClose,
}: {
  verdict: { kind: "alarm" | "no_alarm" | "gate_blocked" | "error"; title: string; subtitle: string };
  testCase: TestCase | null;
  onClose: () => void;
}) {
  const isFail = verdict.kind === "alarm" || verdict.kind === "gate_blocked" || verdict.kind === "error";
  return (
    <div style={{
      padding: "18px 20px", borderBottom: "1px solid var(--line)",
      display: "flex", alignItems: "flex-start", gap: 14,
    }}>
      <span style={{
        width: 36, height: 36, borderRadius: 8, flexShrink: 0,
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        background: isFail ? "var(--fail-bg)" : "var(--pass-bg)",
        color: isFail ? "var(--fail)" : "var(--pass)",
      }}>
        {isFail ? <Icon.Bolt/> : <Icon.Check/>}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)" }}>
          DIAGNOSTIC REPORT · {testCase ? "DRY-RUN" : "LIVE"}
        </div>
        <h2 style={{
          margin: "4px 0 0", fontSize: 18, fontWeight: 600,
          letterSpacing: "-0.01em",
          color: isFail ? "var(--fail)" : "var(--pass)",
        }}>
          {verdict.title}
        </h2>
        <div style={{ marginTop: 6, fontSize: 12.5, color: "var(--ink-2)" }}>
          {verdict.subtitle}
        </div>
        {testCase && (
          <div style={{ marginTop: 6, fontSize: 11.5, color: "var(--ink-3)" }}>
            Test case · <span style={{ color: "var(--ink-2)" }}>{testCase.title}</span>
          </div>
        )}
      </div>
      <button onClick={onClose} title="Dismiss report" style={{
        all: "unset", cursor: "pointer", padding: 6, borderRadius: 4,
        color: "var(--ink-3)",
      }}><Icon.X/></button>
    </div>
  );
}

function SynthesisStrip({
  hasGate, gateResult, passCount, failCount, totalSteps, gateBlocked,
}: {
  hasGate: boolean;
  gateResult: StepRunResult | null;
  passCount: number;
  failCount: number;
  totalSteps: number;
  gateBlocked: boolean;
}) {
  const lines: React.ReactNode[] = [];
  if (hasGate) {
    if (gateResult?.status === "pass") {
      lines.push(<span key="g">⚡ Gate C1 <strong>PASS</strong> · 已啟動 checklist</span>);
    } else if (gateResult?.status === "fail") {
      lines.push(<span key="g">⛔ Gate C1 <strong>FAIL</strong> · {gateBlocked ? "checklist 已跳過" : "降級提示，仍跑 checklist"}</span>);
    } else {
      lines.push(<span key="g">⏳ Gate C1 未完成</span>);
    }
  }
  if (totalSteps > 0 && !gateBlocked) {
    lines.push(<span key="c">⚙ Checklist · <strong style={{ color: "var(--pass)" }}>{passCount} pass</strong> / <strong style={{ color: failCount > 0 ? "var(--fail)" : "var(--ink-3)" }}>{failCount} fail</strong></span>);
  }
  if (lines.length === 0) return null;
  return (
    <div style={{
      padding: "12px 20px", background: "var(--bg-soft)",
      borderBottom: "1px solid var(--line)",
      display: "flex", flexDirection: "column", gap: 4,
      fontSize: 12.5, color: "var(--ink-2)",
    }}>
      {lines}
    </div>
  );
}

function GateResultCard({
  confirmCheck, gateResult, gateBlocked, onInspect,
}: {
  confirmCheck: ConfirmCheck;
  gateResult: StepRunResult | null;
  gateBlocked: boolean;
  onInspect: (id: number) => void;
}) {
  const status = gateResult?.status;
  const isFail = status === "fail";
  const accent = isFail ? "var(--fail)" : status === "pass" ? "var(--pass)" : "var(--line-strong)";
  const accentBg = isFail ? "var(--fail-bg)" : status === "pass" ? "var(--pass-bg)" : "var(--surface-2)";
  return (
    <section style={{ marginTop: 12, padding: "0 20px" }}>
      <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ai)", marginBottom: 8 }}>
        ALARM GATE · C1
      </div>
      <div style={{
        padding: "14px 16px", borderRadius: 10,
        background: "var(--surface)",
        border: `1px solid ${accent}`, borderLeft: `4px solid ${accent}`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span className="mono" style={{
            fontSize: 10, fontWeight: 600,
            color: accent, padding: "2px 8px", borderRadius: 4,
            background: accentBg, border: `1px solid ${accent}`,
          }}>
            {status === "pass" ? "🟢 PASS · 條件達成" : status === "fail" ? "🔴 FAIL · 條件未達成" : "—"}
          </span>
          {gateBlocked && (
            <span className="mono" style={{
              fontSize: 10, color: "var(--fail)", padding: "2px 8px",
              background: "var(--fail-bg)", border: "1px solid var(--fail)",
              borderRadius: 4, fontWeight: 600,
            }}>checklist skipped</span>
          )}
          <span style={{ flex: 1 }}/>
          {confirmCheck.pipeline_id != null && (
            <button
              type="button"
              onClick={() => { if (confirmCheck.pipeline_id != null) onInspect(confirmCheck.pipeline_id); }}
              style={{
                all: "unset", cursor: "pointer",
                fontSize: 11, color: "var(--ai)",
              }}>Inspect ↗</button>
          )}
        </div>
        <div style={{ marginTop: 8, fontSize: 14, color: "var(--ink)", fontWeight: 500, lineHeight: 1.5 }}>
          {confirmCheck.description}
        </div>
        {gateResult && <PipelineResultTable result={gateResult}/>}
        <PipelineDataSection views={gateResult?.data_views}/>
      </div>
    </section>
  );
}

function StepResultCard({
  step, index, result, onInspect,
}: {
  step: SkillStep;
  index: number;
  result: StepRunResult | undefined;
  onInspect: (id: number) => void;
}) {
  const status = result?.status;
  const isFail = status === "fail";
  const isPass = status === "pass";
  const [open, setOpen] = useState(isFail);   // pass steps collapsed by default
  const accent = isFail ? "var(--fail)" : isPass ? "var(--pass)" : "var(--line-strong)";
  const accentBg = isFail ? "var(--fail-bg)" : isPass ? "var(--pass-bg)" : "var(--surface-2)";
  const stepNum = String(index + 1).padStart(2, "0");
  const actions = step.suggested_actions ?? [];

  return (
    <div style={{
      padding: "12px 14px", borderRadius: 10,
      background: "var(--surface)",
      border: `1px solid ${accent}`, borderLeft: `4px solid ${accent}`,
    }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          all: "unset", cursor: "pointer", width: "100%",
          display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
        }}>
        <span className="mono" style={{
          fontSize: 10, fontWeight: 600,
          color: accent, padding: "2px 8px", borderRadius: 4,
          background: accentBg, border: `1px solid ${accent}`,
        }}>
          STEP {stepNum} · {status === "pass" ? "PASS" : status === "fail" ? "FAIL" : "—"}
        </span>
        <span style={{ flex: 1, fontSize: 13.5, color: "var(--ink)", fontWeight: 500, lineHeight: 1.45 }}>
          {step.text}
        </span>
        {step.pipeline_id != null && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); if (step.pipeline_id != null) onInspect(step.pipeline_id); }}
            style={{
              all: "unset", cursor: "pointer",
              fontSize: 11, color: "var(--ai)", marginRight: 8,
            }}>Inspect ↗</button>
        )}
        <span style={{
          fontSize: 11, color: "var(--ink-3)", display: "inline-flex", alignItems: "center", gap: 2,
        }}>
          {open ? "Hide" : "View"} <Icon.Chevron/>
        </span>
      </button>
      {open && (
        <>
          {result && <PipelineResultTable result={result}/>}
          {/* Phase 11 v10 — show the actual dataframes the pipeline produced
              (not just the boolean check verdict). Operator needs the data
              to understand WHY the check pass/failed. */}
          <PipelineDataSection views={result?.data_views}/>
          {/* Suggested actions: HALT callout for high, soft row for med/low */}
          <InlineActions actions={actions} mode="run"/>
          {actions.length === 0 && isFail && (
            <div style={{
              marginTop: 10, padding: "8px 12px", borderRadius: 6,
              background: "var(--surface-2)", color: "var(--ink-3)",
              fontSize: 11.5, fontStyle: "italic",
            }}>
              這個 step 沒設定 suggested action — 在 Author mode 加上「若 fail 該怎麼做」會更實用。
            </div>
          )}
        </>
      )}
    </div>
  );
}

function SummaryReport({
  steps, results, testCase, onRerun, onClose,
  confirmCheck, confirmRunResult, onInspect,
}: {
  steps: SkillStep[];
  results: Record<string, StepRunResult>;
  testCase: TestCase | null;
  onRerun: () => void;
  onClose: () => void;
  confirmCheck: ConfirmCheck | null;
  confirmRunResult: StepRunResult | null;
  onInspect: (id: number) => void;
}) {
  const passed = steps.filter((s) => results[s.id]?.status === "pass");
  const failed = steps.filter((s) => results[s.id]?.status === "fail");

  const hasGate = !!confirmCheck;
  // Java's SkillRunner default: must_pass=true unless explicitly false
  const mustPass = confirmCheck ? !((confirmCheck as { must_pass?: boolean }).must_pass === false) : false;
  const gateBlocked = hasGate && mustPass && confirmRunResult?.status === "fail";

  const verdict = (() => {
    if (gateBlocked) {
      return {
        kind: "gate_blocked" as const,
        title: "ALARM GATE FAILED · checklist 已跳過",
        subtitle: "C1 條件未達成 — 不視為真正的告警情境，未執行後續診斷。",
      };
    }
    if (failed.length === 0 && (!hasGate || confirmRunResult?.status === "pass")) {
      return {
        kind: "no_alarm" as const,
        title: `NO ALARM · all ${steps.length} check${steps.length === 1 ? "" : "s"} passed`,
        subtitle: hasGate
          ? "Gate 通過 + 所有 checklist 都 pass — 沒有需要工程師處理的事項。"
          : "所有 checklist 都 pass — 沒有需要工程師處理的事項。",
      };
    }
    return {
      kind: "alarm" as const,
      title: `ALARM RAISED · ${failed.length} finding${failed.length === 1 ? "" : "s"} flagged`,
      subtitle: `${passed.length} of ${steps.length} check${steps.length === 1 ? "" : "s"} passed · 請依下方建議行動處理。`,
    };
  })();

  return (
    <section style={{
      margin: "6px 0 32px", borderRadius: 12,
      background: "var(--surface)",
      border: "1px solid var(--line-strong)",
      overflow: "hidden",
      boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
    }}>
      <VerdictHeader verdict={verdict} testCase={testCase} onClose={onClose}/>

      <SynthesisStrip
        hasGate={hasGate}
        gateResult={confirmRunResult}
        passCount={passed.length}
        failCount={failed.length}
        totalSteps={steps.length}
        gateBlocked={gateBlocked}
      />

      {hasGate && (
        <GateResultCard
          confirmCheck={confirmCheck}
          gateResult={confirmRunResult}
          gateBlocked={gateBlocked}
          onInspect={onInspect}
        />
      )}

      {!gateBlocked && steps.length > 0 && (
        <section style={{ marginTop: 16, padding: "0 20px" }}>
          <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)", marginBottom: 8 }}>
            CHECKLIST · {steps.length} STEP{steps.length === 1 ? "" : "S"}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {steps.map((s, i) => (
              <StepResultCard
                key={s.id}
                step={s}
                index={i}
                result={results[s.id]}
                onInspect={onInspect}
              />
            ))}
          </div>
        </section>
      )}

      <div style={{
        margin: "20px 20px 16px", paddingTop: 14, borderTop: "1px solid var(--line)",
        display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
      }}>
        <Btn kind="ghost">Export PDF report</Btn>
        {testCase && <Btn kind="ghost">Add to regression set</Btn>}
        <span style={{ flex: 1 }}/>
        <Btn kind="primary" icon={<Icon.Loop/>} onClick={onRerun}>Run with another case</Btn>
      </div>
    </section>
  );
}

/* ── Phase 11 v2: CONFIRM section (gating step) ────────────────────── */

function ConfirmSection({
  slug, mode, confirmCheck, onSet, onReload, onInspect,
}: {
  slug: string;
  mode: "author" | "run";
  confirmCheck: ConfirmCheck | null;
  onSet: (cc: ConfirmCheck | null) => void;
  onReload: () => void;
  onInspect: (pipelineId: number) => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Phase 11 v4: Translate now opens Pipeline Builder (new tab) instead
  // of running silent AI translation. The Builder hosts Glass Box + manual
  // editing; on Confirm it POSTs back to /bind-pipeline which updates the
  // skill's confirm_check. We refresh on window focus to pick up the bind.
  const openInBuilder = async (text: string, slot: string = "confirm") => {
    if (!text.trim() && slot === "confirm") return;
    setBusy(true); setError(null);
    try {
      const r = await fetch(
        `/api/skill-documents/${encodeURIComponent(slug)}/builder-url?`
        + `slot=${encodeURIComponent(slot)}`
        + `&instruction=${encodeURIComponent(text)}`,
      );
      const j = await r.json();
      if (!r.ok) throw new Error(j?.error?.message ?? `HTTP ${r.status}`);
      const url = j.data?.builder_url ?? j.builder_url;
      if (!url) throw new Error("builder_url missing in response");
      window.open(url, "_blank", "noopener");
      // Drop draft text — banner in Builder will carry it.
      setDraft("");
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };

  // When user comes back from Builder tab, refresh the skill detail to
  // pick up the new confirm_check binding.
  useEffect(() => {
    const onFocus = () => onReload();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [onReload]);

  const removeStep = async () => {
    setBusy(true); setError(null);
    try {
      const r = await fetch(`/api/skill-documents/${encodeURIComponent(slug)}/confirm-check`, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      onSet(null);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ marginTop: 30 }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "10px 0 18px", marginTop: 6,
      }}>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ai)", letterSpacing: "0.08em" }}>
          ALARM GATE · {confirmCheck ? "1 STEP" : "OPTIONAL"} · 進一步確認是否要告警
        </span>
        <span style={{ flex: 1, height: 1, background: "var(--line)" }}/>
        <span style={{ fontSize: 11, color: "var(--ink-3)" }}>全部成立 → 發告警 + 走 checklist</span>
      </div>

      {confirmCheck ? (
        <div style={{
          display: "grid", gridTemplateColumns: "auto 1fr auto",
          gap: 14, alignItems: "start",
          padding: "14px 16px", borderRadius: 8,
          background: "var(--surface)",
          // Phase 11 v6 — visually flag stale state when pipeline_id is null
          // (description survives but underlying pipeline was deleted). The
          // C1 card shows orange-ish so user knows it isn't a complete slot
          // and the action becomes "Build" not "Refine".
          border: confirmCheck.pipeline_id == null
            ? "1px solid #FDE68A"
            : "1px solid var(--ai-bg)",
          borderLeft: confirmCheck.pipeline_id == null
            ? "3px solid #D97706"
            : "3px solid var(--ai)",
        }}>
          <span className="mono" style={{
            fontSize: 11,
            color: confirmCheck.pipeline_id == null ? "#92400E" : "var(--ai)",
            background: confirmCheck.pipeline_id == null ? "#FEF3C7" : "var(--ai-bg)",
            padding: "3px 8px", borderRadius: 4,
            whiteSpace: "nowrap",
          }}>C1</span>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <div style={{ fontSize: 14, color: "var(--ink)", fontWeight: 500, flex: 1, minWidth: 0 }}>
                {confirmCheck.description}
              </div>
              {confirmCheck.pipeline_id != null && <PipelineReadyBadge/>}
            </div>
            {/* Phase 11 v6 — stale flag: pipeline_id null but description
                exists. Tells user the slot needs rebuild before run/test. */}
            {confirmCheck.pipeline_id == null && (
              <div style={{
                marginTop: 6, fontSize: 11.5, color: "#92400E",
                display: "inline-flex", alignItems: "center", gap: 6,
              }}>
                ⚠ underlying pipeline was deleted — click <strong>Build</strong> to rebuild from this description
              </div>
            )}
            {/* AI summary, Inspect link, Pending badges are Execute-only.
                Author mode hides these to keep the prose row clean; actions
                live in the trailing ⋯ menu. */}
            {mode === "run" && confirmCheck.ai_summary && confirmCheck.pipeline_id != null && (
              <div style={{
                marginTop: 6, fontSize: 12, color: "var(--ink-3)",
                display: "inline-flex", alignItems: "center", gap: 6,
              }}>
                <Badge kind="ai">✨ AI parsed</Badge>
                <span>{confirmCheck.ai_summary}</span>
              </div>
            )}
            {mode === "run" && confirmCheck.pipeline_id != null && (
              <div style={{ marginTop: 8 }}>
                <button
                  type="button"
                  onClick={() => { if (confirmCheck.pipeline_id != null) onInspect(confirmCheck.pipeline_id); }}
                  style={{
                    all: "unset", cursor: "pointer",
                    fontSize: 11.5, color: "var(--ai)", textDecoration: "none",
                    display: "inline-flex", alignItems: "center", gap: 4,
                  }}
                >
                  Inspect pipeline ↗
                </button>
              </div>
            )}
            {error && <div style={{ marginTop: 6, fontSize: 11, color: "var(--fail)" }}>⚠ {error}</div>}
          </div>
          {/* Phase 11 v6 — actions row: stale → big yellow Build CTA;
              healthy → ⋯ menu (Refine/Inspect/Remove). */}
          {confirmCheck.pipeline_id == null ? (
            <button
              onClick={() => void openInBuilder(confirmCheck.description, "confirm")}
              disabled={busy}
              style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "5px 11px", borderRadius: 6,
                background: "#D97706", color: "#fff",
                border: "none", cursor: busy ? "wait" : "pointer",
                fontSize: 12, fontWeight: 500,
                whiteSpace: "nowrap",
              }}>
              <Icon.Spark/> Build →
            </button>
          ) : (
            <StepActionMenu items={[
              { label: "Refine in Pipeline Builder", icon: <Icon.Spark/>,
                onClick: () => void openInBuilder(confirmCheck.description, "confirm") },
              { label: "Inspect blocks ↗", icon: <Icon.Pencil/>,
                onClick: () => { if (confirmCheck.pipeline_id != null) onInspect(confirmCheck.pipeline_id); } },
              { label: "Remove confirmation step", icon: <Icon.X/>, danger: true,
                onClick: () => void removeStep() },
            ]}/>
          )}
        </div>
      ) : mode === "author" ? (
        // unreachable — handled by upper branch
        <></>
      ) : null}
      {/* Phase 11 v8 — quick "remove" link below the C1 card so the action
          isn't buried in the ⋯ menu (per new design mock). Author mode only. */}
      {confirmCheck && mode === "author" && (
        <button
          type="button"
          onClick={() => void removeStep()}
          disabled={busy}
          style={{
            all: "unset", cursor: busy ? "wait" : "pointer",
            marginTop: 8, marginLeft: 8,
            fontSize: 11.5, color: "var(--ink-3)",
            fontStyle: "italic",
          }}
        >— remove last confirmation step</button>
      )}
      {/* Original empty-author input (kept verbatim) */}
      {!confirmCheck && mode === "author" ? (
        <div style={{
          display: "flex", alignItems: "center", gap: 14,
          padding: "14px 0", borderTop: "1px dashed var(--line)",
          borderBottom: "1px dashed var(--line)",
        }}>
          <button
            type="button"
            aria-label="設定 CONFIRM 步驟"
            onClick={() => inputRef.current?.focus()}
            style={{
              flexShrink: 0, width: 28, height: 28, borderRadius: 6,
              display: "flex", alignItems: "center", justifyContent: "center",
              background: "var(--surface)", border: "1px dashed var(--ai)",
              color: "var(--ai)", cursor: "pointer", padding: 0,
            }}>
            <Icon.Plus/>
          </button>
          <input
            ref={inputRef}
            value={draft}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void openInBuilder(draft); }}
            placeholder="（選填）先確認一個條件，例如「最近 1h OOC ≥ 3 才繼續」"
            style={{
              flex: 1, fontSize: 14, padding: "6px 0",
              border: "none", background: "transparent",
              color: "var(--ink)", outline: "none", fontFamily: "inherit",
            }}
          />
          <Btn kind="ghost" disabled={!draft.trim() || busy} icon={<Icon.Spark/>}
            onClick={() => void openInBuilder(draft)}>
            {busy ? "Opening Builder…" : "Build →"}
          </Btn>
        </div>
      ) : null}
      {error && !confirmCheck && (
        <div style={{ fontSize: 11, color: "var(--fail)", paddingLeft: 42, marginTop: 6 }}>⚠ {error}</div>
      )}
    </div>
  );
}
