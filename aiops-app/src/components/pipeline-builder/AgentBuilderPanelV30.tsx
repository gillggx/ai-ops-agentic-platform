"use client";

import { useCallback, useRef, useState } from "react";
import type { BlockSpec } from "@/lib/pipeline-builder/types";
import { useBuilder } from "@/context/pipeline-builder/BuilderContext";
import GoalPlanCard, { type GoalPhase } from "./v30/GoalPlanCard";
import PhaseTimeline, { type PhaseRuntime, type PhaseStatus } from "./v30/PhaseTimeline";
import HandoverModal, { type HandoverChoice } from "./v30/HandoverModal";

interface Props {
  blockCatalog: BlockSpec[];
  basePipelineId?: number | null;
}

interface ChatLine {
  id: number;
  role: "user" | "agent" | "error" | "info";
  text: string;
}

interface BuildState {
  sessionId: string | null;
  planSummary: string;
  phases: GoalPhase[];
  phaseRuntime: Record<string, PhaseRuntime>;
  goalConfirmed: "pending" | "confirmed" | "cancelled" | "none";
  handover: {
    failedPhaseId: string;
    reason: string;
    triedSummary?: string[];
    missingCapabilities?: string[];
  } | null;
  buildStatus:
    | "idle"
    | "planning"
    | "awaiting_confirm"
    | "executing"
    | "handover"
    | "done"
    | "failed";
  doneMessage?: string;
}

const initialBuildState: BuildState = {
  sessionId: null,
  planSummary: "",
  phases: [],
  phaseRuntime: {},
  goalConfirmed: "none",
  handover: null,
  buildStatus: "idle",
};

let _seq = 0;
const nextId = () => ++_seq;

/**
 * v30 Pipeline Builder Panel — Goal-Oriented ReAct UI.
 *
 * Replaces v27 AgentBuilderPanel for users who opt into v30. Always sends
 * v30Mode: true in /api/agent/build payload.
 *
 * SSE events handled:
 *   goal_plan_proposed / goal_plan_confirmed / goal_plan_rejected
 *   phase_started / phase_round / phase_action / phase_observation
 *   phase_completed / phase_revise_started / phase_revise_retry / phase_failed
 *   handover_pending / handover_chosen
 *   build_finalized / done / error
 */
