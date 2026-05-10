"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  createPipeline,
  deprecatePipeline,
  executePipeline,
  forkPipeline,
  getPipeline,
  listBlocks,
  promotePipeline,
  transitionPipeline,
  updatePipeline,
  validatePipeline,
} from "@/lib/pipeline-builder/api";
import type { PipelineStatus } from "@/lib/pipeline-builder/types";
import { BuilderProvider, useBuilder, useBuilderKeybindings } from "@/context/pipeline-builder/BuilderContext";
import type {
  BlockSpec,
  ExecuteResponse,
  PipelineJSON,
  PipelineRecord,
  ValidationErrorItem,
} from "@/lib/pipeline-builder/types";
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle } from "react-resizable-panels";
import BlockLibrary from "./BlockLibrary";
import DagCanvas from "./DagCanvas";
import NodeInspector from "./NodeInspector";
import EdgeInspector from "./EdgeInspector";
import DataPreviewPanel from "./DataPreviewPanel";
import StatusBadge from "./StatusBadge";
import ValidationDrawer from "./ValidationDrawer";
// Phase 5-UX-3b: Old Builder-specific AgentPanel removed. Users now talk to
// the unified AI Agent via a /chat/[id] tab (opened from Topbar search bar or
// the "Ask Agent" button below, which redirects to /chat/new?prompt=...).
import PipelineResultsPanel from "./PipelineResultsPanel";
import PipelineInputsPanel from "./PipelineInputsPanel";
import PipelineRunDialog from "./PipelineRunDialog";
import PipelineInfoModal from "./PipelineInfoModal";
import PublishReviewModal from "./PublishReviewModal";
import AutoCheckPublishModal from "./AutoCheckPublishModal";
import AutoPatrolSetupModal from "./AutoPatrolSetupModal";
import PipelineThemeStyles from "./PipelineThemeStyles";
import { blockDisplayName } from "@/lib/pipeline-builder/style";
// Phase 5-UX-5: right-side Agent|Parameters|Runs tab panel.
import RightTabbedPanel from "./RightTabbedPanel";
// Phase 5-UX-5 fix: restore Glass Box Agent (iterative node-by-node build).
// The unified AIAgentPanel was one-shot (build_pipeline in a single tool call);
// user wants to watch the agent pull nodes onto the canvas step by step.
import AgentBuilderPanel from "./AgentBuilderPanel";
// Phase E3: AIAgentPanel now used in BuilderLayout too (single agent UX).
// AgentBuilderPanel kept only as a fallback in case the new wiring regresses;
// will be deleted once mode="builder" + onGlassOp path is verified in prod.
import { AIAgentPanel } from "@/components/copilot/AIAgentPanel";
import { applyGlassOpToCanvas } from "@/context/pipeline-builder/useAgentStream";

interface Props {
  // Phase 5-UX-3b: "session" = /chat/[id] tab mode. Hosts AI Agent on the right
  // side and hydrates canvas from session.last_pipeline_json. Hides publish/
  // lifecycle controls (those belong in /admin/pipeline-builder).
  mode: "new" | "edit" | "session";
  pipelineId?: number;
  /** PR-B: kind picked in the new-pipeline gate page; sent on first save. */
  initialKind?: "auto_patrol" | "auto_check" | "skill";
  /** Phase 5: ephemeral pipeline hydrated from chat's Edit-in-Builder handoff. */
  initialPipelineJson?: PipelineJSON;
  /** P4.3: trigger config captured in the kind+trigger wizard. Auto-binds on
   *  first save — patrol → POST /admin/auto-patrols, check → publish-auto-check. */
  initialPendingTrigger?: import("@/app/admin/pipeline-builder/new/page").PendingTrigger;
  /** Phase 5-UX-3b: session id — required when mode="session". Pins the AI Agent
   *  panel on the right to a specific conversation for history + continuity. */
  sessionId?: string;
  /** Phase 5-UX-3b: seed prompt auto-sent once when session mode mounts. */
  initialPrompt?: string;
  /** Phase 5-UX-6: when false, BuilderInner uses position:relative + fills
   *  parent instead of position:fixed covering the viewport. LiveCanvasOverlay
   *  needs this so its own NarrationStrip + EventLogPanel don't get hidden
   *  behind BuilderInner's fixed layer. Default true (existing callers). */
  fillViewport?: boolean;
  /** Phase 5-UX-6: override the Agent tab content (replaces AgentBuilderPanel).
   *  LiveCanvasOverlay uses this to put its glass-event log inside the existing
   *  Agent tab instead of a separate panel, consolidating the right side. */
  agentTabContent?: React.ReactNode;
}

export default function BuilderLayout(props: Props) {
  return (
    <BuilderProvider>
      <BuilderInner {...props} />
    </BuilderProvider>
  );
}

/** Phase 5-UX-6: variant that does NOT wrap its own BuilderProvider, so a
 *  parent can control the canvas context (e.g. LiveCanvasOverlay wants to
 *  apply agent operations to the SAME context the canvas renders). */
export function BuilderLayoutNoProvider(props: Props) {
  return <BuilderInner {...props} />;
}

