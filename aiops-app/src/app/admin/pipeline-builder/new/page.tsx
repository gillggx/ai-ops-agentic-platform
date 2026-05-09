"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { PipelineInput, PipelineJSON } from "@/lib/pipeline-builder/types";
import AutoPatrolTriggerForm, {
  emptyTrigger,
  validateTrigger,
  type AutoPatrolTriggerValue,
  type EventType,
} from "@/components/pipeline-builder/AutoPatrolTriggerForm";
import AutoCheckTriggerForm, {
  emptyAutoCheckTrigger,
  validateAutoCheckTrigger,
  type AutoCheckTriggerValue,
} from "@/components/pipeline-builder/AutoCheckTriggerForm";
import WizardInputsStep, { validateInputs } from "@/components/pipeline-builder/WizardInputsStep";
import {
  getInputSuggestions,
  suggestionToInput,
  type WizardTriggerMode,
} from "@/components/pipeline-builder/wizard-input-suggestions";
import AutoPatrolScopePicker, {
  defaultPickedScope,
  requiredInputsForScope,
  validatePickedScope,
  type PickedScope,
} from "@/components/pipeline-builder/AutoPatrolScopePicker";
import SurfaceTour from "@/components/tour/SurfaceTour";
import { PIPELINE_BUILDER_STEPS } from "@/components/tour/steps/pipeline-builder";
import SkillEmbedBanner, {
  bootstrapSkillCtxFromUrl,
  readSkillCtx,
  seedInputsFromCtx,
} from "@/components/pipeline-builder/SkillEmbedBanner";

// React Flow can't SSR
const BuilderLayout = dynamic(() => import("@/components/pipeline-builder/BuilderLayout"), {
  ssr: false,
});

type Kind = "auto_patrol" | "auto_check" | "skill";
type Step = 1 | 2 | 3;

/** Payload handed to BuilderLayout. Auto-created on first save.
 *
 *  For auto_patrol the wizard also captures `scope` — only relevant for
 *  schedule/once triggers (event triggers ignore scope and resolve target
 *  from the alarm payload at runtime). The scope is stuffed into the
 *  AutoPatrolEntity.target_scope JSON column on first save. */
export type PendingTrigger =
  | { kind: "auto_patrol"; config: AutoPatrolTriggerValue; scope: PickedScope }
  | { kind: "auto_check"; config: AutoCheckTriggerValue }
  | null;

export default function NewPipelinePage() {
  const [kind, setKind] = useState<Kind | null>(null);
  // 3-step wizard: kind → trigger (skill skips) → inputs → Builder
  const [step, setStep] = useState<Step>(1);
  const [pendingTrigger, setPendingTrigger] = useState<PendingTrigger>(null);
  const [pendingInputs, setPendingInputs] = useState<PipelineInput[]>([]);

  // Phase 5: ephemeral pipeline hydrated from Copilot's Edit-in-Builder button
  const [ephemeralPipeline, setEphemeralPipeline] = useState<PipelineJSON | null>(null);
  // v1.5: when ?from=agent + ephemeral pipeline → skip the wizard entirely
  // and drop the user straight onto the canvas with the agent-built pipeline
  // already loaded.
  const [skipWizard, setSkipWizard] = useState(false);
  const [checkedSession, setCheckedSession] = useState(false);

  useEffect(() => {
    let hydrated: PipelineJSON | null = null;
    try {
      const raw = sessionStorage.getItem("pb:ephemeral_pipeline");
      if (raw) {
        const payload = JSON.parse(raw) as { pipeline_json?: PipelineJSON; ts?: number };
        if (payload?.pipeline_json) {
          hydrated = payload.pipeline_json;
          setEphemeralPipeline(payload.pipeline_json);
        }
        sessionStorage.removeItem("pb:ephemeral_pipeline");
      }
    } catch {
      // ignore malformed payload
    }

    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const q = params.get("kind");
      // PbPipelineCard.handleEditInBuilder uses ?from=chat; AIAgentPanel
      // uses ?from=agent. Both mean "Glass Box already built it, drop user
      // onto canvas, skip wizard."
      const fromParam = params.get("from");
      const fromAgent = fromParam === "agent" || fromParam === "chat";
      // Phase 11 v4: ?embed=skill = launched from a Skill page. Bootstrap
      // sessionStorage ctx + seed inputs from event/target → skip wizard.
      const skillCtx = bootstrapSkillCtxFromUrl();

      // Heuristic: pipeline_json shape decides the kind. block_alert ⇒ auto_patrol;
      // block_chart-only ⇒ skill; mixed ⇒ default skill.
      const inferKind = (pj: PipelineJSON): Kind => {
        const hasAlert = pj.nodes.some((n) => n.block_id === "block_alert");
        const hasChart = pj.nodes.some((n) => n.block_id === "block_chart");
        if (hasAlert) return "auto_patrol";
        if (hasChart) return "skill";
        return "skill";
      };

      if (skillCtx) {
        // Skill embed: kind="skill" (no alert; ends in step_check), seed inputs
        // from the trigger event payload or schedule target.
        setKind("skill");
        const seeded = seedInputsFromCtx(skillCtx).map((s) => ({
          name: s.name, type: s.type, required: s.required,
          description: s.description ?? "",
        })) as PipelineInput[];
        setPendingInputs(seeded);
        setSkipWizard(true);
      } else if (q === "auto_patrol" || q === "auto_check" || q === "skill") {
        setKind(q);
        setStep(q === "skill" ? 3 : 2);
      } else if (fromAgent && hydrated) {
        // Agent already built the pipeline — bypass kind gate, trigger config,
        // and inputs declaration. User can still adjust inside builder.
        setKind(inferKind(hydrated));
        setSkipWizard(true);
      } else if (hydrated) {
        // Old behavior (chat copy-paste from another flow) — default to skill
        // and run the wizard so the user can review.
        setKind("skill");
      }
    }
    setCheckedSession(true);
  }, []);

  if (!checkedSession) return null;

  return (
    <WizardOrBuilder
      kind={kind}
      setKind={setKind}
      step={step}
      setStep={setStep}
      pendingTrigger={pendingTrigger}
      setPendingTrigger={setPendingTrigger}
      pendingInputs={pendingInputs}
      setPendingInputs={setPendingInputs}
      ephemeralPipeline={ephemeralPipeline}
      skipWizard={skipWizard}
    />
  );
}