export default function AgentBuilderPanelV30({ blockCatalog, basePipelineId }: Props) {
  const { actions } = useBuilder();
  const [input, setInput] = useState("");
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [build, setBuild] = useState<BuildState>(initialBuildState);
  const buildRef = useRef<BuildState>(initialBuildState);
  const runningRef = useRef(false);

  // sync ref with state for SSE handlers (state updates are async)
  buildRef.current = build;

  // Apply backend pipeline snapshot to canvas (best-effort).
  const applyCanvasSnapshot = useCallback(
    (snap: unknown) => {
      if (!snap || typeof snap !== "object") return;
      const s = snap as { nodes?: unknown[]; edges?: unknown[] };
      if (!Array.isArray(s.nodes)) return;
      try {
        actions.setNodesAndEdges(
          s.nodes as never,
          (Array.isArray(s.edges) ? s.edges : []) as never,
        );
      } catch (e) {
        // best-effort; canvas might not be ready
        // eslint-disable-next-line no-console
        console.warn("v30 applyCanvasSnapshot failed:", e);
      }
    },
    [actions],
  );

  const log = (role: ChatLine["role"], text: string) =>
    setLines((p) => [...p, { id: nextId(), role, text }]);

  // ── SSE consumer ─────────────────────────────────────────────────────
  const consumeStream = useCallback(
    async (streamRes: Response) => {
      if (!streamRes.ok || !streamRes.body) {
        const errText = await streamRes.text().catch(() => "");
        throw new Error(`stream failed (${streamRes.status}): ${errText.slice(0, 160)}`);
      }
      const reader = streamRes.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let frameEnd: number;
        // eslint-disable-next-line no-cond-assign
        while ((frameEnd = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, frameEnd);
          buffer = buffer.slice(frameEnd + 2);
          if (!frame.trim()) continue;
          let evType = "message";
          const dataLines: string[] = [];
          for (const ln of frame.split("\n")) {
            if (ln.startsWith("event:")) evType = ln.slice(6).trim();
            else if (ln.startsWith("data:")) dataLines.push(ln.slice(5).trim());
          }
          let data: Record<string, unknown> = {};
          try {
            data = dataLines.length ? JSON.parse(dataLines.join("\n")) : {};
          } catch {
            data = { _raw: dataLines.join("\n") };
          }
          handleEvent(evType, data);
        }
      }
    },
    [],
  );

  // ── Event dispatcher ─────────────────────────────────────────────────
  const handleEvent = useCallback(
    (evType: string, data: Record<string, unknown>) => {
      const sid = (data.session_id as string) || buildRef.current.sessionId;

      if (evType === "goal_plan_proposed") {
        const phases = (data.phases as GoalPhase[]) || [];
        setBuild((b) => ({
          ...b,
          sessionId: sid,
          planSummary: (data.plan_summary as string) || "",
          phases,
          phaseRuntime: Object.fromEntries(phases.map((p) => [p.id, { status: "pending" as PhaseStatus }])),
          goalConfirmed: "pending",
          buildStatus: "awaiting_confirm",
        }));
        log("agent", `提出 ${phases.length} 個 phases，請確認`);
      } else if (evType === "goal_plan_confirmed") {
        setBuild((b) => ({ ...b, goalConfirmed: "confirmed", buildStatus: "executing" }));
        log("info", "Plan 已確認，agent 開始建構");
      } else if (evType === "goal_plan_rejected" || evType === "goal_plan_refused") {
        setBuild((b) => ({ ...b, goalConfirmed: "cancelled", buildStatus: "failed" }));
        log("error", "Plan 被拒絕 / agent 看不懂需求");
      } else if (evType === "phase_started") {
        const pid = data.phase_id as string;
        setBuild((b) => ({
          ...b,
          phaseRuntime: {
            ...b.phaseRuntime,
            [pid]: { ...b.phaseRuntime[pid], status: "in_progress" },
          },
        }));
      } else if (evType === "phase_round") {
        const pid = data.phase_id as string;
        const round = data.round as number;
        const max = data.max as number;
        setBuild((b) => ({
          ...b,
          phaseRuntime: {
            ...b.phaseRuntime,
            [pid]: { ...b.phaseRuntime[pid], status: "in_progress", round, maxRound: max },
          },
        }));
      } else if (evType === "phase_action") {
        const pid = data.phase_id as string;
        const tool = data.tool as string;
        const resultSummary = data.result_summary as string | undefined;
        // Update timeline
        setBuild((b) => ({
          ...b,
          phaseRuntime: {
            ...b.phaseRuntime,
            [pid]: {
              ...b.phaseRuntime[pid],
              status: "in_progress",
              lastAction: tool,
              lastActionResult: resultSummary,
            },
          },
        }));
        // Update canvas if pipeline_snapshot present
        applyCanvasSnapshot(data.pipeline_snapshot);
      } else if (evType === "phase_observation") {
        // optional: silent
      } else if (evType === "phase_completed") {
        const pid = data.phase_id as string;
        const rationale = (data.rationale as string) || "";
        setBuild((b) => ({
          ...b,
          phaseRuntime: {
            ...b.phaseRuntime,
            [pid]: { ...b.phaseRuntime[pid], status: "completed", rationale },
          },
        }));
        log("agent", `Phase ${pid} 完成 — ${rationale.slice(0, 80)}`);
      } else if (evType === "phase_revise_started") {
        const pid = data.phase_id as string;
        const reason = (data.reason as string) || "";
        setBuild((b) => ({
          ...b,
          phaseRuntime: {
            ...b.phaseRuntime,
            [pid]: { ...b.phaseRuntime[pid], status: "paused", failReason: `revising: ${reason}` },
          },
        }));
        log("info", `Phase ${pid} 卡住，agent 自我反思中 (${reason})`);
      } else if (evType === "phase_revise_retry") {
        const pid = data.phase_id as string;
        const alt = (data.alternative as string) || "";
        setBuild((b) => ({
          ...b,
          phaseRuntime: {
            ...b.phaseRuntime,
            [pid]: { ...b.phaseRuntime[pid], status: "in_progress", failReason: undefined },
          },
        }));
        log("agent", `Phase ${pid} 換策略再試: ${alt.slice(0, 80)}`);
      } else if (evType === "handover_pending") {
        const pid = data.failed_phase_id as string;
        setBuild((b) => ({
          ...b,
          phaseRuntime: {
            ...b.phaseRuntime,
            [pid]: { ...b.phaseRuntime[pid], status: "failed", failReason: data.reason as string },
          },
          handover: {
            failedPhaseId: pid,
            reason: (data.reason as string) || "",
            triedSummary: data.tried_summary as string[] | undefined,
            missingCapabilities: data.missing_capabilities as string[] | undefined,
          },
          buildStatus: "handover",
        }));
      } else if (evType === "handover_chosen") {
        setBuild((b) => ({ ...b, handover: null }));
        log("info", `已選擇: ${data.choice}`);
      } else if (evType === "build_finalized" || evType === "done") {
        const status = (data.status as string) || "unknown";
        const summary = (data.summary as string) || "";
        setBuild((b) => ({ ...b, buildStatus: status === "finished" || status === "build_partial" ? "done" : "failed", doneMessage: `${status} — ${summary}` }));
        applyCanvasSnapshot(data.pipeline_json);
        log(status === "finished" ? "agent" : "error", `Build ${status}: ${summary || "(no summary)"}`);
        runningRef.current = false;
      } else if (evType === "error") {
        log("error", (data.message as string) || "Unknown error");
        setBuild((b) => ({ ...b, buildStatus: "failed" }));
        runningRef.current = false;
      }
    },
    [actions],
  );

  // ── Submit ──────────────────────────────────────────────────────────
  const submit = async () => {
    if (runningRef.current || !input.trim()) return;
    runningRef.current = true;
    const instruction = input.trim();
    setInput("");
    log("user", instruction);
    setBuild({ ...initialBuildState, buildStatus: "planning" });

    try {
      const res = await fetch("/api/agent/build", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          instruction,
          pipelineId: basePipelineId,
          v30Mode: true,
          skillStepMode: false,
        }),
      });
      await consumeStream(res);
    } catch (ex) {
      log("error", `Build error: ${(ex as Error).message}`);
      setBuild((b) => ({ ...b, buildStatus: "failed" }));
      runningRef.current = false;
    }
  };

  // ── Confirm / cancel goal plan ──────────────────────────────────────
  const onConfirmPlan = async (phases: GoalPhase[]) => {
    if (!buildRef.current.sessionId) return;
    try {
      const res = await fetch("/api/agent/build/plan-confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          sessionId: buildRef.current.sessionId,
          confirmed: true,
          phases,
        }),
      });
      await consumeStream(res);
    } catch (ex) {
      log("error", `plan-confirm error: ${(ex as Error).message}`);
    }
  };
  const onCancelPlan = async () => {
    if (!buildRef.current.sessionId) return;
    try {
      const res = await fetch("/api/agent/build/plan-confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ sessionId: buildRef.current.sessionId, confirmed: false }),
      });
      await consumeStream(res);
    } catch (ex) {
      log("error", `plan-confirm cancel error: ${(ex as Error).message}`);
    }
  };

  // ── Handover choice ──────────────────────────────────────────────────
  const onHandoverChoose = async (choice: HandoverChoice, newGoal?: string) => {
    if (!buildRef.current.sessionId) return;
    try {
      const res = await fetch("/api/agent/build/handover", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          sessionId: buildRef.current.sessionId,
          choice,
          newGoal: newGoal || "",
        }),
      });
      await consumeStream(res);
    } catch (ex) {
      log("error", `handover error: ${(ex as Error).message}`);
    }
  };

  // ── Render ───────────────────────────────────────────────────────────
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "#fafafa",
        fontSize: 13,
      }}
    >
      <div
        style={{
          padding: "8px 12px",
          background: "#fff",
          borderBottom: "1px solid #e2e8f0",
          fontSize: 11,
          fontWeight: 700,
          color: "#475569",
          letterSpacing: 0.6,
          textTransform: "uppercase",
        }}
      >
        Agent Builder (v30 ReAct)
      </div>

      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: 12,
        }}
      >
        {/* Chat lines */}
        {lines.map((ln) => (
          <div
            key={ln.id}
            style={{
              display: "flex",
              justifyContent: ln.role === "user" ? "flex-end" : "flex-start",
              marginBottom: 8,
            }}
          >
            <div
              style={{
                maxWidth: "85%",
                padding: "7px 10px",
                borderRadius: 8,
                background:
                  ln.role === "user" ? "#eff6ff"
                  : ln.role === "error" ? "#fef2f2"
                  : ln.role === "info" ? "#f1f5f9"
                  : "#fff",
                border: `1px solid ${
                  ln.role === "user" ? "#bfdbfe"
                  : ln.role === "error" ? "#fca5a5"
                  : ln.role === "info" ? "#cbd5e1"
                  : "#e2e8f0"
                }`,
                color:
                  ln.role === "error" ? "#991b1b"
                  : "#0f172a",
                fontSize: 13,
                whiteSpace: "pre-wrap",
              }}
            >
              {ln.text}
            </div>
          </div>
        ))}

        {/* Goal Plan Card */}
        {build.phases.length > 0 && build.goalConfirmed !== "none" && (
          <GoalPlanCard
            planSummary={build.planSummary}
            phases={build.phases}
            onConfirm={onConfirmPlan}
            onCancel={onCancelPlan}
            decided={
              build.goalConfirmed === "confirmed" ? "confirmed"
              : build.goalConfirmed === "cancelled" ? "cancelled"
              : undefined
            }
          />
        )}

        {/* Phase Timeline (after confirm) */}
        {build.goalConfirmed === "confirmed" && build.phases.length > 0 && (
          <PhaseTimeline phases={build.phases} runtime={build.phaseRuntime} />
        )}

        {/* Done banner */}
        {build.doneMessage && (
          <div
            style={{
              padding: "10px 14px",
              background:
                build.buildStatus === "done" ? "#f0fdf4"
                : "#fef2f2",
              border: `1px solid ${
                build.buildStatus === "done" ? "#86efac"
                : "#fca5a5"
              }`,
              borderRadius: 8,
              marginTop: 10,
              fontSize: 13,
              fontWeight: 600,
              color:
                build.buildStatus === "done" ? "#15803d"
                : "#991b1b",
            }}
          >
            {build.doneMessage}
          </div>
        )}
      </div>

      {/* Input area */}
      <div
        style={{
          padding: 12,
          borderTop: "1px solid #e2e8f0",
          background: "#fff",
          display: "flex",
          gap: 8,
        }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="描述要建什麼 pipeline..."
          rows={2}
          disabled={runningRef.current}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          style={{
            flex: 1,
            padding: 8,
            fontSize: 13,
            border: "1px solid #cbd5e1",
            borderRadius: 5,
            fontFamily: "inherit",
            resize: "none",
          }}
        />
        <button
          type="button"
          onClick={submit}
          disabled={runningRef.current || !input.trim()}
          style={{
            padding: "0 16px",
            background: runningRef.current || !input.trim() ? "#cbd5e1" : "#2563eb",
            color: "#fff",
            border: "none",
            borderRadius: 5,
            fontSize: 13,
            fontWeight: 600,
            cursor: runningRef.current || !input.trim() ? "not-allowed" : "pointer",
          }}
        >
          {runningRef.current ? "..." : "送出"}
        </button>
      </div>

      {/* Handover Modal */}
      {build.handover && (
        <HandoverModal
          failedPhaseId={build.handover.failedPhaseId}
          reason={build.handover.reason}
          triedSummary={build.handover.triedSummary}
          missingCapabilities={build.handover.missingCapabilities}
          onChoose={onHandoverChoose}
        />
      )}
    </div>
  );
}
