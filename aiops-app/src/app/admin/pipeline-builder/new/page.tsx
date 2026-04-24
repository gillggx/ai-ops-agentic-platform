"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { PipelineJSON } from "@/lib/pipeline-builder/types";
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

// React Flow can't SSR
const BuilderLayout = dynamic(() => import("@/components/pipeline-builder/BuilderLayout"), {
  ssr: false,
});

type Kind = "auto_patrol" | "auto_check" | "skill";

/** Payload handed to BuilderLayout. Auto-created on first save. */
export type PendingTrigger =
  | { kind: "auto_patrol"; config: AutoPatrolTriggerValue }
  | { kind: "auto_check"; config: AutoCheckTriggerValue }
  | null;

export default function NewPipelinePage() {
  const [kind, setKind] = useState<Kind | null>(null);
  // P4.2 — 2-step wizard state. Step 2 only shown for auto_patrol / auto_check.
  // Skill goes directly to Builder (step=done).
  const [step, setStep] = useState<1 | 2>(1);
  const [pendingTrigger, setPendingTrigger] = useState<PendingTrigger>(null);

  // Phase 5: ephemeral pipeline hydrated from Copilot's Edit-in-Builder button
  const [ephemeralPipeline, setEphemeralPipeline] = useState<PipelineJSON | null>(null);
  const [checkedSession, setCheckedSession] = useState(false);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("pb:ephemeral_pipeline");
      if (raw) {
        const payload = JSON.parse(raw) as { pipeline_json?: PipelineJSON; ts?: number };
        if (payload?.pipeline_json) {
          setEphemeralPipeline(payload.pipeline_json);
          setKind("skill");  // chat-built pipelines default to skill (no trigger needed)
        }
        sessionStorage.removeItem("pb:ephemeral_pipeline");
      }
    } catch {
      // ignore malformed payload
    }
    // Deep-link from Triggers Overview: ?kind=auto_check skips the kind gate.
    // Read from window.location (CSR-only) — useSearchParams would force a
    // Suspense boundary at prerender time.
    if (typeof window !== "undefined") {
      const q = new URLSearchParams(window.location.search).get("kind");
      if (q === "auto_patrol" || q === "auto_check" || q === "skill") {
        setKind(q);
        // Query-param landing goes through the same wizard — step 2 for
        // auto_patrol/auto_check, straight-through for skill.
        if (q === "skill") setStep(1);
        else setStep(2);
      }
    }
    setCheckedSession(true);
  }, []);

  if (!checkedSession) return null;

  // Done: hand off to the Builder with the captured pendingTrigger (if any).
  const wizardDone = kind != null && (
    kind === "skill" || step === 1 && kind == null /* never */ ||
    // For patrol/check, step must have advanced past 2
    (step === 2 && isTriggerReady(kind, pendingTrigger))
  );

  // Actually simpler: wizard is "done" when user explicitly clicks the
  // "下一步 → 進 Builder" button, which flips a dedicated flag.
  // But tracking that through React state is noisy; use kind presence + a
  // separate `ready` flag below.
  return <WizardOrBuilder
    kind={kind}
    setKind={setKind}
    step={step}
    setStep={setStep}
    pendingTrigger={pendingTrigger}
    setPendingTrigger={setPendingTrigger}
    ephemeralPipeline={ephemeralPipeline}
  />;
}

function isTriggerReady(kind: Kind | null, t: PendingTrigger): boolean {
  if (kind === "skill") return true;
  if (t == null) return false;
  if (t.kind === "auto_patrol") return validateTrigger(t.config) == null;
  if (t.kind === "auto_check") return validateAutoCheckTrigger(t.config) == null;
  return false;
}

interface WizardProps {
  kind: Kind | null;
  setKind: (k: Kind | null) => void;
  step: 1 | 2;
  setStep: (s: 1 | 2) => void;
  pendingTrigger: PendingTrigger;
  setPendingTrigger: (t: PendingTrigger) => void;
  ephemeralPipeline: PipelineJSON | null;
}