interface WizardProps {
  kind: Kind | null;
  setKind: (k: Kind | null) => void;
  step: Step;
  setStep: (s: Step) => void;
  pendingTrigger: PendingTrigger;
  setPendingTrigger: (t: PendingTrigger) => void;
  pendingInputs: PipelineInput[];
  setPendingInputs: (inputs: PipelineInput[]) => void;
  ephemeralPipeline: PipelineJSON | null;
  skipWizard: boolean;
}

function WizardOrBuilder({
  kind, setKind, step, setStep,
  pendingTrigger, setPendingTrigger,
  pendingInputs, setPendingInputs,
  ephemeralPipeline,
  skipWizard,
}: WizardProps) {
  // "ready" = user clicked "進 Builder" on the final step.
  const [ready, setReady] = useState(false);

  // v1.5: when navigated from chat with ?from=agent, hand straight off
  // to BuilderLayout — no wizard, no kind gate. The hydrated pipeline
  // is already in ephemeralPipeline.
  // Phase 11 v4: ?embed=skill also skips the wizard but has no ephemeral
  // pipeline — just seeded inputs. Allow skipWizard regardless.
  useEffect(() => {
    if (skipWizard && kind && !ready) {
      setReady(true);
    }
  }, [skipWizard, kind, ready]);

  // When user lands on step 3 with no prior pendingInputs, pre-populate with
  // the pre-checked suggestions so the common case is already set.
  useEffect(() => {
    if (step !== 3) return;
    if (pendingInputs.length > 0) return;  // user already picked something
    if (!kind) return;
    const triggerMode: WizardTriggerMode =
      pendingTrigger?.kind === "auto_patrol" ? pendingTrigger.config.mode : null;
    const scopeType = pendingTrigger?.kind === "auto_patrol"
      ? pendingTrigger.scope.type
      : undefined;
    const defaults = getInputSuggestions(kind, triggerMode, scopeType)
      .filter((s) => s.preChecked)
      .map(suggestionToInput);
    if (defaults.length > 0) setPendingInputs(defaults);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, kind, pendingTrigger]);

  if (ready && kind) {
    // Hand off to BuilderLayout. Inputs ride on the initial pipeline_json.
    const initialJson: PipelineJSON = {
      version: "1.0",
      name: "新 Pipeline",
      metadata: {},
      nodes: ephemeralPipeline?.nodes ?? [],
      edges: ephemeralPipeline?.edges ?? [],
      inputs: pendingInputs.length > 0
        ? pendingInputs
        : (ephemeralPipeline?.inputs ?? []),
    };
    // Phase 11 v4: pipelineId is null on /new (gets one after first save +
    // BuilderLayout navigates to /[id]). Banner shows "press Save first" hint.
    return (
      <>
        <SkillEmbedBanner pipelineId={null}/>
        <BuilderLayout
          mode="new"
          initialKind={kind}
          initialPipelineJson={initialJson}
          initialPendingTrigger={pendingTrigger}
          initialPrompt={readSkillCtx()?.instruction}
        />
        <SurfaceTour surfaceId="pipeline-builder" steps={PIPELINE_BUILDER_STEPS} />
      </>
    );
  }

  // Step 1: Kind gate
  if (step === 1 || !kind) {
    return (
      <GateContainer
        title="建立新 Pipeline · Step 1/3"
        subtitle="先選 Pipeline 類型 — 不同類型有不同結構檢查 + 發佈路徑。下一步會依類型設 trigger + 宣告 inputs。"
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
          <KindCard
            emoji="🔍"
            label="Auto Patrol"
            tagline="定時 / 排程觸發 → 觸發即發 Alarm"
            bullets={[
              "結構需含 block_alert（必要終點）",
              "下一步：設定 event / schedule / 指定時間",
              "再下一步：宣告 pipeline inputs",
              "常用於：機台巡檢 / SPC OOC 監控",
            ]}
            accent="#B45309"
            onPick={() => {
              setKind("auto_patrol");
              setPendingTrigger({
                kind: "auto_patrol",
                config: emptyTrigger(),
                scope: defaultPickedScope,
              });
              setStep(2);
            }}
          />
          <KindCard
            emoji="⚡"
            label="Auto-Check (診斷規則)"
            tagline="Auto-Patrol 的 Alarm 觸發 → 自動跑這條 pipeline 做診斷"
            bullets={[
              "= 以前的 Diagnostic Rule",
              "綁定 Alarm：Auto-Patrol 觸發 alarm 後自動執行",
              "結構需含 block_alert 或 block_chart",
              "下一步：選要綁哪些 alarm 事件",
              "再下一步：宣告 inputs 接 alarm payload",
            ]}
            accent="#7C3AED"
            onPick={() => {
              setKind("auto_check");
              setPendingTrigger({ kind: "auto_check", config: emptyAutoCheckTrigger() });
              setStep(2);
            }}
          />
          <KindCard
            emoji="🩺"
            label="Skill"
            tagline="Agent / User on-demand → 吐圖吐表"
            bullets={[
              "結構需含 block_chart（必要終點）",
              "禁止含 block_alert",
              "On-demand 呼叫，不需設 trigger",
              "下一步：宣告 Agent 呼叫時要傳的 inputs",
            ]}
            accent="#166534"
            onPick={() => {
              setKind("skill");
              setPendingTrigger(null);
              // Skill bypasses trigger step — go straight to inputs step.
              setStep(3);
            }}
          />
        </div>
      </GateContainer>
    );
  }

  // Step 2: Trigger config (auto_patrol / auto_check only; skill never reaches here)
  if (step === 2) {
    return (
      <TriggerStep
        kind={kind}
        pendingTrigger={pendingTrigger}
        setPendingTrigger={setPendingTrigger}
        onBack={() => { setStep(1); setPendingTrigger(null); setKind(null); }}
        onNext={() => setStep(3)}
      />
    );
  }

  // Step 3: Inputs
  return (
    <InputsStep
      kind={kind}
      pendingTrigger={pendingTrigger}
      pendingInputs={pendingInputs}
      setPendingInputs={setPendingInputs}
      onBack={() => {
        // auto_patrol/auto_check go back to trigger step; skill goes to kind gate
        if (kind === "skill") { setStep(1); setKind(null); }
        else setStep(2);
      }}
      onNext={() => setReady(true)}
    />
  );
}

