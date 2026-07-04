"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import type { BlockSpec } from "@/lib/pipeline-builder/types";
import { useBuilder } from "@/context/pipeline-builder/BuilderContext";
import GoalPlanCard, { type GoalPhase } from "./v30/GoalPlanCard";
import PhaseTimeline, { type PhaseRuntime, type PhaseStatus } from "./v30/PhaseTimeline";
import HandoverModal, { type HandoverChoice } from "./v30/HandoverModal";
import { readSkillV2Ctx } from "@/components/skills-v2/SkillV2EmbedBanner";

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
  const { state: builderState, actions } = useBuilder();
  // v31.1 — previous instruction, sent with follow-ups so goal_plan can
  // resolve modification anaphora ("我後悔了，改成3張…") against the canvas.
  const priorInstructionRef = useRef<string | null>(null);
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
      // 2026-06-28 fix: capture session_id from ANY event that carries
      // one. Sidecar emits `goal_plan_proposed` WITHOUT session_id, then
      // a separate `goal_plan_confirm_required` WITH session_id (see
      // runner.py:180). Without this capture, buildRef.sessionId stays
      // empty and BOTH auto-confirm AND manual-click POST blank session_id
      // → Java 400 → SSE stream tears → HTTP/2 PROTOCOL_ERROR.
      if (data.session_id && buildRef.current.sessionId !== data.session_id) {
        setBuild((b) => ({ ...b, sessionId: data.session_id as string }));
      }

      if (evType === "goal_plan_proposed") {
        const phases = (data.phases as GoalPhase[]) || [];
        setBuild((b) => ({
          ...b,
          sessionId: sid || b.sessionId,
          planSummary: (data.plan_summary as string) || "",
          phases,
          phaseRuntime: Object.fromEntries(phases.map((p) => [p.id, { status: "pending" as PhaseStatus }])),
          goalConfirmed: "pending",
          buildStatus: "awaiting_confirm",
        }));
        log("agent", `提出 ${phases.length} 個 phases，請確認`);
        // Auto-confirm fires on goal_plan_confirm_required (below), NOT
        // here — that's the event that carries session_id.
      } else if (evType === "goal_plan_confirm_required") {
        // Skills v2 embed: 自動確認 plan once we have BOTH phases (from
        // goal_plan_proposed) AND session_id (this event). Only when ctx.mode
        // is compile/rebuild — edit mode means user wants to hand-edit, so
        // we leave the plan gate visible if Agent was somehow triggered.
        const realSid = (data.session_id as string) || sid;
        const phases = buildRef.current.phases;
        const ctx = readSkillV2Ctx();
        const isAutoMode = ctx?.mode === "compile" || ctx?.mode === "rebuild" || (ctx && !ctx.mode);
        if (isAutoMode && !autoConfirmedRef.current && realSid && phases.length > 0) {
          autoConfirmedRef.current = true;
          log("info", "Skills v2 embed: 自動確認 plan，agent 繼續建構");
          void (async () => {
            try {
              const r = await fetch("/api/agent/build/plan-confirm", {
                method: "POST",
                headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
                body: JSON.stringify({ session_id: realSid, confirmed: true, phases }),
              });
              await consumeStream(r);
            } catch (ex) {
              log("error", `auto-confirm failed: ${(ex as Error).message}`);
            }
          })();
        }
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
        const autoCompleted = Boolean(data.auto_completed);
        const ffByBlock = (data.advanced_by_block as string) || undefined;
        const ffByNode = (data.advanced_by_node as string) || undefined;
        setBuild((b) => ({
          ...b,
          phaseRuntime: {
            ...b.phaseRuntime,
            [pid]: {
              ...b.phaseRuntime[pid],
              status: "completed",
              rationale,
              autoCompleted,
              fastForwardedByBlock: ffByBlock,
              fastForwardedBy: ffByNode,
            },
          },
        }));
        log("agent", `Phase ${pid} 完成 — ${rationale.slice(0, 100)}`);
      } else if (evType === "phase_fast_forward_report") {
        // v30.1: one block covered >=2 phases at once. Show user the
        // concrete outcome per phase so they can sanity-check the cascade.
        const advancedBy = (data.advanced_by_block as string) || "(unknown)";
        const advancedByNode = (data.advanced_by_node as string) || "?";
        const completed =
          (data.phases_completed as Array<{ id: string; outcome?: string; expected?: string }>) || [];
        const ids = completed.map((c) => c.id).join(", ");
        const summary = completed
          .map((c) => `  ${c.id} (${c.expected ?? "?"}): ${c.outcome ?? ""}`)
          .join("\n");
        log(
          "agent",
          `[fast-forward] ${completed.length} phases (${ids}) 由 ${advancedByNode} [${advancedBy}] 一個 block 同時涵蓋:\n${summary}`,
        );
      } else if (evType === "phase_verifier_no_match") {
        // verifier didn't accept the mutation; LLM continues. Surface in
        // admin trace only — too noisy for chat log.
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
  const submit = useCallback(async (overrideInstruction?: string) => {
    if (runningRef.current) return;
    const instruction = (overrideInstruction ?? input).trim();
    if (!instruction) return;
    runningRef.current = true;
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
          // v31.1 — follow-up context: current canvas + previous instruction.
          // Without these, a modification message reaches goal_plan with zero
          // context and gets a too_vague refuse ("agent 看不懂需求").
          ...(builderState.pipeline.nodes.length > 0 ? {
            // Full PipelineJSON — cherry-picking nodes/edges dropped the
            // required name/version fields and crashed PipelineJSON
            // validation when the resumed build loop started (2026-07-04).
            pipelineSnapshot: builderState.pipeline,
          } : {}),
          ...(priorInstructionRef.current ? { priorInstruction: priorInstructionRef.current } : {}),
          v30Mode: true,
          skillStepMode: false,
        }),
      });
      priorInstructionRef.current = instruction;
      await consumeStream(res);
    } catch (ex) {
      log("error", `Build error: ${(ex as Error).message}`);
      setBuild((b) => ({ ...b, buildStatus: "failed" }));
      runningRef.current = false;
    }
  }, [input, basePipelineId, consumeStream, builderState.pipeline]);

  // ── Auto-fire on mount when launched from Skills v2 Editor ──────────
  // When the Editor's "用 Pipeline Builder 編譯 →" navigates here it
  // stashes the skill's NL in sessionStorage. Pick it up and kick off
  // the build automatically — user shouldn't have to retype their NL
  // into the agent input box.
  const autoFiredRef = useRef(false);
  useEffect(() => {
    if (autoFiredRef.current) return;
    const ctx = readSkillV2Ctx();
    if (!ctx?.nl?.trim()) return;
    // Only auto-fire in compile/rebuild flow. mode === "edit" means user
    // opened PB to hand-edit; don't kick off an Agent build.
    const mode = ctx.mode ?? "compile";
    if (mode === "edit") return;
    autoFiredRef.current = true;
    setTimeout(() => { void submit(ctx.nl); }, 80);
  }, [submit]);

  // ── Skills v2 auto-confirm plan ─────────────────────────────────────
  // Now handled inline inside the goal_plan_proposed SSE branch above —
  // POSTing plan-confirm there uses the freshly-received session_id and
  // avoids a useEffect race against state propagation. autoConfirmedRef
  // is declared here so the inline handler can read/set it.
  const autoConfirmedRef = useRef(false);

  // ── Confirm / cancel goal plan ──────────────────────────────────────
  const onConfirmPlan = async (phases: GoalPhase[]) => {
    const sid = buildRef.current.sessionId;
    if (!sid) {
      log("error", "Plan 無法確認：尚未取得 session_id");
      return;
    }
    try {
      const res = await fetch("/api/agent/build/plan-confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ session_id: sid, confirmed: true, phases }),
      });
      await consumeStream(res);
    } catch (ex) {
      log("error", `plan-confirm error: ${(ex as Error).message}`);
    }
  };
  const onCancelPlan = async () => {
    const sid = buildRef.current.sessionId;
    if (!sid) return;
    try {
      const res = await fetch("/api/agent/build/plan-confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ session_id: sid, confirmed: false }),
      });
      await consumeStream(res);
    } catch (ex) {
      log("error", `plan-confirm cancel error: ${(ex as Error).message}`);
    }
  };

  // ── Handover choice ──────────────────────────────────────────────────
  const onHandoverChoose = async (choice: HandoverChoice, newGoal?: string) => {
    const sid = buildRef.current.sessionId;
    if (!sid) return;
    try {
      const res = await fetch("/api/agent/build/handover", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          session_id: sid,
          choice,
          new_goal: newGoal || "",
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
            editable
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

        {/* Post-delivery feedback (observability spec §4.4) — records the
            divergence signal for the Supervisor loop; nothing fires. */}
        {build.doneMessage && build.buildStatus === "done" && build.sessionId && (
          <EpisodeFeedbackBar episodeKey={build.sessionId} />
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
          onClick={() => { void submit(); }}
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

/** Post-delivery 3-button feedback strip (符合 / 要修改 / 不是我要的).
 *  Posts to /api/agent-episodes/[key]/feedback; reject text is optional.
 *  Pure recording — the Supervisor loop consumes it offline. */
function EpisodeFeedbackBar({ episodeKey }: { episodeKey: string }) {
  const [sent, setSent] = useState<string | null>(null);
  const [pendingReject, setPendingReject] = useState(false);
  const [text, setText] = useState("");

  const submit = async (sentiment: "accept" | "edit" | "reject", note?: string) => {
    try {
      await fetch(`/api/agent-episodes/${encodeURIComponent(episodeKey)}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "delivery", sentiment, text: note ?? "" }),
      });
    } catch {
      /* recording only — never block the user on failure */
    }
    setSent(sentiment);
    setPendingReject(false);
  };

  if (sent) {
    return (
      <div style={{ marginTop: 8, fontSize: 12, color: "#64748b" }}>
        已記錄回饋（{sent === "accept" ? "符合" : sent === "edit" ? "要修改" : "不是我要的"}），謝謝。
      </div>
    );
  }
  const btn: CSSProperties = {
    padding: "5px 12px", borderRadius: 7, border: "1px solid #cbd5e1",
    background: "#fff", fontSize: 12.5, cursor: "pointer",
  };
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span style={{ fontSize: 12, color: "#64748b" }}>這個結果:</span>
        <button style={{ ...btn, borderColor: "#86efac", color: "#15803d" }}
                onClick={() => submit("accept")}>符合</button>
        <button style={{ ...btn, borderColor: "#fde68a", color: "#b45309" }}
                onClick={() => submit("edit")}>要修改</button>
        <button style={{ ...btn, borderColor: "#fca5a5", color: "#b91c1c" }}
                onClick={() => setPendingReject(true)}>不是我要的</button>
      </div>
      {pendingReject && (
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="（選填）哪裡不對？"
            style={{ flex: 1, padding: "5px 10px", borderRadius: 7,
                     border: "1px solid #cbd5e1", fontSize: 12.5 }}
          />
          <button style={{ ...btn, borderColor: "#fca5a5", color: "#b91c1c" }}
                  onClick={() => submit("reject", text)}>送出</button>
        </div>
      )}
    </div>
  );
}