function WizardOrBuilder({
  kind, setKind, step, setStep,
  pendingTrigger, setPendingTrigger, ephemeralPipeline,
}: WizardProps) {
  // "ready" = user clicked 下一步 to proceed into Builder.
  const [ready, setReady] = useState(false);

  // Skill skips step 2 — go straight to Builder when kind is picked.
  useEffect(() => {
    if (kind === "skill") setReady(true);
  }, [kind]);

  if (ready && kind) {
    return (
      <BuilderLayout
        mode="new"
        initialKind={kind}
        initialPipelineJson={ephemeralPipeline ?? undefined}
        initialPendingTrigger={pendingTrigger}
      />
    );
  }

  // Step 1: Kind gate
  if (step === 1 || !kind) {
    return (
      <GateContainer
        title="建立新 Pipeline"
        subtitle="先選 Pipeline 類型 — 不同類型有不同結構檢查 + 發佈路徑。建立後仍可在 draft / validating 階段切換類型，lock / active 之後要 clone 才能改。"
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
          <KindCard
            emoji="🔍"
            label="Auto Patrol"
            tagline="定時 / 排程觸發 → 觸發即發 Alarm"
            bullets={[
              "結構需含 block_alert（必要終點）",
              "下一步：設定 event / schedule / 指定時間",
              "常用於：機台巡檢 / SPC OOC 監控",
            ]}
            accent="#B45309"
            onPick={() => {
              setKind("auto_patrol");
              setPendingTrigger({ kind: "auto_patrol", config: emptyTrigger() });
              setStep(2);
            }}
          />
          <KindCard
            emoji="⚡"
            label="Auto-Check"
            tagline="Alarm 觸發 → 自動帶入 alarm 資訊跑分析"
            bullets={[
              "結構需含 block_alert 或 block_chart",
              "**必須宣告 inputs**（alarm payload 依名稱自動填入）",
              "下一步：選要綁哪些 alarm event_type",
              "常用於：OOC 後自動診斷 / recipe drift 後自動畫圖",
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
              "常用於：Agent 對話中調用查資料",
            ]}
            accent="#166534"
            onPick={() => {
              setKind("skill");
              setPendingTrigger(null);
              // Skill bypasses step 2 entirely.
              setReady(true);
            }}
          />
        </div>
      </GateContainer>
    );
  }

  // Step 2: Trigger config (auto_patrol / auto_check only)
  return (
    <TriggerStep
      kind={kind}
      pendingTrigger={pendingTrigger}
      setPendingTrigger={setPendingTrigger}
      onBack={() => { setStep(1); setPendingTrigger(null); setKind(null); }}
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
  const [error, setError] = useState<string | null>(null);

  // Fetch event types (patrol: id-dropdown; check: name-suggestion chips)
  useEffect(() => {
    fetch("/api/admin/event-types", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        const items = Array.isArray(d) ? d : (d?.data ?? []);
        setEventTypes(items as EventType[]);
        setEventTypeSuggestions((items as EventType[]).map((e) => e.name));
      })
      .catch(() => { setEventTypes([]); setEventTypeSuggestions([]); });
  }, []);

  const handleNext = () => {
    if (kind === "auto_patrol" && pendingTrigger?.kind === "auto_patrol") {
      const err = validateTrigger(pendingTrigger.config);
      if (err) { setError(err); return; }
    } else if (kind === "auto_check" && pendingTrigger?.kind === "auto_check") {
      const err = validateAutoCheckTrigger(pendingTrigger.config);
      if (err) { setError(err); return; }
    }
    setError(null);
    onNext();
  };

  return (
    <GateContainer
      title={kind === "auto_patrol" ? "設定 Auto-Patrol 觸發條件" : "設定 Auto-Check 觸發條件"}
      subtitle={kind === "auto_patrol"
        ? "選擇什麼時候跑這個 pipeline — 事件觸發 / 排程 / 一次性指定時間。此設定會在 pipeline 第一次儲存時自動建立 Auto-Patrol 綁定。"
        : "選擇哪些 alarm event_type 會觸發這個 pipeline。綁定在 pipeline 發佈（→ active）時寫入。"}
    >
      <div
        style={{
          padding: 24,
          border: "1px solid #E2E8F0",
          borderRadius: 10,
          background: "#fff",
        }}
      >
        {kind === "auto_patrol" && pendingTrigger?.kind === "auto_patrol" && (
          <AutoPatrolTriggerForm
            value={pendingTrigger.config}
            onChange={(next) => setPendingTrigger({ kind: "auto_patrol", config: next })}
            eventTypes={eventTypes}
          />
        )}
        {kind === "auto_check" && pendingTrigger?.kind === "auto_check" && (
          <AutoCheckTriggerForm
            value={pendingTrigger.config}
            onChange={(next) => setPendingTrigger({ kind: "auto_check", config: next })}
            suggestions={eventTypeSuggestions}
          />
        )}

        {error && (
          <div style={{ marginTop: 12, padding: 10, background: "#fff1f0", color: "#cf1322", borderRadius: 6, fontSize: 12 }}>
            {error}
          </div>
        )}

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
            onClick={handleNext}
            style={{
              padding: "10px 20px", fontSize: 13, fontWeight: 600, borderRadius: 6, cursor: "pointer",
              background: "#1890ff", color: "#fff", border: "none",
            }}
          >
            下一步 → 進 Builder
          </button>
        </div>
      </div>
    </GateContainer>
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