function TriggerStep({
  kind, pendingTrigger, setPendingTrigger, onBack, onNext,
}: {
  kind: Kind;
  pendingTrigger: PendingTrigger;
  setPendingTrigger: (t: PendingTrigger) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const [eventTypes, setEventTypes] = useState<EventType[]>([]);
  const [eventTypeSuggestions, setEventTypeSuggestions] = useState<string[]>([]);
  const [patrolSuggestions, setPatrolSuggestions] = useState<Array<{ id: number; name: string; pipeline_name?: string | null }>>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/admin/event-types", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        const items = Array.isArray(d) ? d : (d?.data ?? []);
        setEventTypes(items as EventType[]);
        setEventTypeSuggestions((items as EventType[]).map((e) => e.name));
      })
      .catch(() => { setEventTypes([]); setEventTypeSuggestions([]); });

    // Phase E1: also fetch active auto_patrols so user can bind to a
    // patrol-fired alarm via auto_patrol:{id} token.
    fetch("/api/admin/auto-patrols?active_only=true", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        const items = Array.isArray(d) ? d : (d?.data ?? []);
        setPatrolSuggestions(
          (items as Array<{ id: number; name: string; pipeline_name?: string | null }>)
            .filter((p) => p && p.id != null && p.name)
            .map((p) => ({ id: p.id, name: p.name, pipeline_name: p.pipeline_name ?? null })),
        );
      })
      .catch(() => setPatrolSuggestions([]));
  }, []);

  const handleNext = () => {
    if (kind === "auto_patrol" && pendingTrigger?.kind === "auto_patrol") {
      const err = validateTrigger(pendingTrigger.config);
      if (err) { setError(err); return; }
      // Validate scope only when trigger mode is non-event (event-mode patrols
      // don't use scope; the runtime resolves target from the alarm payload).
      if (pendingTrigger.config.mode !== "event") {
        const scopeErr = validatePickedScope(pendingTrigger.scope);
        if (scopeErr) { setError(scopeErr); return; }
      }
    } else if (kind === "auto_check" && pendingTrigger?.kind === "auto_check") {
      const err = validateAutoCheckTrigger(pendingTrigger.config);
      if (err) { setError(err); return; }
    }
    setError(null);
    onNext();
  };

  const showScopePicker =
    kind === "auto_patrol" &&
    pendingTrigger?.kind === "auto_patrol" &&
    (pendingTrigger.config.mode === "schedule" || pendingTrigger.config.mode === "once");

  return (
    <GateContainer
      title={(kind === "auto_patrol" ? "設定 Auto-Patrol 觸發條件" : "設定 Auto-Check 觸發條件") + " · Step 2/3"}
      subtitle={kind === "auto_patrol"
        ? "選擇什麼時候跑這個 pipeline — 事件觸發 / 排程 / 一次性指定時間。排程/一次性模式還要選「目標範圍」，下一步會依此設定建議 inputs。"
        : "選擇哪些 alarm event_type 會觸發這個 pipeline。下一步會建議接 alarm payload 用的 inputs。"}
    >
      <div style={cardBodyStyle}>
        {kind === "auto_patrol" && pendingTrigger?.kind === "auto_patrol" && (
          <AutoPatrolTriggerForm
            value={pendingTrigger.config}
            onChange={(next) => setPendingTrigger({
              kind: "auto_patrol",
              config: next,
              scope: pendingTrigger.scope,
            })}
            eventTypes={eventTypes}
          />
        )}
        {kind === "auto_check" && pendingTrigger?.kind === "auto_check" && (
          <AutoCheckTriggerForm
            value={pendingTrigger.config}
            onChange={(next) => setPendingTrigger({ kind: "auto_check", config: next })}
            suggestions={eventTypeSuggestions}
            patrolSuggestions={patrolSuggestions}
          />
        )}

        {showScopePicker && pendingTrigger?.kind === "auto_patrol" && (
          <div style={{ marginTop: 18, paddingTop: 18, borderTop: "1px dashed #E2E8F0" }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "#475569", marginBottom: 8 }}>
              目標範圍 — 排程 / 一次性觸發時，cron 跑的瞬間要跑哪些機台
            </div>
            <AutoPatrolScopePicker
              value={pendingTrigger.scope}
              onChange={(next) => setPendingTrigger({
                kind: "auto_patrol",
                config: pendingTrigger.config,
                scope: next,
              })}
            />
          </div>
        )}

        {error && (
          <div style={{ marginTop: 12, padding: 10, background: "#fff1f0", color: "#cf1322", borderRadius: 6, fontSize: 12 }}>
            {error}
          </div>
        )}

        <WizardNav onBack={onBack} onNext={handleNext} nextLabel="下一步 → 宣告 Inputs" />
      </div>
    </GateContainer>
  );
}