function BuilderInner({ mode, pipelineId, initialKind, initialPipelineJson, initialPendingTrigger, sessionId, initialPrompt, fillViewport = true, agentTabContent }: Props) {
  // P4.3: pendingTrigger lives in a ref so it survives re-renders but is
  // consumed + cleared exactly once on first save. Captured from prop on mount.
  const pendingTriggerRef = useRef(initialPendingTrigger ?? null);
  const { state, actions, selectedNode, selectedEdge } = useBuilder();
  useBuilderKeybindings();
  const router = useRouter();

  const [catalog, setCatalog] = useState<BlockSpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [runResult, setRunResult] = useState<ExecuteResponse | null>(null);
  const [validationOpen, setValidationOpen] = useState(false);
  const [validationErrors, setValidationErrors] = useState<ValidationErrorItem[]>([]);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  // Phase 5-UX-5: focus state for Copilot — user's next chat message is about
  // this node. Set via NodeInspector's "Ask Agent" button or right-click menu.
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  // Phase 5-UX-5 fix: lift right-panel tab state so the top-bar "Ask Agent"
  // button + "Ask about this" from Inspector can programmatically switch tabs.
  const [rightTab, setRightTab] = useState<"agent" | "parameters" | "runs">("agent");
  const [resultsPanelOpen, setResultsPanelOpen] = useState(false);
  const [inputsPanelOpen, setInputsPanelOpen] = useState(false);
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [infoModalOpen, setInfoModalOpen] = useState(false);
  const [publishModalOpen, setPublishModalOpen] = useState(false);
  // Phase 5-UX-7: separate publish modal for auto_check (event binding)
  const [autoCheckModalOpen, setAutoCheckModalOpen] = useState(false);
  // Option A Phase β: Auto-Patrol setup modal — inline patrol creation without leaving the Builder.
  const [autoPatrolModalOpen, setAutoPatrolModalOpen] = useState(false);
  // P4.4: the Auto-Patrol currently bound to this pipeline (for edit mode).
  // null = not fetched yet; undefined = fetched but none exists (unbound).
  // P5 Auto-Check binding visibility: show user which alarm event_types
  // currently route to this pipeline. Backend table:
  //   pipeline_auto_check_triggers(pipeline_id, event_type, match_filter)
  const [autoCheckBindings, setAutoCheckBindings] = useState<
    Array<{ event_type: string; match_filter: Record<string, string[]> | null }> | null
  >(null);
  const [boundPatrol, setBoundPatrol] = useState<
    | null
    | undefined
    | {
        id: number;
        name: string;
        description: string;
        trigger_mode: "event" | "schedule" | "once";
        event_type_id: number | null;
        cron_expr: string | null;
        scheduled_at: string | null;
        alarm_severity: string | null;
        alarm_title: string | null;
        input_binding: Record<string, unknown> | null;
      }
  >(null);
  const [autoRun, setAutoRun] = useState(false);
  const [toast, setToast] = useState<{ kind: "info" | "error" | "success"; text: string } | null>(null);
  const [nameDraft, setNameDraft] = useState(state.pipeline.name);
  const autoRunTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // PR-B: locked / active / archived are all read-only. Only draft + validating are editable.
  const readOnly =
    state.meta.status === "locked" ||
    state.meta.status === "active" ||
    state.meta.status === "archived";

  // Load catalog + pipeline
  useEffect(() => {
    (async () => {
      try {
        const blocks = await listBlocks();
        setCatalog(blocks);
        if (mode === "edit" && pipelineId) {
          const rec = await getPipeline(pipelineId);
          actions.init(rec);
          setNameDraft(rec.pipeline_json.name);
        } else if (initialPipelineJson) {
          // Phase 5: hydrate from chat's ephemeral pipeline — mark dirty so user can save
          actions.init({ pipeline: initialPipelineJson });
        } else if (mode === "session") {
          // Phase 5-UX-6 race fix: in session mode the parent (LiveCanvasOverlay
          // or /chat/[id] page) owns the BuilderContext and will populate it
          // via glass-ops as SSE events arrive. This effect's async completion
          // races with those ops — resetting to empty here wipes out the nodes
          // the agent just added. So: DO NOT init in session mode.
        } else {
          actions.init({ pipeline: { version: "1.0", name: "新 Pipeline", nodes: [], edges: [], metadata: {} } });
        }
      } catch (e) {
        setToast({ kind: "error", text: (e as Error).message });
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, pipelineId]);

  useEffect(() => {
    if (!loading) setNameDraft(state.pipeline.name);
  }, [state.pipeline.name, loading]);

  // P4.4: fetch any Auto-Patrol bound to this pipeline so the 🔔 button can
  // switch label + open in edit mode. Refires when pipelineId changes (after
  // first save the wizard-posted patrol will show up on next fetch).
  const fetchBoundPatrol = useCallback(async () => {
    const pid = state.meta.pipelineId;
    if (pid == null || mode === "session") return;
    try {
      const res = await fetch("/api/admin/auto-patrols", { cache: "no-store" });
      const list = await res.json();
      const match = (Array.isArray(list) ? list : []).find(
        (p: Record<string, unknown>) => p.pipeline_id === pid,
      );
      setBoundPatrol(
        match
          ? {
              id: Number(match.id),
              name: String(match.name ?? ""),
              description: String(match.description ?? ""),
              trigger_mode: (match.trigger_mode as "event" | "schedule" | "once") ?? "event",
              event_type_id: (match.event_type_id as number) ?? null,
              cron_expr: (match.cron_expr as string) ?? null,
              scheduled_at: (match.scheduled_at as string) ?? null,
              alarm_severity: (match.alarm_severity as string) ?? null,
              alarm_title: (match.alarm_title as string) ?? null,
              input_binding: (match.input_binding as Record<string, unknown>) ?? null,
            }
          : undefined,
      );
    } catch {
      setBoundPatrol(undefined);
    }
  }, [state.meta.pipelineId, mode]);
  useEffect(() => { void fetchBoundPatrol(); }, [fetchBoundPatrol]);

  // Fetch auto_check trigger bindings (kind=auto_check only). Lets the canvas
  // banner display "this pipeline is triggered by alarm.X / patrol Y" so the
  // user can confirm the wiring at a glance instead of opening the modal.
  useEffect(() => {
    if (mode === "session") return;
    if (state.meta.pipelineKind !== "auto_check") {
      setAutoCheckBindings(null);
      return;
    }
    if (state.meta.pipelineId == null) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `/api/admin/pipelines/${state.meta.pipelineId}/auto-check-triggers`,
          { cache: "no-store" },
        );
        if (!res.ok) { setAutoCheckBindings([]); return; }
        const json = await res.json();
        // Java DTO uses camelCase (eventType / matchFilter), Python era used
        // snake_case. Accept both for graceful migration.
        const data = (json?.data ?? json) as Array<{
          eventType?: string; event_type?: string;
          matchFilter?: Record<string, string[]> | null;
          match_filter?: Record<string, string[]> | null;
        }>;
        if (!cancelled) {
          setAutoCheckBindings(
            (Array.isArray(data) ? data : []).map((b) => ({
              event_type: b.eventType ?? b.event_type ?? "",
              match_filter: b.matchFilter ?? b.match_filter ?? null,
            })).filter((b) => b.event_type),
          );
        }
      } catch {
        if (!cancelled) setAutoCheckBindings([]);
      }
    })();
    return () => { cancelled = true; };
  }, [state.meta.pipelineId, state.meta.pipelineKind, mode]);

  // Warn on unload if dirty
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (state.dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [state.dirty]);

  const showToast = (kind: "info" | "error" | "success", text: string) => {
    setToast({ kind, text });
    setTimeout(() => setToast(null), 3000);
  };

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      if (state.meta.pipelineId == null) {
        const rec = await createPipeline({
          name: state.pipeline.name,
          description: state.description,
          pipeline_kind: initialKind ?? "skill",
          pipeline_json: state.pipeline,
        });
        actions.init(rec);
        actions.markSaved();

        // P4.3: if wizard supplied a pendingTrigger, auto-bind now (once).
        const pending = pendingTriggerRef.current;
        if (pending) {
          pendingTriggerRef.current = null;  // consume; prevent re-fire
          try {
            if (pending.kind === "auto_patrol") {
              const cfg = pending.config;
              // Event-mode patrols resolve the target from the alarm payload at
              // runtime, so target_scope is implicitly event_driven and the
              // wizard never asks the user. Schedule/once-mode patrols carry the
              // scope picked in Step 2 — all_equipment / specific_equipment /
              // by_step + fanout_cap.
              const scopeJson = cfg.mode === "event"
                ? { type: "event_driven" as const }
                : pending.scope;
              const body = {
                name: `[Patrol] ${state.pipeline.name}`.slice(0, 200),
                description: state.description,
                trigger_mode: cfg.mode,
                cron_expr: cfg.mode === "schedule" ? cfg.cronExpr : null,
                scheduled_at: cfg.mode === "once" ? cfg.scheduledAt : null,
                event_type_id: cfg.mode === "event" ? cfg.eventTypeId : null,
                execution_mode: "pipeline",
                pipeline_id: rec.id,
                alarm_severity: "HIGH",
                alarm_title: state.pipeline.name,
                target_scope: JSON.stringify(scopeJson),
                data_context: cfg.mode === "event" ? "event_driven" : "scheduled",
                is_active: true,
              };
              const res = await fetch("/api/admin/auto-patrols", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
              });
              if (!res.ok) throw new Error(`HTTP ${res.status}`);
              showToast("success", "已儲存 Draft + 建立 Auto-Patrol 綁定");
            } else if (pending.kind === "auto_check") {
              const eventTypes = pending.config.eventTypesText
                .split(/[,\n]+/).map((s) => s.trim()).filter(Boolean);
              if (eventTypes.length > 0) {
                // Auto-Check binding only happens at publish time (locked → active).
                // Stash the wizard-captured event_types in sessionStorage so
                // AutoCheckPublishModal pre-fills when the user clicks Publish.
                try {
                  sessionStorage.setItem(
                    `pb:pending_auto_check:${rec.id}`,
                    JSON.stringify({ event_types: eventTypes, ts: Date.now() }),
                  );
                } catch {}
                showToast("success", `已儲存 Draft · ${eventTypes.length} 個 event_type 已記下，發佈時會自動帶入`);
              } else {
                showToast("success", "已儲存為 Draft");
              }
            }
          } catch (bindErr) {
            // Surface binding failure but don't block the save — user can retry
            // via the 🔔 button after closing the toast.
            showToast("error", `Pipeline 已儲存，但 trigger 綁定失敗：${(bindErr as Error).message}`);
          }
        } else {
          showToast("success", "已儲存為 Draft");
        }

        router.replace(`/admin/pipeline-builder/${rec.id}`);
      } else {
        const rec = await updatePipeline(state.meta.pipelineId, {
          name: state.pipeline.name,
          description: state.description,
          pipeline_json: state.pipeline,
        });
        actions.init(rec);
        actions.markSaved();
        showToast("success", "已儲存");
      }
    } catch (e) {
      showToast("error", `儲存失敗：${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }, [state, actions, router, initialKind]);

  const handleValidate = useCallback(async () => {
    try {
      const res = await validatePipeline(state.pipeline);
      setValidationErrors(res.errors);
      setValidationOpen(true);
    } catch (e) {
      showToast("error", (e as Error).message);
    }
  }, [state.pipeline]);

  const executeWithInputs = useCallback(async (providedInputs: Record<string, unknown>) => {
    setRunResult(null);
    try {
      const res = await executePipeline(state.pipeline, providedInputs);
      setRunResult(res);
      if (res.node_results && Object.keys(res.node_results).length > 0) {
        actions.mergeNodeResults(res.node_results);
      }
      if (res.status === "validation_error") {
        setValidationErrors(res.errors ?? []);
        setValidationOpen(true);
        showToast("error", "Pipeline 驗證失敗");
      } else if (res.status === "success") {
        showToast("success", `執行成功（run_id=${res.run_id}）`);
        if (res.result_summary) setResultsPanelOpen(true);
      } else {
        showToast("error", `執行失敗：${res.error_message ?? "unknown"}`);
      }
    } catch (e) {
      showToast("error", (e as Error).message);
    }
  }, [state.pipeline, actions]);

  const handleRun = useCallback(async () => {
    // Phase 4-B0: if any required input lacks a default + example, open Run Dialog first
    const declared = state.pipeline.inputs ?? [];
    const needsPrompt = declared.some(
      (i) => i.required && i.default === null && i.example === null,
    ) || declared.some(
      (i) => i.required && i.default === undefined && i.example === undefined,
    );
    if (declared.length > 0 && needsPrompt) {
      setRunDialogOpen(true);
      return;
    }

    // Otherwise silent run with defaults/examples
    const silentInputs: Record<string, unknown> = {};
    for (const inp of declared) {
      if (inp.default != null) silentInputs[inp.name] = inp.default;
      else if (inp.example != null) silentInputs[inp.name] = inp.example;
    }
    void executeWithInputs(silentInputs);
  }, [state.pipeline.inputs, executeWithInputs]);

  /** UX Fix Pack: Auto-run on change — debounce 1500ms after pipeline mutations.
   *  Skips when autoRun is off, pipeline empty, readOnly, or pipeline has required
   *  inputs (would prompt dialog, bad UX on every edit). */
  useEffect(() => {
    if (!autoRun) return;
    if (readOnly) return;
    if (state.pipeline.nodes.length === 0) return;
    const hasRequiredInputs = (state.pipeline.inputs ?? []).some(
      (i) => i.required && i.default == null && i.example == null,
    );
    if (hasRequiredInputs) return;
    if (autoRunTimerRef.current) clearTimeout(autoRunTimerRef.current);
    autoRunTimerRef.current = setTimeout(() => {
      void handleRun();
    }, 1500);
    return () => {
      if (autoRunTimerRef.current) clearTimeout(autoRunTimerRef.current);
    };
  }, [autoRun, readOnly, state.pipeline.nodes, state.pipeline.edges, state.pipeline.inputs, handleRun]);

  // PR-B: unified lifecycle transition + back-compat helpers.
  const handleTransition = useCallback(
    async (to: PipelineStatus, confirmMsg?: string) => {
      if (state.meta.pipelineId == null) {
        showToast("error", "請先儲存 pipeline");
        return;
      }
      if (state.dirty && to !== "draft") {
        showToast("error", "請先儲存變更");
        return;
      }
      if (confirmMsg && !confirm(confirmMsg)) return;
      try {
        await transitionPipeline(state.meta.pipelineId, to);
        showToast("success", `狀態已更新為 ${to}`);
        const rec = await getPipeline(state.meta.pipelineId);
        actions.init(rec);
      } catch (e) {
        showToast("error", (e as Error).message);
      }
    },
    [state.meta.pipelineId, state.dirty, actions],
  );

  const handleClone = useCallback(async () => {
    if (state.meta.pipelineId == null) return;
    try {
      const cloned = await forkPipeline(state.meta.pipelineId);
      showToast("success", "已 Clone 為新 Draft");
      router.push(`/admin/pipeline-builder/${cloned.id}`);
    } catch (e) {
      showToast("error", (e as Error).message);
    }
  }, [state.meta.pipelineId, router]);

  // Back-compat referenced elsewhere (not currently wired in UI)
  const handleDeprecate = useCallback(async () => {
    if (state.meta.pipelineId == null) return;
    if (!confirm("封存後不可恢復（僅能 Clone 建立新版本），確定？")) return;
    try {
      await deprecatePipeline(state.meta.pipelineId);
      showToast("success", "已封存");
      const rec = await getPipeline(state.meta.pipelineId);
      actions.init(rec);
    } catch (e) {
      showToast("error", (e as Error).message);
    }
  }, [state.meta.pipelineId, actions]);

  const runStatuses = runResult
    ? Object.fromEntries(
        Object.entries(runResult.node_results).map(([k, v]) => [k, v.status])
      )
    : {};

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "#8c8c8c" }}>載入中...</div>
    );
  }

  return (
    <div
      data-testid="builder-root"
      data-pb-theme={state.theme}
      data-pb-density={state.density}
      style={{
        // Phase 5-UX-6: fillViewport=false (LiveCanvasOverlay) → fill parent
        // instead of escaping the flow with fixed positioning.
        ...(fillViewport
          ? { position: "fixed", top: 0, left: 0, right: 0, bottom: 0, zIndex: 100 }
          : { position: "relative", width: "100%", height: "100%" }),
        display: "flex",
        flexDirection: "column",
        background: "var(--pb-canvas-bg)",
        color: "var(--pb-text)",
        fontFamily: "system-ui, -apple-system, 'Noto Sans TC', sans-serif",
      }}
    >
      <PipelineThemeStyles />
      {/* Header */}
      <div
        style={{
          padding: "8px 18px",
          background: "var(--pb-panel-bg)",
          borderBottom: "1px solid var(--pb-panel-border)",
          color: "var(--pb-text)",
          display: "flex",
          alignItems: "center",
          gap: 12,
          zIndex: 5,
        }}
      >
        {mode !== "session" && (() => {
          // Phase 11 v6 — when launched from a Skill (sessionStorage ctx),
          // the back link should return to the parent Skill detail page,
          // not the (now-redirected) Pipeline Builder list. Read the ctx
          // here instead of importing SkillEmbedBanner to avoid a cycle.
          let backHref = "/admin/pipeline-builder";
          let backLabel = "← List";
          if (typeof window !== "undefined") {
            try {
              const raw = sessionStorage.getItem("pb:skill_embed_ctx");
              if (raw) {
                const ctx = JSON.parse(raw) as { skill_slug?: string };
                if (ctx?.skill_slug) {
                  backHref = `/skills/${encodeURIComponent(ctx.skill_slug)}/edit`;
                  backLabel = `← back to Skill`;
                }
              }
            } catch { /* ignore */ }
          }
          return (
            <>
              <button
                onClick={() => router.push(backHref)}
                style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "#4F46E5", padding: 0 }}
              >
                {backLabel}
              </button>
              <span style={{ color: "#CBD5E1" }}>/</span>
            </>
          );
        })()}
        {mode === "session" && (
          <>
            <button
              onClick={() => {
                if (state.dirty) {
                  const ok = window.confirm("這個 session 未儲存，確定離開？");
                  if (!ok) return;
                }
                // Phase 5-UX-6 fix: session page has a beforeunload guard +
                // the SSE reader can prevent clean unmount; router.push silently
                // no-ops. Use hard nav to force-leave. Pre-clear dirty flag so
                // beforeunload doesn't pop the browser's native prompt too.
                actions.markSaved();
                setTimeout(() => {
                  window.location.href = "/dashboard";
                }, 0);
              }}
              title="回 Dashboard（session 內容留存，可從對話列表重開）"
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "#4F46E5", padding: 0 }}
            >
              ← Dashboard
            </button>
            <span style={{ color: "#CBD5E1" }}>/</span>
            <span style={{ fontSize: 12, color: "#64748B" }}>💬 Session</span>
            <span style={{ color: "#CBD5E1" }}>/</span>
          </>
        )}
        <input
          data-testid="pipeline-name-input"
          type="text"
          value={nameDraft}
          onChange={(e) => setNameDraft(e.target.value)}
          onBlur={() => {
            if (nameDraft && nameDraft !== state.pipeline.name) {
              actions.renamePipeline(nameDraft);
            }
          }}
          disabled={readOnly}
          onFocus={(e) => (e.currentTarget.style.border = "1px solid #CBD5E1")}
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: "#0F172A",
            border: "1px dashed #CBD5E1",
            padding: "3px 6px",
            borderRadius: 3,
            outline: "none",
            background: readOnly ? "#F1F5F9" : "#fff",
            minWidth: 220,
          }}
          title="點擊編輯名稱；完整資訊點 ✏️ Info"
        />
        <button
          data-testid="btn-info"
          onClick={() => setInfoModalOpen(true)}
          title="編輯 Pipeline 基本資訊（名稱、描述）"
          style={{
            background: "none",
            border: "1px solid #CBD5E1",
            cursor: "pointer",
            fontSize: 12,
            color: "#475569",
            padding: "3px 8px",
            borderRadius: 3,
            lineHeight: 1.2,
          }}
        >
          ✏️ Info
        </button>
        {state.dirty && (
          <span style={{ fontSize: 10, color: "#D97706", letterSpacing: "0.05em", textTransform: "uppercase", fontWeight: 600 }}>
            ● Unsaved
          </span>
        )}

        {/* Status bar (STATUS / ACTIVE NODES / SELECTED) */}
        <div
          data-testid="status-bar"
          style={{
            marginLeft: 18,
            display: "flex",
            gap: 18,
            fontSize: 10,
            color: "#64748B",
            letterSpacing: "0.05em",
          }}
        >
          <StatusBarItem label="STATUS">
            <StatusBadge status={state.meta.status} />
          </StatusBarItem>
          <StatusBarItem label="ACTIVE NODES">
            <span data-testid="sb-active-nodes" style={{ fontSize: 13, fontWeight: 600, color: "#0F172A" }}>
              {state.pipeline.nodes.length}
            </span>
          </StatusBarItem>
          <StatusBarItem label="SELECTED">
            <span data-testid="sb-selected" style={{ fontSize: 12, fontWeight: 500, color: "#0F172A" }}>
              {selectedNode
                ? (selectedNode.display_label ?? blockDisplayName(selectedNode.block_id))
                : "—"}
            </span>
          </StatusBarItem>
          {runResult?.result_summary && (
            <StatusBarItem label="RESULT">
              <span
                data-testid="sb-pipeline-result"
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  padding: "2px 8px",
                  borderRadius: 3,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  background: runResult.result_summary.triggered ? "#DCFCE7" : "#F1F5F9",
                  color: runResult.result_summary.triggered ? "#166534" : "#64748B",
                  border: `1px solid ${runResult.result_summary.triggered ? "#86EFAC" : "#CBD5E1"}`,
                }}
              >
                {runResult.result_summary.triggered ? "✓ Triggered" : "✗ Not Triggered"}
              </span>
            </StatusBarItem>
          )}
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {/* PR-D1/D3 visual prefs */}
          <button
            data-testid="btn-theme"
            onClick={() => actions.setTheme(state.theme === "dark" ? "light" : "dark")}
            title={state.theme === "dark" ? "切到亮色" : "切到暗色"}
            style={{
              ...btn("ghost"),
              fontSize: 14,
              padding: "4px 8px",
            }}
          >
            {state.theme === "dark" ? "☀" : "🌙"}
          </button>
          <button
            data-testid="btn-density"
            onClick={() => actions.setDensity(state.density === "full" ? "compact" : "full")}
            title={state.density === "full" ? "切換成緊湊" : "切換成完整"}
            style={{
              ...btn("ghost"),
              fontSize: 11,
              padding: "4px 8px",
              letterSpacing: "0.03em",
              fontWeight: 600,
            }}
          >
            {state.density === "full" ? "▤ Full" : "▢ Compact"}
          </button>
          <button data-testid="btn-undo" onClick={actions.undo} title="Undo (Cmd/Ctrl+Z)" style={btn("ghost", readOnly)}>
            ↶
          </button>
          <button data-testid="btn-redo" onClick={actions.redo} title="Redo (Cmd/Ctrl+Y)" style={btn("ghost", readOnly)}>
            ↷
          </button>
          {/* Phase 5-UX-6 fix: "Ask Agent" button removed — the Agent tab is
              always present on the right, and NodeInspector's per-node "Ask
              about this" already focuses it. Redundant top-bar entry. */}
          <button
            data-testid="btn-pipeline-inputs"
            onClick={() => setInputsPanelOpen(true)}
            style={{ ...btn("ghost"), color: "#3730A3", borderColor: "#C7D2FE" }}
            title="宣告 pipeline 變數（讓 pipeline 可重用）"
          >
            🔣 Inputs ({state.pipeline.inputs?.length ?? 0})
          </button>
          <button data-testid="btn-validate" onClick={handleValidate} style={btn("ghost")}>
            Validate
          </button>
          <label
            data-testid="auto-run-toggle"
            title="改動 pipeline 後延遲 1.5 秒自動執行（避免大 pipeline 卡頓時可關閉）"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              fontSize: 11,
              color: autoRun ? "#16A34A" : "#64748B",
              cursor: readOnly ? "not-allowed" : "pointer",
              padding: "3px 8px",
              borderRadius: 3,
              border: `1px solid ${autoRun ? "#86EFAC" : "#CBD5E1"}`,
              background: autoRun ? "#F0FDF4" : "#fff",
              opacity: readOnly ? 0.5 : 1,
              fontWeight: 500,
              userSelect: "none",
            }}
          >
            <input
              type="checkbox"
              checked={autoRun}
              onChange={(e) => setAutoRun(e.target.checked)}
              disabled={readOnly}
              style={{ margin: 0 }}
            />
            Auto
          </label>
          <button
            data-testid="btn-run"
            data-tour-id="pb-run-full"
            onClick={handleRun}
            style={{ ...btn("primary"), background: "#16A34A", borderColor: "#16A34A" }}
            title="執行整條 pipeline — 節點上會顯示每個 node 的 rows / error 徽章"
          >
            ▶ Run Full
          </button>
          {runResult?.result_summary && (
            <button
              data-testid="btn-pipeline-results"
              onClick={() => setResultsPanelOpen(true)}
              style={{ ...btn("ghost"), background: "#F0FDF4", color: "#166534", borderColor: "#BBF7D0", fontWeight: 600 }}
              title="Show pipeline result summary + charts"
            >
              📊 Results
            </button>
          )}
          {mode !== "session" && (
            <button
              data-testid="btn-save"
              onClick={handleSave}
              disabled={saving || readOnly}
              style={btn(state.dirty ? "primary" : "ghost", saving || readOnly)}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          )}
          {mode === "session" && (
            <button
              onClick={async () => {
                // Phase 5-UX-3b: "Save as Skill" in session mode → persist as
                // draft pipeline + open the real Builder so user can pick kind
                // + publish via the lifecycle flow.
                const name = window.prompt("儲存為 Pipeline（之後可在 Pipeline Builder 選 kind + 發佈）\n\n名稱：", state.pipeline.name || "session pipeline");
                if (!name) return;
                try {
                  const rec = await createPipeline({
                    name,
                    description: `從對話 session 建立`,
                    pipeline_json: state.pipeline,
                  });
                  window.open(`/admin/pipeline-builder/${rec.id}`, "_blank");
                  showToast("success", `已建立 pipeline #${rec.id}`);
                } catch (e) {
                  showToast("error", `儲存失敗：${(e as Error).message}`);
                }
              }}
              style={btn("primary")}
              title="把這個 session 的 pipeline 存起來，稍後可發佈為 Skill"
            >
              📌 存為 Pipeline
            </button>
          )}

          {/* PR-B lifecycle transition buttons — hidden in session mode (publish
              lives in /admin/pipeline-builder). */}
          {mode !== "session" && state.meta.status === "draft" && state.meta.pipelineId != null && (
            <button
              onClick={() => handleTransition("validating")}
              style={btn("ghost")}
              title="進入測試階段：驗證結構 + 用真實資料預覽"
            >
              → 開始測試
            </button>
          )}
          {mode !== "session" && state.meta.status === "validating" && state.meta.pipelineId != null && (
            <>
              <button
                onClick={() => handleTransition("locked")}
                style={btn("primary")}
                title="凍結 pipeline + LLM 產文件 + 準備上架"
              >
                → 準備上架
              </button>
              <button onClick={() => handleTransition("draft")} style={btn("ghost")}>
                ← 退回 Draft
              </button>
            </>
          )}
          {mode !== "session" && state.meta.status === "locked" && state.meta.pipelineId != null && (
            <>
              {/* Phase 5-UX-7 publish routing by kind:
                  skill      → Review Modal (writes pb_published_skills + → active)
                  auto_check → AutoCheckTriggerModal (bind event_types + → active)
                  auto_patrol → direct transition to active */}
              <button
                onClick={() => {
                  const kind = state.meta.pipelineKind ?? initialKind;
                  if (kind === "auto_check") {
                    setAutoCheckModalOpen(true);
                  } else if (kind === "skill" || kind === "diagnostic" || kind == null) {
                    setPublishModalOpen(true);
                  } else {
                    void handleTransition("active", "確定發佈？");
                  }
                }}
                style={btn("success")}
                title="發佈：skill → Skill Registry；auto_check → 綁 alarm 事件；auto_patrol → 直接 active"
              >
                ✔ Publish
              </button>
              <button onClick={() => handleTransition("draft")} style={btn("ghost")}>
                ← 退回 Draft
              </button>
            </>
          )}
          {/* P4.4: Trigger-binding button. Routing by pipeline_kind:
              - auto_patrol  → AutoPatrolSetupModal（event / schedule / once）
              - auto_check   → AutoCheckPublishModal（綁哪個 alarm 觸發此 pipeline）
              - skill / null → 隱藏（skills are on-demand, no trigger）
              Bound state changes the label. Hidden for archived. */}
          {mode !== "session"
            && state.meta.pipelineId != null
            && state.meta.status !== "archived"
            && state.meta.pipelineKind === "auto_patrol" && (
            <button
              onClick={() => setAutoPatrolModalOpen(true)}
              style={{
                ...btn("ghost"),
                border: boundPatrol ? "1px solid #94a3b8" : "1px solid #3182ce",
                color: boundPatrol ? "#475569" : "#2c5282",
                background: boundPatrol ? "#fff" : "#ebf8ff",
                fontWeight: 600,
              }}
              title={
                boundPatrol
                  ? `編輯已綁定的 Auto-Patrol #${boundPatrol.id}`
                  : "這個 pipeline 還沒綁 trigger — 按此設定 event / schedule / 指定時間"
              }
            >
              🔔 {boundPatrol ? `編輯 Patrol 綁定 (#${boundPatrol.id})` : "設定 Patrol 觸發"}
            </button>
          )}
          {mode !== "session"
            && state.meta.pipelineId != null
            && state.meta.status !== "archived"
            && state.meta.pipelineKind === "auto_check" && (
            <button
              onClick={() => setAutoCheckModalOpen(true)}
              style={{
                ...btn("ghost"),
                border: "1px solid #3182ce",
                color: "#2c5282",
                background: "#ebf8ff",
                fontWeight: 600,
              }}
              title="設定 / 編輯 — 哪個 alarm event 來時要 fire 這條 auto-check pipeline"
            >
              🔔 設定 Auto-Check 來源
            </button>
          )}
          {/* Phase A — Run Now button: only when this pipeline has a bound
              Auto-Patrol. Synchronous fire (scope expansion + sidecar exec).
              Result toast shows fanout/triggered counts so user can
              eyeball-verify without diving into the Runs tab. */}
          {mode !== "session" && boundPatrol && (
            <button
              onClick={async () => {
                if (!boundPatrol) return;
                showToast("info", `▶️ 觸發 Patrol #${boundPatrol.id}…`);
                try {
                  const res = await fetch(`/api/admin/auto-patrols/${boundPatrol.id}/trigger`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: "{}",
                  });
                  const body = await res.json();
                  if (!res.ok) {
                    showToast("error", `觸發失敗：${body.error ?? res.statusText}`);
                    return;
                  }
                  const fanout = body.fanout_count ?? 0;
                  const triggered = body.triggered_count ?? 0;
                  showToast(
                    triggered > 0 ? "error" : "success",
                    `Patrol fired · fanout=${fanout} triggered=${triggered}（看 Runs tab）`,
                  );
                  setRightTab("runs");
                } catch (e) {
                  showToast("error", `觸發失敗：${(e as Error).message}`);
                }
              }}
              style={{ ...btn("ghost"), border: "1px solid #16a34a", color: "#15803d", background: "#f0fdf4", fontWeight: 600 }}
              title="同步觸發 patrol（fan-out + 寫 alarm/run 紀錄）"
            >
              ▶️ Run Now
            </button>
          )}
          {state.meta.status === "active" && (
            <>
              <button onClick={handleClone} style={btn("ghost")} title="複製為可編輯的 Draft">
                🧬 Clone & Edit
              </button>
              <button
                onClick={() => handleTransition("archived", "封存後不可直接恢復（需 Clone），確定？")}
                style={btn("danger")}
              >
                📦 Archive
              </button>
            </>
          )}
          {state.meta.status === "archived" && (
            <button onClick={handleClone} style={btn("ghost")}>
              🧬 Clone (新 Draft)
            </button>
          )}
        </div>
      </div>

      {/* P5: auto_check pipelines — show which alarm event_types currently
          route to this pipeline. Empty array = saved but no binding yet. */}
      {mode !== "session"
        && state.meta.pipelineId != null
        && state.meta.pipelineKind === "auto_check"
        && state.meta.status !== "archived"
        && autoCheckBindings != null && (
        <div
          style={{
            padding: "8px 18px",
            background: autoCheckBindings.length > 0 ? "#ecfeff" : "#fffbeb",
            borderBottom: "1px solid",
            borderBottomColor: autoCheckBindings.length > 0 ? "#a5f3fc" : "#fde68a",
            fontSize: 12,
            color: autoCheckBindings.length > 0 ? "#155e75" : "#92400e",
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          {autoCheckBindings.length > 0 ? (
            <>
              <span style={{ fontWeight: 600 }}>🔬 Auto-Check 已綁定</span>
              <span>當 alarm 的 trigger_event 符合以下時 fire 這條 pipeline：</span>
              {autoCheckBindings.map((b, i) => (
                <code key={i} style={{
                  padding: "2px 8px", borderRadius: 4,
                  background: "#fff", border: "1px solid #a5f3fc",
                  fontFamily: "ui-monospace, monospace", fontSize: 11,
                }}>
                  {b.event_type}
                  {b.match_filter && Object.keys(b.match_filter).length > 0 && (
                    <span style={{ marginLeft: 6, color: "#0891b2" }}>
                      + {Object.keys(b.match_filter).length} filter
                    </span>
                  )}
                </code>
              ))}
            </>
          ) : (
            <span>⚠️ 這個 Auto-Check pipeline 還沒綁任何 alarm 事件 — 按右上「設定 Auto-Check 來源」設定。</span>
          )}
        </div>
      )}

      {/* P4.4: banner reminding auto_patrol pipelines to bind a trigger.
          Shown when: kind=auto_patrol, saved, not archived, no patrol bound,
          and the bound-patrol fetch has returned (boundPatrol === undefined).
          Legacy pipelines that predate the wizard hit this banner on open. */}
      {mode !== "session"
        && state.meta.pipelineId != null
        && state.meta.pipelineKind === "auto_patrol"
        && state.meta.status !== "archived"
        && boundPatrol === undefined && (
        <div
          style={{
            padding: "8px 18px",
            background: "#fffbeb",
            borderBottom: "1px solid #fde68a",
            fontSize: 12,
            color: "#92400e",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <span>⚠️ 這個 Auto-Patrol pipeline 還沒設觸發條件。</span>
          <button
            onClick={() => setAutoPatrolModalOpen(true)}
            style={{
              padding: "3px 10px",
              borderRadius: 4,
              border: "1px solid #f59e0b",
              background: "#fff",
              color: "#b45309",
              fontSize: 11,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            立即設定 →
          </button>
        </div>
      )}

      {/* Main body: vertical PanelGroup — top(BlockLib | Canvas | Inspector) / bottom(Preview) */}
      {/* Phase 5-UX-3b session mode: AI Agent occupies a resizable right-side aside. */}
      <div style={{ flex: 1, overflow: "hidden", minHeight: 0, display: "flex", flexDirection: "row" }}>
        <div style={{ flex: 1, overflow: "hidden", minHeight: 0, minWidth: 0 }}>
        {previewCollapsed ? (
          // Collapsed: top takes everything, bottom is a thin 28px strip
          <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
            <div style={{ flex: 1, display: "flex", overflow: "hidden", minHeight: 0 }}>
              <BlockLibrary readOnly={readOnly} />
              <div data-tour-id="pb-canvas" style={{ flex: 1, overflow: "hidden" }}>
                <DagCanvas
                  blockCatalog={catalog}
                  readOnly={readOnly}
                  runStatuses={runStatuses}
                  onPortError={(msg) => showToast("error", msg)}
                  onAgentPin={(nodeId) => {
                    actions.select(nodeId);
                    const node = state.pipeline.nodes.find((n) => n.id === nodeId);
                    const label = node?.display_label ?? node?.block_id ?? nodeId;
                    window.open(
                      `/chat/new?prompt=${encodeURIComponent(`針對 ${label} (${nodeId}) 提問：`)}`,
                      "_blank",
                    );
                  }}
                />
              </div>
              {/* Phase 5-UX-5: NodeInspector / EdgeInspector moved into right
                  tabbed panel (Parameters tab). */}
            </div>
            <DataPreviewPanel
              collapsed
              onToggle={() => setPreviewCollapsed((c) => !c)}
            />
          </div>
        ) : (
          <PanelGroup orientation="vertical" id="pb-preview-split" style={{ height: "100%" }}>
            <Panel defaultSize="70%" minSize="30%">
              <div style={{ height: "100%", display: "flex", overflow: "hidden" }}>
                <BlockLibrary readOnly={readOnly} />
                <div data-tour-id="pb-canvas" style={{ flex: 1, overflow: "hidden" }}>
                  <DagCanvas
                    blockCatalog={catalog}
                    readOnly={readOnly}
                    runStatuses={runStatuses}
                    onPortError={(msg) => showToast("error", msg)}
                  />
                </div>
                {/* Phase 5-UX-5: NodeInspector / EdgeInspector moved into right
                    tabbed panel (Parameters tab). */}
              </div>
            </Panel>
            <PanelResizeHandle
              id="pb-preview-resizer"
              style={{
                height: 4,
                background: "#E2E8F0",
                cursor: "row-resize",
                flexShrink: 0,
              }}
            >
              <div
                data-testid="preview-resize-handle"
                style={{ height: "100%", width: "100%" }}
              />
            </PanelResizeHandle>
            <Panel defaultSize="30%" minSize="15%" maxSize="70%">
              <DataPreviewPanel
                collapsed={false}
                onToggle={() => setPreviewCollapsed((c) => !c)}
                onColumnClick={(col) => {
                  if (state.focusedColumnTarget && selectedNode) {
                    actions.setParam(selectedNode.id, state.focusedColumnTarget, col);
                    showToast("success", `已填入 ${state.focusedColumnTarget} = ${col}`);
                  }
                }}
              />
            </Panel>
          </PanelGroup>
        )}
        </div>
        {/* Phase 5-UX-5: right tabbed panel — Agent | Parameters | Runs.
            Always present in session + edit + new modes. */}
        <RightTabbedPanel
          blockCatalog={catalog}
          readOnly={readOnly}
          runResult={runResult}
          pipelineId={state.meta.pipelineId ?? null}
          tab={rightTab}
          setRightTab={setRightTab}
          onAskAgent={(nodeId) => {
            // Phase 5-UX-5: set focus + switch to Agent tab.
            setFocusedNodeId(nodeId);
            setRightTab("agent");
          }}
          agentPanel={
            agentTabContent ?? (
              // Phase E3: Builder context now uses the SAME AIAgentPanel as
              // /chat/[id] — one agent panel everywhere. mode="session" hides
              // the inline pb_pipeline result card (BuilderLayout's canvas IS
              // the result); agentMode="builder" tells the orchestrator to
              // skip "要建嗎?" confirmations because the user is already on
              // a canvas. Glass Box ops stream live via onGlassOp which calls
              // applyGlassOpToCanvas (shared with LiveCanvasOverlay).
              <AIAgentPanel
                mode="session"
                agentMode="builder"
                sessionId={sessionId ?? `pb-${state.meta.pipelineId ?? "new"}`}
                // Phase 11 v6 — when launched from a Skill embed flow, the
                // user's NL instruction comes in via the URL/sessionStorage
                // ctx. AIAgentPanel auto-sends `initialPrompt` once on mount
                // (see initialPromptFiredRef at L640) so the user doesn't
                // re-type it inside the agent panel.
                initialPrompt={initialPrompt ?? undefined}
                // Inject `_kind` into the snapshot so the orchestrator's
                // builder section knows whether this is auto_patrol /
                // auto_check / skill — drives confirm_pipeline_intent's
                // input.source classification (auto_check inputs come from
                // alarm payload, not user_input).
                //
                // Phase 11 v6 — when launched from a Skill embed flow,
                // override _kind to "skill_step". This signals to the
                // orchestrator: (a) skip confirm_pipeline_intent gate
                // (user already pressed Build on the Skill page), and
                // (b) tell graph_build to enforce block_step_check as the
                // terminator (NOT block_chart / block_alert).
                pipelineSnapshot={(() => {
                  const skillCtx = (typeof window !== "undefined")
                    ? (() => {
                        try {
                          const raw = sessionStorage.getItem("pb:skill_embed_ctx");
                          return raw ? JSON.parse(raw) as { skill_slug?: string } : null;
                        } catch { return null; }
                      })()
                    : null;
                  const kind = skillCtx?.skill_slug
                    ? "skill_step"
                    : (state.meta.pipelineKind ?? null);
                  return { ...state.pipeline, _kind: kind };
                })()}
                onGlassOp={(ev) => applyGlassOpToCanvas(ev, actions, catalog)}
                // Phase 10-D: graph_build's layout_node lays out positions
                // server-side and ships them in the final pipeline_json. Apply
                // those over the live add_node positions so the canvas ends
                // tidy (source on left, charts fanned out on right).
                onGlassDone={(ev) => {
                  const pj = ev.pipeline_json as
                    | { nodes?: Array<{ id: string; position?: { x: number; y: number } }> }
                    | null
                    | undefined;
                  if (!pj?.nodes) return;
                  for (const n of pj.nodes) {
                    if (n.position && typeof n.position.x === "number" && typeof n.position.y === "number") {
                      actions.moveNode(n.id, { x: n.position.x, y: n.position.y });
                    }
                  }
                }}
                contextEquipment={null}
                focusedNodeId={focusedNodeId}
                focusedNodeLabel={(() => {
                  if (!focusedNodeId) return null;
                  const node = state.pipeline.nodes.find((n) => n.id === focusedNodeId);
                  return node?.display_label ?? node?.block_id ?? focusedNodeId;
                })()}
                onClearFocus={() => setFocusedNodeId(null)}
              />
            )
          }
        />
      </div>

      {/* Validation drawer */}
      <ValidationDrawer
        open={validationOpen}
        errors={validationErrors}
        onClose={() => setValidationOpen(false)}
      />

      {/* UX Fix Pack: Pipeline Info modal (name + description) */}
      <PipelineInfoModal
        open={infoModalOpen}
        onClose={() => setInfoModalOpen(false)}
        readOnly={readOnly}
      />

      {/* PR-C: Publish Review Modal (skill kind) */}
      <PublishReviewModal
        open={publishModalOpen}
        pipelineId={state.meta.pipelineId}
        onClose={() => setPublishModalOpen(false)}
        onPublished={(slug) => {
          showToast("success", `已發佈為 Skill: ${slug}`);
          // Reload pipeline to pick up new status=active
          if (state.meta.pipelineId != null) {
            getPipeline(state.meta.pipelineId).then((rec) => actions.init(rec)).catch(() => {});
          }
        }}
      />

      {/* Phase 5-UX-7: Auto-Check Publish Modal (auto_check kind) */}
      {state.meta.pipelineId != null && (
        <AutoCheckPublishModal
          open={autoCheckModalOpen}
          onClose={() => setAutoCheckModalOpen(false)}
          pipelineId={state.meta.pipelineId}
          pipelineName={state.pipeline.name}
          pipelineJson={state.pipeline}
          pipelineStatus={state.meta.status ?? null}
          onPublished={(eventTypes) => {
            setAutoCheckModalOpen(false);
            showToast("success", `已綁 ${eventTypes.length} 個 event_type + 發佈`);
            if (state.meta.pipelineId != null) {
              getPipeline(state.meta.pipelineId).then((rec) => actions.init(rec)).catch(() => {});
            }
          }}
        />
      )}

      {/* Option A Phase β: Auto-Patrol setup modal */}
      {state.meta.pipelineId != null && (
        <AutoPatrolSetupModal
          open={autoPatrolModalOpen}
          pipelineId={state.meta.pipelineId}
          pipelineName={state.pipeline.name}
          existingPatrol={boundPatrol ?? null}
          onClose={() => setAutoPatrolModalOpen(false)}
          onCreated={(patrolId) => {
            setAutoPatrolModalOpen(false);
            showToast(
              "success",
              boundPatrol ? `已更新 Auto-Patrol #${patrolId}` : `已建立 Auto-Patrol #${patrolId}`,
            );
            // P4.4: refetch so the button relabels from "設定" → "編輯".
            void fetchBoundPatrol();
          }}
        />
      )}

      {/* Phase 4-B0: pipeline inputs editor modal */}
      <PipelineInputsPanel
        open={inputsPanelOpen}
        onClose={() => setInputsPanelOpen(false)}
      />

      {/* Phase 4-B0: Run dialog — prompts for required inputs */}
      <PipelineRunDialog
        open={runDialogOpen}
        inputs={state.pipeline.inputs ?? []}
        onCancel={() => setRunDialogOpen(false)}
        onSubmit={(values) => {
          setRunDialogOpen(false);
          void executeWithInputs(values);
        }}
      />

      {/* Pipeline Results (alert + multi-chart sequence) */}
      <PipelineResultsPanel
        open={resultsPanelOpen}
        onClose={() => setResultsPanelOpen(false)}
        summary={runResult?.result_summary ?? null}
        nodeResults={runResult?.node_results ?? {}}
      />

      {/* Toast */}
      {toast && (
        <div
          style={{
            position: "fixed",
            bottom: 24,
            left: "50%",
            transform: "translateX(-50%)",
            background:
              toast.kind === "success" ? "#f6ffed" : toast.kind === "error" ? "#fff1f0" : "#e6f7ff",
            color:
              toast.kind === "success" ? "#389e0d" : toast.kind === "error" ? "#cf1322" : "#096dd9",
            border: `1px solid ${
              toast.kind === "success" ? "#b7eb8f" : toast.kind === "error" ? "#ffa39e" : "#91d5ff"
            }`,
            padding: "8px 18px",
            borderRadius: 4,
            fontSize: 13,
            zIndex: 2000,
            boxShadow: "0 2px 6px rgba(0,0,0,0.1)",
          }}
        >
          {toast.text}
        </div>
      )}

      {/* Ignore selectedNode — only consumed in Inspector */}
      <span style={{ display: "none" }}>{selectedNode?.id ?? ""}</span>
    </div>
  );
}

function StatusBarItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 2 }}>
      <span style={{ fontSize: 9, fontWeight: 600, letterSpacing: "0.08em", color: "#94A3B8" }}>
        {label}
      </span>
      <span>{children}</span>
    </div>
  );
}

function btn(variant: "primary" | "ghost" | "success" | "danger", disabled = false): React.CSSProperties {
  const base: React.CSSProperties = {
    padding: "4px 12px",
    fontSize: 12,
    borderRadius: 3,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
    border: "1px solid transparent",
    fontWeight: 500,
    letterSpacing: "0.01em",
  };
  switch (variant) {
    case "primary":
      return { ...base, background: "#4F46E5", color: "#fff", borderColor: "#4F46E5" };
    case "success":
      return { ...base, background: "#16A34A", color: "#fff", borderColor: "#16A34A" };
    case "danger":
      return { ...base, background: "#FEF2F2", color: "#B91C1C", borderColor: "#FCA5A5" };
    case "ghost":
    default:
      return { ...base, background: "#fff", color: "#475569", borderColor: "#CBD5E1" };
  }
}
