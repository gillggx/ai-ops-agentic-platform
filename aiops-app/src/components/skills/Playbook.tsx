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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  const [runResults, setRunResults] = useState<Record<string, { status: "pass" | "fail"; value: string; note: string }>>({});
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
    if (!confirm("Publish 後 trigger 會生效並開始持續執行。確認 publish？")) return;
    await onSave();
    const res = await fetch(`/api/skill-documents/${encodeURIComponent(slug)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "stable" }),
    });
    if (res.ok) router.refresh();
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
        // Fallback simulation: mark each step running → done sequentially
        await simulateRun();
        return;
      }
      // SSE consumer
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
          if (evt === "step_start") {
            const sid = data.step_id as string;
            setRunActiveStep(sid);
            setRunStatuses((prev) => ({ ...prev, [sid]: "running" }));
          } else if (evt === "step_done") {
            const sid = data.step_id as string;
            const status = (data.status as "pass" | "fail") || "pass";
            const value = (data.value as string) || "";
            const note = (data.note as string) || "";
            setRunStatuses((prev) => ({ ...prev, [sid]: "done" }));
            setRunResults((prev) => ({ ...prev, [sid]: { status, value, note } }));
          } else if (evt === "done") {
            setRunState("done");
            setRunActiveStep(null);
            setShowSummary(true);
          }
        }
      }
    } catch (e) {
      console.warn("run failed, falling back to client simulation:", e);
      await simulateRun();
    }
  };

  const simulateRun = async () => {
    // Backend-less fallback so author can preview UX without SkillRunner
    for (const s of steps) {
      setRunActiveStep(s.id);
      setRunStatuses((prev) => ({ ...prev, [s.id]: "running" }));
      await new Promise((r) => setTimeout(r, 500));
      const status = Math.random() > 0.5 ? "pass" : "fail";
      setRunResults((prev) => ({
        ...prev,
        [s.id]: {
          status,
          value: status === "pass" ? "All checks ok" : "Threshold exceeded",
          note: "(simulated)",
        },
      }));
      setRunStatuses((prev) => ({ ...prev, [s.id]: "done" }));
    }
    setRunActiveStep(null);
    setRunState("done");
    setShowSummary(true);
  };

  const resetRun = () => {
    setRunState("idle");
    setRunStatuses({});
    setRunActiveStep(null);
    setRunResults({});
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
      />

      <div style={{
        display: "flex", justifyContent: "center",
        gap: 0, maxWidth: 1400, margin: "0 auto",
      }}>
        <main style={{ flex: 1, maxWidth: 860, padding: "0 28px 80px" }}>
          <PlaybookHeader skill={skill} title={title} trigger={trigger} setTrigger={(t) => { setTrigger(t); markDirty(); }} mode={mode}/>

          {showSummary && runState === "done" && (
            <SummaryReport
              steps={steps}
              results={runResults}
              testCase={selectedCase}
              onRerun={() => { setShowSummary(false); setShowCaseSelector(true); }}
              onClose={() => setShowSummary(false)}
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

          {mode === "author" && <AddStep onAdd={addStep}/>}
        </main>

        {runState !== "idle" && (
          <RunTimeline
            steps={steps}
            runState={runState}
            activeStepId={runActiveStep}
            runStatuses={runStatuses}
            runResults={runResults}
          />
        )}
      </div>

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
  slug, title, mode, runState, dirty, onTitleChange, onSave, onPublish, onRun, onReset,
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

      {mode === "author" && (
        <>
          <Btn kind="ghost" onClick={onSave} disabled={!dirty}>{dirty ? "Save Draft" : "Saved"}</Btn>
          <Btn kind="secondary" onClick={onPublish}>Publish</Btn>
        </>
      )}
      {runState === "idle" || runState === "done" ? (
        <Btn kind="primary" icon={<Icon.Play/>} onClick={onRun}>
          {runState === "done" ? "Re-run Skill" : (mode === "author" ? "Test Skill" : "Run Skill")}
        </Btn>
      ) : (
        <Btn kind="secondary" icon={<Icon.Loop/>} onClick={onReset}>Stop</Btn>
      )}
    </div>
  );
}

function PlaybookHeader({
  skill, title, trigger, setTrigger, mode,
}: {
  skill: SkillDetail;
  title: string;
  trigger: TC;
  setTrigger: (t: TC) => void;
  mode: "author" | "run";
}) {
  return (
    <div style={{ padding: "44px 0 28px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)", letterSpacing: "0.06em" }}>
          SKILL · {(skill.stage || "").toUpperCase()} · ADVISORY
        </span>
        <Badge kind="muted" dim>v{skill.version} · {skill.status}</Badge>
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

function StepBlock({
  step, index, mode, expanded, onToggle, runStatus, runResult,
  onTextChange, onActionsChange, onRemove,
  onOpenInBuilder,
  onActionsExpand, actionsExpanded,
}: {
  step: SkillStep;
  index: number;
  mode: "author" | "run";
  expanded: boolean;
  onToggle: () => void;
  runStatus?: "queued" | "running" | "done";
  runResult?: { status: "pass" | "fail"; value: string; note: string };
  onTextChange: (t: string) => void;
  onActionsChange: (a: SuggestedAction[]) => void;
  onRemove: () => void;
  onOpenInBuilder: (instruction: string) => void;
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
                <StepActionMenu items={[
                  { label: "Refine in Pipeline Builder", icon: <Icon.Spark/>,
                    onClick: () => onOpenInBuilder(step.text) },
                  { label: "Inspect blocks ↗", icon: <Icon.Pencil/>,
                    onClick: () => window.open(`/admin/pipeline-builder/${step.pipeline_id}`, "_blank", "noopener") },
                  { label: actionsExpanded ? "Hide suggested actions" : `Suggested actions (${actionsCount})`,
                    icon: <Icon.Spark/>, onClick: onActionsExpand },
                  { label: "Remove step", icon: <Icon.X/>, danger: true, onClick: onRemove },
                ]}/>
              )}
            </div>

            {actionsExpanded && (
              <SuggestedActionsEditor
                actions={step.suggested_actions ?? []}
                onChange={onActionsChange}
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
          </div>

          {expanded && (
            <ExpandedPipeline
              step={step}
              isRunning={isRunning}
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
  step, isRunning,
}: {
  step: SkillStep;
  isRunning: boolean;
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
          <Link href={`/admin/pipeline-builder/${step.pipeline_id}`} target="_blank" style={{
            fontSize: 11, color: "var(--ai)", textDecoration: "none",
            display: "inline-flex", alignItems: "center", gap: 4,
          }}>
            Inspect ↗
          </Link>
        )}
      </div>

      <div style={{ padding: "8px 14px", background: "var(--bg-soft)" }}>
        <PipelineCanvasMini blocks={blocks} dense/>
      </div>
    </div>
  );
}

function SuggestedActionsEditor({
  actions, onChange,
}: { actions: SuggestedAction[]; onChange: (a: SuggestedAction[]) => void }) {
  const upd = (i: number, patch: Partial<SuggestedAction>) => {
    onChange(actions.map((a, idx) => idx === i ? { ...a, ...patch } : a));
  };
  const del = (i: number) => onChange(actions.filter((_, idx) => idx !== i));
  const add = () => onChange([
    ...actions,
    { id: "a" + Date.now().toString(36), title: "", detail: "", rationale: "", confidence: "med" },
  ]);

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
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {actions.map((a, i) => (
          <div key={a.id} style={{
            padding: "8px 10px", background: "var(--surface-2)",
            border: "1px solid var(--line)", borderRadius: 6,
            display: "flex", flexDirection: "column", gap: 6,
          }}>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input value={a.title} onChange={(e) => upd(i, { title: e.target.value })}
                placeholder="建議行動的標題（e.g. 回退 APC recipe）"
                style={{ flex: 1, padding: "5px 8px", border: "1px solid var(--line)", borderRadius: 4,
                         fontSize: 12.5, background: "var(--surface)", outline: "none", fontFamily: "inherit" }}/>
              <select value={a.confidence} onChange={(e) => upd(i, { confidence: e.target.value as "high" | "med" | "low" })}
                style={{ padding: "5px 8px", border: "1px solid var(--line)", borderRadius: 4, fontSize: 11.5, fontFamily: "inherit" }}>
                <option value="high">high</option>
                <option value="med">med</option>
                <option value="low">low</option>
              </select>
              <button onClick={() => del(i)} style={{
                border: "1px solid var(--line)", background: "var(--surface)",
                color: "var(--fail)", padding: "4px 8px", borderRadius: 4,
                cursor: "pointer", fontSize: 11,
              }}>delete</button>
            </div>
            <input value={a.detail} onChange={(e) => upd(i, { detail: e.target.value })}
              placeholder="詳細描述（e.g. rev. 18 為最後一個 stable revision）"
              style={{ padding: "5px 8px", border: "1px solid var(--line)", borderRadius: 4,
                       fontSize: 12, background: "var(--surface)", outline: "none", fontFamily: "inherit" }}/>
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
  result: { status: "pass" | "fail"; value: string; note: string };
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
              <div style={{ fontSize: 12.5, color: "var(--ink)", fontWeight: 500 }}>{a.title}</div>
              <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 3, lineHeight: 1.55 }}>{a.detail}</div>
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
}: {
  steps: SkillStep[];
  runState: "idle" | "running" | "done";
  activeStepId: string | null;
  runStatuses: Record<string, "queued" | "running" | "done">;
  runResults: Record<string, { status: "pass" | "fail"; value: string; note: string }>;
}) {
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

function SummaryReport({
  steps, results, testCase, onRerun, onClose,
}: {
  steps: SkillStep[];
  results: Record<string, { status: "pass" | "fail"; value: string; note: string }>;
  testCase: TestCase | null;
  onRerun: () => void;
  onClose: () => void;
}) {
  const failed = steps.filter((s) => results[s.id]?.status === "fail");
  const passed = steps.filter((s) => results[s.id]?.status === "pass");
  const hasFail = failed.length > 0;

  return (
    <section style={{
      margin: "6px 0 32px", borderRadius: 12,
      background: "var(--surface)",
      border: "1px solid var(--line-strong)",
      overflow: "hidden",
      boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
    }}>
      <div style={{ padding: "18px 20px", borderBottom: "1px solid var(--line)", display: "flex", alignItems: "flex-start", gap: 14 }}>
        <span style={{
          width: 36, height: 36, borderRadius: 8, flexShrink: 0,
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          background: hasFail ? "var(--fail-bg)" : "var(--pass-bg)",
          color: hasFail ? "var(--fail)" : "var(--pass)",
        }}>
          {hasFail ? <Icon.Bolt/> : <Icon.Check/>}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)" }}>
            DIAGNOSTIC SUMMARY · {testCase ? "DRY-RUN" : "LIVE"}
          </div>
          <h2 style={{ margin: "4px 0 0", fontSize: 18, fontWeight: 600, letterSpacing: "-0.01em", color: "var(--ink)" }}>
            {hasFail
              ? `${failed.length} finding${failed.length > 1 ? "s" : ""} flagged · ${passed.length} of ${steps.length} checks passed`
              : `All ${steps.length} checks passed · no issue detected`}
          </h2>
          {testCase && (
            <div style={{ marginTop: 8, fontSize: 11.5, color: "var(--ink-3)" }}>
              Test case · <span style={{ color: "var(--ink-2)" }}>{testCase.title}</span>
            </div>
          )}
        </div>
        <button onClick={onClose} title="Dismiss summary" style={{
          all: "unset", cursor: "pointer", padding: 6, borderRadius: 4,
          color: "var(--ink-3)",
        }}><Icon.X/></button>
      </div>

      <div style={{ padding: "16px 20px" }}>
        {hasFail && (
          <>
            <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)", marginBottom: 10 }}>FINDINGS</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 18 }}>
              {failed.map((s) => {
                const idx = steps.findIndex((x) => x.id === s.id);
                const r = results[s.id];
                return (
                  <div key={s.id} style={{
                    padding: "12px 14px",
                    border: "1px solid var(--fail)",
                    background: "var(--fail-bg)",
                    borderRadius: 8,
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                      <span className="mono" style={{ fontSize: 10, color: "var(--fail)", padding: "1px 7px", border: "1px solid var(--fail)", borderRadius: 4, fontWeight: 600 }}>
                        STEP {String(idx + 1).padStart(2, "0")}
                      </span>
                      <strong style={{ fontSize: 13.5, color: "var(--ink)" }}>{r?.value}</strong>
                    </div>
                    <div style={{ marginTop: 7, fontSize: 12.5, color: "var(--ink-2)", lineHeight: 1.55 }}>
                      <span style={{ color: "var(--ink-3)" }}>Step ·</span> {s.text}
                    </div>
                    {r?.note && (
                      <div className="mono" style={{ marginTop: 4, fontSize: 11.5, color: "var(--ink-2)" }}>
                        <span style={{ color: "var(--ink-3)" }}>detail ·</span> {r.note}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            {/* Suggested actions aggregated from failed steps */}
            {failed.flatMap((s) => s.suggested_actions ?? []).length > 0 && (
              <>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
                  <span className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)" }}>SUGGESTED NEXT ACTIONS</span>
                  <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>· ✨ advisory · 不會自動執行</span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 18 }}>
                  {failed.flatMap((s) => s.suggested_actions ?? []).map((a) => (
                    <div key={a.id} style={{
                      display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 14, alignItems: "flex-start",
                      padding: "12px 14px",
                      background: "var(--sys-bg)",
                      border: "1px solid var(--sys-line)",
                      borderRadius: 8,
                    }}>
                      <span style={{
                        width: 22, height: 22, borderRadius: 6, marginTop: 1,
                        display: "inline-flex", alignItems: "center", justifyContent: "center",
                        background: a.confidence === "high" ? "var(--ai-bg)" : "var(--surface)",
                        color: a.confidence === "high" ? "var(--ai)" : "var(--ink-3)",
                        border: "1px solid var(--sys-line)",
                      }}><Icon.Spark/></span>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--ink)" }}>{a.title}</div>
                        <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 3, lineHeight: 1.55 }}>{a.detail}</div>
                        {a.rationale && (
                          <div className="mono" style={{ fontSize: 10.5, color: "var(--ink-4)", marginTop: 6, lineHeight: 1.5 }}>
                            ✨ why · {a.rationale}
                          </div>
                        )}
                      </div>
                      <span className="mono" style={{
                        fontSize: 10, padding: "2px 8px", borderRadius: 999,
                        background: "var(--surface)", border: "1px solid var(--sys-line)", color: "var(--ink-3)",
                        whiteSpace: "nowrap",
                      }}>
                        {a.confidence}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
        <div style={{
          paddingTop: 14, borderTop: "1px solid var(--line)",
          display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
        }}>
          <Btn kind="ghost">Export PDF report</Btn>
          {testCase && <Btn kind="ghost">Add to regression set</Btn>}
          <span style={{ flex: 1 }}/>
          <Btn kind="primary" icon={<Icon.Loop/>} onClick={onRerun}>Run with another case</Btn>
        </div>
      </div>
    </section>
  );
}

/* ── Phase 11 v2: CONFIRM section (gating step) ────────────────────── */

function ConfirmSection({
  slug, mode, confirmCheck, onSet, onReload,
}: {
  slug: string;
  mode: "author" | "run";
  confirmCheck: ConfirmCheck | null;
  onSet: (cc: ConfirmCheck | null) => void;
  onReload: () => void;
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
          CONFIRMATION · {confirmCheck ? "1 STEP" : "OPTIONAL"} · IS IT REAL?
        </span>
        <span style={{ flex: 1, height: 1, background: "var(--line)" }}/>
        <span style={{ fontSize: 11, color: "var(--ink-3)" }}>only proceed if pass</span>
      </div>

      {confirmCheck ? (
        <div style={{
          display: "grid", gridTemplateColumns: "auto 1fr auto",
          gap: 14, alignItems: "start",
          padding: "14px 16px", borderRadius: 8,
          background: "var(--surface)",
          border: "1px solid var(--ai-bg)",
          borderLeft: "3px solid var(--ai)",
        }}>
          <span className="mono" style={{
            fontSize: 11, color: "var(--ai)",
            background: "var(--ai-bg)", padding: "3px 8px", borderRadius: 4,
            whiteSpace: "nowrap",
          }}>C1</span>
          <div>
            <div style={{ fontSize: 14, color: "var(--ink)", fontWeight: 500 }}>
              {confirmCheck.description}
            </div>
            {/* Phase 11 v5 — AI summary, Inspect link, Pending badges
                are Execute-only. Author mode hides these to keep the prose
                row clean; actions live in the trailing ⋯ menu. */}
            {mode === "run" && confirmCheck.ai_summary && (
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
                <a
                  href={`/admin/pipeline-builder/${confirmCheck.pipeline_id}`}
                  target="_blank"
                  rel="noopener"
                  style={{
                    fontSize: 11.5, color: "var(--ai)", textDecoration: "none",
                    display: "inline-flex", alignItems: "center", gap: 4,
                  }}
                >
                  Inspect pipeline ↗
                </a>
              </div>
            )}
            {error && <div style={{ marginTop: 6, fontSize: 11, color: "var(--fail)" }}>⚠ {error}</div>}
          </div>
          {mode === "author" && (
            <StepActionMenu items={[
              { label: "Refine in Pipeline Builder", icon: <Icon.Spark/>,
                onClick: () => void openInBuilder(confirmCheck.description, "confirm") },
              ...(confirmCheck.pipeline_id != null
                ? [{ label: "Inspect blocks ↗", icon: <Icon.Pencil/>,
                    onClick: () => window.open(`/admin/pipeline-builder/${confirmCheck.pipeline_id}`, "_blank", "noopener") }]
                : []),
              { label: "Remove confirmation step", icon: <Icon.X/>, danger: true,
                onClick: () => void removeStep() },
            ]}/>
          )}
        </div>
      ) : mode === "author" ? (
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