function InputsStep({
  kind, pendingTrigger, pendingInputs, setPendingInputs, onBack, onNext,
}: {
  kind: Kind;
  pendingTrigger: PendingTrigger;
  pendingInputs: PipelineInput[];
  setPendingInputs: (inputs: PipelineInput[]) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const triggerMode: WizardTriggerMode =
    pendingTrigger?.kind === "auto_patrol" ? pendingTrigger.config.mode : null;

  // Scope from Step 2 — used to gate the "next" button so the user can't ship
  // a pipeline whose declared inputs don't match what the runtime will inject.
  const patrolScope =
    pendingTrigger?.kind === "auto_patrol" && pendingTrigger.config.mode !== "event"
      ? pendingTrigger.scope
      : null;

  const handleNext = () => {
    const err = validateInputs(pendingInputs);
    if (err) { setError(err); return; }
    if (patrolScope) {
      const required = requiredInputsForScope(patrolScope);
      const declared = new Set(pendingInputs.map((i) => i.name));
      const missing = required.filter((n) => !declared.has(n));
      if (missing.length > 0) {
        const scopeLabel =
          patrolScope.type === "all_equipment" ? "所有機台"
          : patrolScope.type === "specific_equipment" ? "指定機台"
          : "指定站點";
        setError(
          `目標範圍 = 「${scopeLabel}」→ pipeline 必須宣告 input：${missing.join(", ")}。` +
          `runtime 會把 $loop.${missing[0]} 注入這個欄位，沒宣告就拿不到值。`,
        );
        return;
      }
    }
    setError(null);
    onNext();
  };

  return (
    <GateContainer
      title={`宣告 Pipeline Inputs · Step 3/3`}
      subtitle="這個 pipeline 在 runtime 會收到哪些變數？勾選常用 inputs 或自訂。至少需要 1 個 — 這是 pipeline 跟外界的契約。"
    >
      <div style={cardBodyStyle}>
        <WizardInputsStep
          kind={kind}
          triggerMode={triggerMode}
          scopeType={patrolScope?.type}
          value={pendingInputs}
          onChange={setPendingInputs}
        />

        {error && (
          <div style={{ marginTop: 12, padding: 10, background: "#fff1f0", color: "#cf1322", borderRadius: 6, fontSize: 12 }}>
            {error}
          </div>
        )}

        <WizardNav onBack={onBack} onNext={handleNext} nextLabel="進 Builder →" />
      </div>
    </GateContainer>
  );
}

function WizardNav({ onBack, onNext, nextLabel }: { onBack: () => void; onNext: () => void; nextLabel: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 20 }}>
      <button
        onClick={onBack}
        style={{
          padding: "8px 16px", fontSize: 13, borderRadius: 6, cursor: "pointer",
          background: "#fff", color: "#4a5568", border: "1px solid #e2e8f0",
        }}
      >
        ← 返回
      </button>
      <button
        onClick={onNext}
        style={{
          padding: "10px 20px", fontSize: 13, fontWeight: 600, borderRadius: 6, cursor: "pointer",
          background: "#1890ff", color: "#fff", border: "none",
        }}
      >
        {nextLabel}
      </button>
    </div>
  );
}

function GateContainer({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        padding: 40,
        maxWidth: 1100,
        margin: "40px auto",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      <h1 style={{ fontSize: 22, color: "#0F172A", marginBottom: 6 }}>{title}</h1>
      <div style={{ fontSize: 13, color: "#64748B", marginBottom: 24 }}>{subtitle}</div>
      {children}
    </div>
  );
}

function KindCard({
  emoji,
  label,
  tagline,
  bullets,
  accent,
  onPick,
}: {
  emoji: string;
  label: string;
  tagline: string;
  bullets: string[];
  accent: string;
  onPick: () => void;
}) {
  return (
    <button
      onClick={onPick}
      style={{
        textAlign: "left",
        padding: 18,
        border: `1px solid #E2E8F0`,
        borderRadius: 8,
        background: "#fff",
        cursor: "pointer",
        fontFamily: "inherit",
        transition: "border-color 120ms, box-shadow 120ms",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = accent;
        e.currentTarget.style.boxShadow = `0 2px 6px rgba(0,0,0,0.04)`;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "#E2E8F0";
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <span style={{ fontSize: 26 }}>{emoji}</span>
        <span style={{ fontSize: 16, fontWeight: 700, color: "#0F172A" }}>{label}</span>
      </div>
      <div style={{ fontSize: 12, color: accent, fontWeight: 600, marginBottom: 10 }}>{tagline}</div>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "#475569", lineHeight: 1.7 }}>
        {bullets.map((b, i) => (
          <li key={i}>{b}</li>
        ))}
      </ul>
    </button>
  );
}

const cardBodyStyle: React.CSSProperties = {
  padding: 24,
  border: "1px solid #E2E8F0",
  borderRadius: 10,
  background: "#fff",
};
