"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import type { AIOpsReportContract } from "aiops-contract";
import { isValidContract } from "aiops-contract";
import { consumeSSE } from "@/lib/sse";
import { RuleProposalCard } from "@/components/copilot/RuleProposalCard";
import { BulletConfirmCard, type IntentBullet } from "@/components/chat/BulletConfirmCard";
import {
  DesignIntentCard,
  type DesignIntentChoice,
  type DesignIntentData,
} from "@/components/copilot/DesignIntentCard";
import { PlanCard, type PlanData, type PhaseStatus, type PhaseEntry } from "@/components/chat/PlanCard";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StageState {
  stage: number;
  label: string;
  status: "running" | "complete" | "error";
}

type LogLevel = "info" | "tool" | "thinking" | "memory" | "error" | "hitl" | "token";

interface LogEntry {
  id: number;
  icon: string;
  text: string;
  level: LogLevel;
  ts: string;
}

interface ChatMessage {
  id: number;
  role: "user" | "agent" | "design_intent" | "plan";
  content: string;
  /** For role === "design_intent" — the structured intent card to render. */
  designIntent?: DesignIntentData;
  /** For role === "design_intent" — the user prompt that triggered this card,
   *  needed to compose the [intent_confirmed:<id>] follow-up message. */
  designIntentPrompt?: string;
  /** For role === "plan" — v30 builder goal plan with live phase status. */
  plan?: PlanData;
  /** Optional render card embedded in agent message. */
  card?:
    | {
        type: "rule_proposal";
        rule_draft: Parameters<typeof RuleProposalCard>[0]["ruleDraft"];
        preview: Parameters<typeof RuleProposalCard>[0]["preview"];
      }
    | {
        type: "intent_confirm";
        chat_session_id: string;
        bullets: IntentBullet[];
        too_vague_reason?: string;
        resolved?: "confirmed" | "refused" | "error";
        resolved_summary?: string;
      };
}

interface HitlRequest {
  approval_token: string;
  tool: string;
  input?: Record<string, unknown>;
}

interface Props {
  onContract: (contract: AIOpsReportContract) => void;
  triggerMessage?: string | null;
  onTriggerConsumed?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let _seq = 0;
const nextId = () => ++_seq;

function makeLog(icon: string, text: string, level: LogLevel): LogEntry {
  return {
    id: nextId(), icon, text, level,
    ts: new Date().toLocaleTimeString("zh-TW", { hour12: false }),
  };
}

const LEVEL_COLOR: Record<LogLevel, string> = {
  info:     "#60a5fa",
  tool:     "#fbbf24",
  thinking: "#94a3b8",
  memory:   "#a78bfa",
  error:    "#fc8181",
  hitl:     "#f97316",
  token:    "#64748b",
};

// ---------------------------------------------------------------------------
// ChatPanel
// ---------------------------------------------------------------------------

export function ChatPanel({ onContract, triggerMessage, onTriggerConsumed }: Props) {
  const [input, setInput]           = useState("");
  const [loading, setLoading]       = useState(false);
  const [stages, setStages]         = useState<StageState[]>([]);
  const [logs, setLogs]             = useState<LogEntry[]>([]);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [hitl, setHitl]             = useState<HitlRequest | null>(null);
  const [tokenIn, setTokenIn]       = useState(0);
  const [tokenOut, setTokenOut]     = useState(0);
  const [activeTab, setActiveTab]   = useState<"chat" | "console">("chat");

  const sessionIdRef = useRef<string | null>(null);
  const logsEndRef   = useRef<HTMLDivElement>(null);
  const chatEndRef   = useRef<HTMLDivElement>(null);
  // Track the most recent user-typed prompt so design_intent_confirm cards
  // can compose the [intent_confirmed:<card_id>] follow-up message.
  const lastUserPromptRef = useRef<string>("");
  // v30.17i — id of the active plan message in chatHistory so subsequent
  // phase_update events can mutate the same card instead of stacking
  // duplicate plan renders. Reset to null on each new user message so a
  // new build run gets its own plan card.
  const activePlanMsgIdRef = useRef<number | null>(null);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory]);

  // Auto-send when parent triggers a message (from SuggestedActions)
  useEffect(() => {
    if (triggerMessage) {
      sendMessage(triggerMessage);
      onTriggerConsumed?.();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triggerMessage]);

  const addLog = useCallback((entry: LogEntry) => {
    setLogs((prev) => [...prev.slice(-200), entry]);
  }, []);

  const resolveHitl = useCallback(async (token: string, approved: boolean) => {
    setHitl(null);
    addLog(makeLog(approved ? "✅" : "❌", `HITL | ${approved ? "批准" : "拒絕"}: token=${token}`, "hitl"));
    try {
      await fetch(`/api/agent/approve/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved }),
      });
    } catch (e) {
      addLog(makeLog("⚠️", `HITL 回報失敗: ${e instanceof Error ? e.message : e}`, "error"));
    }
  }, [addLog]);

  const sendMessage = useCallback(async (
    message: string,
    clientContext?: Record<string, unknown>,
  ) => {
    if (!message.trim() || loading) return;

    setLoading(true);
    setStages([]);
    setLogs([]);
    setHitl(null);
    setTokenIn(0);
    setTokenOut(0);
    setInput("");
    setActiveTab("chat");

    // Capture user prompt for design_intent_confirm follow-up composition.
    // Don't capture the [intent_confirmed:...] follow-up itself or we'd
    // overwrite the original prompt that the card relates to.
    if (!message.startsWith("[intent_confirmed:")) {
      lastUserPromptRef.current = message;
      // v30.17i — fresh build run gets a fresh plan card
      activePlanMsgIdRef.current = null;
    }

    // Add user message to chat history
    setChatHistory((prev) => [...prev, { id: nextId(), role: "user", content: message }]);

    try {
      const res = await fetch("/api/agent/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          session_id: sessionIdRef.current,
          ...(clientContext ? { client_context: clientContext } : {}),
        }),
      });

      if (!res.ok) {
        addLog(makeLog("❌", `Agent error: ${res.status}`, "error"));
        return;
      }

      await consumeSSE(res, (ev) => {
        const type = ev.type as string;

        switch (type) {
          case "stage_update": {
            const stage  = ev.stage as number;
            const status = ev.status as "running" | "complete" | "error";
            const label  = (ev.label as string) ?? `Stage ${stage}`;
            setStages((prev) => {
              const idx = prev.findIndex((s) => s.stage === stage);
              if (idx >= 0) {
                const u = [...prev]; u[idx] = { stage, label, status }; return u;
              }
              return [...prev, { stage, label, status }];
            });
            break;
          }

          case "context_load": {
            const rag   = ev.rag_count    ?? 0;
            const turns = ev.history_turns ?? 0;
            const pref  = ev.pref_summary && ev.pref_summary !== "(無)" ? ev.pref_summary : "未設定";
            addLog(makeLog("📦", `CONTEXT | RAG: ${rag} 條 | 歷史: ${turns} 輪 | 偏好: ${pref}`, "info"));
            break;
          }

          case "thinking":
            addLog(makeLog("💭", `THINKING | ${((ev.text as string) ?? "").slice(0, 200)}`, "thinking"));
            break;

          case "llm_usage": {
            const inTok  = (ev.input_tokens  as number) ?? 0;
            const outTok = (ev.output_tokens as number) ?? 0;
            setTokenIn((p)  => p + inTok);
            setTokenOut((p) => p + outTok);
            addLog(makeLog("🔢", `LLM #${ev.iteration ?? "?"} | in=${inTok} out=${outTok}`, "token"));
            break;
          }

          case "tool_start": {
            const inputStr = JSON.stringify(ev.input ?? {});
            const toolName = (ev.tool ?? "") as string;
            const [icon, prefix] = toolName === "save_memory"   ? ["💾", "SAVE MEMORY"]
                                 : toolName === "search_memory"  ? ["🔍", "GET MEMORY"]
                                 : toolName === "delete_memory"  ? ["🗑️", "DELETE MEMORY"]
                                 : ["🔧", "TOOL"];
            addLog(makeLog(icon,
              `${prefix} #${ev.iteration ?? "?"} → ${toolName}(${inputStr.slice(0, 80)}${inputStr.length > 80 ? "…" : ""})`,
              "tool"
            ));
            break;
          }

          case "tool_done": {
            const toolName = (ev.tool ?? "") as string;
            const [icon, prefix] = toolName === "save_memory"   ? ["💾", "SAVE MEMORY ✓"]
                                 : toolName === "search_memory"  ? ["🔍", "GET MEMORY ✓"]
                                 : toolName === "delete_memory"  ? ["🗑️", "DELETE MEMORY ✓"]
                                 : ["✅", "DONE"];
            addLog(makeLog(icon, `${prefix} → ${toolName} | ${(ev.result_summary ?? "") as string}`, "tool"));

            // Phase 9 — propose_personal_rule emits a rule_proposal render
            // card; surface it as an inline confirmation card in chat.
            const renderCard = ev.render_card as { type?: string; rule_draft?: unknown; preview?: unknown } | undefined;
            if (renderCard?.type === "rule_proposal" && renderCard.rule_draft) {
              setChatHistory((prev) => [...prev, {
                id: nextId(),
                role: "agent",
                content: "",
                card: {
                  type: "rule_proposal",
                  rule_draft: renderCard.rule_draft as Parameters<typeof RuleProposalCard>[0]["ruleDraft"],
                  preview: (renderCard.preview ?? {}) as Parameters<typeof RuleProposalCard>[0]["preview"],
                },
              }]);
            }
            break;
          }

          case "memory_write": {
            const content = (ev.fix_rule ?? ev.content ?? "") as string;
            const src = (ev.memory_type ?? ev.source ?? "") as string;
            const [icon, label] = src === "trap"             ? ["⚠️", "Trap Memory"]
                                : src === "diagnosis"        ? ["🧠", "記憶寫入 · 診斷"]
                                : src === "preference"       ? ["⭐", "記憶寫入 · 偏好"]
                                : src === "hitl_preference"  ? ["⭐", "記憶寫入 · HITL偏好"]
                                : src === "api_pattern"      ? ["📚", "記憶寫入 · API模式"]
                                :                             ["💾", "記憶寫入"];
            addLog(makeLog(icon, `[${label}] ${content.slice(0, 120)}`, "memory"));
            break;
          }

          case "reflection_running":
            addLog(makeLog("🔍", "Self-Critique 驗證數值來源中…", "info"));
            break;

          case "reflection_pass":
            addLog(makeLog("✅", "Self-Critique 通過 — 所有數值來源已確認", "info"));
            break;

          case "reflection_amendment": {
            const count = (ev.issue_count as number) ?? (ev.issues as unknown[])?.length ?? 0;
            const amended = (ev.amended_text as string) ?? "";
            addLog(makeLog("🚨", `Self-Critique 發現 ${count} 處幻覺 — 已修訂回覆`, "error"));
            if (amended) {
              setChatHistory((prev) => {
                if (prev.length === 0) return prev;
                const last = prev[prev.length - 1];
                if (last.role !== "agent") return prev;
                return [...prev.slice(0, -1), { ...last, content: amended }];
              });
            }
            break;
          }

          case "approval_required": {
            const req: HitlRequest = {
              approval_token: ev.approval_token as string,
              tool:           ev.tool as string,
              input:          ev.input as Record<string, unknown> | undefined,
            };
            addLog(makeLog("⚠️", `HITL | 等待批准: ${req.tool}（token: ${req.approval_token}）`, "hitl"));
            setHitl(req);
            break;
          }

          case "synthesis": {
            const text = (ev.text as string) ?? "";
            // Extract the plain text part (strip <contract> block) for chat display
            const displayText = text.replace(/<contract>[\s\S]*?<\/contract>/g, "").trim();
            if (isValidContract(ev.contract)) {
              onContract(ev.contract as AIOpsReportContract);
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "agent",
                content: displayText || (ev.contract as { summary?: string }).summary || "",
              }]);
            } else if (displayText) {
              setChatHistory((prev) => [...prev, { id: nextId(), role: "agent", content: displayText }]);
            }
            addLog(makeLog("💬", `SYNTHESIS 完成 (${text.length} chars)`, "info"));
            break;
          }

          case "done":
            sessionIdRef.current = ev.session_id as string;
            break;

          case "error":
            addLog(makeLog("❌", (ev.message as string) ?? "Agent 發生錯誤", "error"));
            break;

          // --- Agent planning ---
          case "plan": {
            const planText = (ev.text as string) ?? "";
            addLog(makeLog("🧭",
              `PLAN #${ev.iteration ?? "?"}\n${planText}`,
              "info"));
            break;
          }

          // --- Pipeline Builder Glass Box mode ---
          // When the agent decides to build a pipeline (e.g. asking for a
          // trend chart), it streams pb_glass_* events instead of a final
          // synthesis. Surface them so the chat panel shows activity + a
          // final answer instead of looking dead.
          case "pb_glass_start":
            addLog(makeLog("🧱",
              `PIPELINE BUILDER | 開始建構：${(ev.goal as string) ?? ""}`,
              "info"));
            break;

          case "pb_glass_chat": {
            const content = (ev.content as string) ?? "";

            // v30.17i — goal_plan_proposed carries structured `plan` data
            // alongside text. Render as a PlanCard once, then later
            // phase_completed / phase_revise_started events arrive (also
            // pb_glass_chat) with `phase_update` payload that mutates the
            // same card's phase status. AIAgentPanel ignores these extra
            // fields and renders the text bubble — no regression.
            const planPayload = ev.plan as PlanData | undefined;
            const planConfirmed = ev.plan_confirmed as { auto: boolean; n_phases: number } | undefined;
            const phaseUpdate = ev.phase_update as {
              phase_id: string;
              status: PhaseStatus;
              rationale?: string;
              reason?: string;
            } | undefined;

            if (planPayload && Array.isArray(planPayload.phases)) {
              const phases: PhaseEntry[] = planPayload.phases.map((p) => ({
                id: p.id,
                goal: p.goal ?? "",
                expected: p.expected ?? "?",
                status: "pending",
                auto_injected: !!p.auto_injected,
              }));
              const planData: PlanData = {
                summary: planPayload.summary ?? "",
                phases,
                confirmed: false,
              };
              const newId = nextId();
              activePlanMsgIdRef.current = newId;
              setChatHistory((prev) => [...prev, {
                id: newId, role: "plan", content: "",
                plan: planData,
              }]);
              break;
            }

            if (planConfirmed && activePlanMsgIdRef.current != null) {
              const targetId = activePlanMsgIdRef.current;
              setChatHistory((prev) => prev.map((m) => {
                if (m.id !== targetId || !m.plan) return m;
                // Flip confirmed flag + mark first phase as running
                const phases = m.plan.phases.map((p, idx) => ({
                  ...p,
                  status: idx === 0 ? ("running" as PhaseStatus) : p.status,
                }));
                return { ...m, plan: { ...m.plan, phases, confirmed: true } };
              }));
              break;  // suppress the text bubble for confirmation
            }

            if (phaseUpdate && activePlanMsgIdRef.current != null) {
              const targetId = activePlanMsgIdRef.current;
              setChatHistory((prev) => prev.map((m) => {
                if (m.id !== targetId || !m.plan) return m;
                let advanceNext = false;
                const phases = m.plan.phases.map((p) => {
                  if (p.id !== phaseUpdate.phase_id) return p;
                  if (phaseUpdate.status === "completed") advanceNext = true;
                  return {
                    ...p,
                    status: phaseUpdate.status,
                    rationale: phaseUpdate.rationale,
                    reason: phaseUpdate.reason,
                  };
                });
                // When a phase completes, mark the next pending phase as running
                if (advanceNext) {
                  const nextIdx = phases.findIndex((p) => p.status === "pending");
                  if (nextIdx >= 0) {
                    phases[nextIdx] = { ...phases[nextIdx], status: "running" };
                  }
                }
                return { ...m, plan: { ...m.plan, phases } };
              }));
              break;  // suppress the per-phase text bubble too
            }

            // Fallback — generic chat content (no structured payload)
            if (content) {
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "agent",
                content,
              }]);
            }
            break;
          }

          case "pb_glass_op": {
            const op = (ev.op as string) ?? "?";
            const args = (ev.args as Record<string, unknown>) ?? {};
            // v30.17h — args carries underscore-prefixed phase metadata
            // (_phase_id / _round / _args_summary) alongside the raw tool
            // args. Show phase context inline so the chat console tracks
            // which phase each op belongs to.
            const phaseId = args._phase_id as string | undefined;
            const roundNum = args._round as number | undefined;
            const summary = args._args_summary as string | undefined;
            const phasePrefix = phaseId && roundNum ? `[${phaseId} r${roundNum}] ` : "";
            // Pick a compact body: prefer the human summary when present,
            // otherwise stringify the args minus underscore metadata.
            let body = summary ?? "";
            if (!body) {
              const cleanArgs = Object.fromEntries(
                Object.entries(args).filter(([k]) => !k.startsWith("_")),
              );
              body = JSON.stringify(cleanArgs).slice(0, 80);
            }
            addLog(makeLog("⚙️",
              `PIPELINE OP | ${phasePrefix}${op} ${body}`,
              "tool"));
            break;
          }

          case "pb_glass_done": {
            const pid = ev.pipeline_id ?? ev.saved_pipeline_id;
            const msg = pid
              ? `Pipeline 建構完成（id=${pid}）— 請到 Pipeline Builder 查看結果`
              : "Pipeline 建構結束";
            setChatHistory((prev) => [...prev, {
              id: nextId(), role: "agent", content: msg,
            }]);
            break;
          }

          // intent_completeness gate (chat orchestrator_v2) — emits a
          // structured design intent card when the user prompt is too
          // ambiguous to build directly. UX matches AIAgentPanel's case
          // so chat mode and builder mode behave identically.
          case "design_intent_confirm": {
            const design: DesignIntentData = {
              card_id: (ev.card_id as string) ?? `intent-${Date.now()}`,
              inputs: (ev.inputs as DesignIntentData["inputs"]) ?? [],
              logic: (ev.logic as string) ?? "",
              presentation: (ev.presentation as DesignIntentData["presentation"]) ?? "mixed",
              alternatives: (ev.alternatives as DesignIntentData["alternatives"]) ?? [],
              clarifications: (ev.clarifications as DesignIntentData["clarifications"]) ?? [],
              resolved: false,
            };
            setChatHistory((prev) => [...prev, {
              id: nextId(),
              role: "design_intent",
              content: "",
              designIntent: design,
              designIntentPrompt: lastUserPromptRef.current,
            }]);
            addLog(makeLog("🧠",
              `DESIGN INTENT | card=${design.card_id} (${(design.clarifications ?? []).length} clarifications)`,
              "hitl"));
            break;
          }

          // v19: chat clarify pause — model 要 user 先確認 intent bullets.
          case "pb_intent_confirm": {
            const bullets = (ev.bullets as IntentBullet[]) ?? [];
            const reason = (ev.too_vague_reason as string | undefined) || undefined;
            const chatSid = String(ev.session_id ?? ev.build_session_id ?? "");
            if (bullets.length > 0) {
              setChatHistory((prev) => [...prev, {
                id: nextId(),
                role: "agent",
                content: "",
                card: {
                  type: "intent_confirm",
                  chat_session_id: chatSid,
                  bullets,
                  too_vague_reason: reason,
                },
              }]);
              addLog(makeLog("🧠",
                `INTENT CONFIRM | ${bullets.length} bullet(s) waiting for user`,
                "hitl"));
            }
            break;
          }
        }
      }, (err) => {
        addLog(makeLog("❌", `連線失敗: ${err.message}`, "error"));
      });
    } finally {
      setLoading(false);
    }
  }, [loading, onContract, addLog]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const STAGE_LABELS: Record<number, string> = {
    0: "S0", 1: "S1", 2: "S2", 3: "S3", 4: "S4", 5: "S5",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: 16, gap: 10 }}>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "#90cdf4" }}>AIOps Agent</div>
        {(tokenIn > 0 || tokenOut > 0) && (
          <div style={{ fontSize: 10, color: "#4a5568", fontFamily: "monospace" }}>
            in {tokenIn.toLocaleString()} / out {tokenOut.toLocaleString()} tok
          </div>
        )}
      </div>

      {/* Stage Progress */}
      {stages.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {stages.map((s) => (
            <div key={s.stage} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
              <span style={{
                width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                background: s.status === "complete" ? "#68d391" : s.status === "error" ? "#fc8181" : "#f6ad55",
              }} />
              <span style={{ color: s.status === "complete" ? "#4a5568" : "#e2e8f0" }}>
                {s.label || STAGE_LABELS[s.stage] || `S${s.stage}`}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Tab Bar */}
      <div style={{ display: "flex", borderBottom: "1px solid #2d3748" }}>
        {(["chat", "console"] as const).map((tab) => (
          <button key={tab} onClick={() => setActiveTab(tab)} style={{
            background: "none", border: "none", cursor: "pointer",
            padding: "6px 14px", fontSize: 12, fontWeight: 600,
            color: activeTab === tab ? "#63b3ed" : "#4a5568",
            borderBottom: activeTab === tab ? "2px solid #63b3ed" : "2px solid transparent",
            marginBottom: -1,
          }}>
            {tab === "chat" ? "💬 對話" : "⚙ Console"}
            {tab === "console" && loading && (
              <span style={{ marginLeft: 6, color: "#f6ad55" }}>●</span>
            )}
          </button>
        ))}
      </div>

      {/* HITL */}
      {hitl && (
        <div style={{ background: "#1a202c", border: "1px solid #f97316", borderRadius: 8, padding: "12px 16px" }}>
          <div style={{ fontSize: 12, color: "#f97316", fontWeight: 600, marginBottom: 6 }}>⚠️ HITL — 需要確認</div>
          <div style={{ fontSize: 12, color: "#e2e8f0", marginBottom: 8 }}>
            工具：<code style={{ color: "#fbbf24" }}>{hitl.tool}</code>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={() => resolveHitl(hitl.approval_token, true)}
              style={{ padding: "6px 14px", background: "#276749", color: "#9ae6b4", border: "none", borderRadius: 5, fontSize: 12, cursor: "pointer" }}>
              批准
            </button>
            <button onClick={() => resolveHitl(hitl.approval_token, false)}
              style={{ padding: "6px 14px", background: "#742a2a", color: "#feb2b2", border: "none", borderRadius: 5, fontSize: 12, cursor: "pointer" }}>
              拒絕
            </button>
          </div>
        </div>
      )}

      {/* Chat History Tab */}
      {activeTab === "chat" && (
        <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 10, minHeight: 0 }}>
          {chatHistory.length === 0 && (
            <div style={{ color: "#2d3748", fontSize: 13, paddingTop: 16, textAlign: "center" }}>
              輸入訊息開始對話
            </div>
          )}
          {chatHistory.map((msg) => (
            <div key={msg.id} style={{
              display: "flex",
              justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
            }}>
              {msg.card?.type === "rule_proposal" ? (
                <div style={{ maxWidth: "95%", width: "100%" }}>
                  <RuleProposalCard
                    ruleDraft={msg.card.rule_draft}
                    preview={msg.card.preview}
                  />
                </div>
              ) : msg.card?.type === "intent_confirm" ? (
                <div style={{ maxWidth: "95%", width: "100%" }}>
                  {msg.card.resolved === undefined ? (
                    <BulletConfirmCard
                      chatSessionId={msg.card.chat_session_id}
                      bullets={msg.card.bullets}
                      tooVagueReason={msg.card.too_vague_reason}
                      onConfirm={async (confirmations) => {
                        // Use consumeSSE pattern manually (ChatPanel doesn't
                        // export its stream handler). Drain events to find
                        // final status, then synthesize follow-up message.
                        const res = await fetch("/api/agent/chat/intent-respond", {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            chatSessionId: msg.card && msg.card.type === "intent_confirm" ? msg.card.chat_session_id : "",
                            confirmations,
                          }),
                        });
                        let finalStatus: "confirmed" | "refused" | "error" = "confirmed";
                        let summary = "";
                        try {
                          const reader = res.body?.getReader();
                          const decoder = new TextDecoder();
                          let buf = "";
                          while (reader) {
                            const { value, done } = await reader.read();
                            if (done) break;
                            buf += decoder.decode(value, { stream: true });
                            const blocks = buf.split(/\r?\n\r?\n/);
                            buf = blocks.pop() ?? "";
                            for (const block of blocks) {
                              let evName = "message";
                              const dl: string[] = [];
                              for (const line of block.replace(/\r/g, "").split("\n")) {
                                if (line.startsWith("event: ")) evName = line.slice(7).trim();
                                else if (line.startsWith("data: ")) dl.push(line.slice(6));
                              }
                              if (!dl.length) continue;
                              try {
                                const d = JSON.parse(dl.join("\n")) as Record<string, unknown>;
                                if (evName === "done" || d.type === "pb_glass_done") {
                                  const st = String(d.status ?? "");
                                  if (st === "refused") finalStatus = "refused";
                                  else if (st === "failed") finalStatus = "error";
                                  summary = String(d.summary ?? summary);
                                }
                              } catch { /* skip */ }
                            }
                          }
                        } catch (e) {
                          console.error(e);
                          finalStatus = "error";
                        }
                        const finalText = finalStatus === "confirmed"
                          ? (summary ? `✓ 已建好：${summary}` : "✓ 已建好，請到 Pipeline Builder 查看")
                          : finalStatus === "refused"
                            ? "✋ 已取消 — 請重新描述你要的需求"
                            : "⚠ 處理時出錯，請再試一次";
                        setChatHistory((prev) => prev.map((m) =>
                          m.id === msg.id && m.card?.type === "intent_confirm"
                            ? { ...m, card: { ...m.card, resolved: finalStatus, resolved_summary: summary } }
                            : m,
                        ).concat([{ id: nextId(), role: "agent", content: finalText }]));
                        return finalStatus;
                      }}
                    />
                  ) : (
                    <div style={{
                      fontSize: 11, color: "#4a5568", padding: "6px 10px",
                      background: "#1a202c", border: "1px solid #2d3748",
                      borderRadius: 6, fontStyle: "italic",
                    }}>
                      Intent {msg.card.resolved === "confirmed" ? "✓ confirmed" : msg.card.resolved === "refused" ? "✗ refused" : "⚠ error"}
                    </div>
                  )}
                </div>
              ) : msg.role === "plan" && msg.plan ? (
                <div style={{ width: "100%", maxWidth: "95%" }}>
                  <PlanCard plan={msg.plan} />
                </div>
              ) : msg.role === "design_intent" && msg.designIntent ? (
                <div style={{ width: "100%", maxWidth: "95%" }}>
                  <DesignIntentCard
                    data={msg.designIntent}
                    originalPrompt={msg.designIntentPrompt ?? ""}
                    onPick={(choice: DesignIntentChoice, design: DesignIntentData) => {
                      setChatHistory((prev) => prev.map((m) =>
                        m.id === msg.id && m.designIntent
                          ? { ...m, designIntent: { ...m.designIntent, resolved: true } }
                          : m,
                      ));
                      const original = msg.designIntentPrompt ?? "";
                      if (choice === "cancel") {
                        setChatHistory((prev) => [...prev, {
                          id: nextId(), role: "agent",
                          content: "已取消這次設計。需要的話請重新描述。",
                        }]);
                        return;
                      }
                      // confirm — compose [intent_confirmed:<id> sel=...] prefix
                      // + send via sendMessage with client_context.intent_spec
                      // (matches AIAgentPanel flow so backend behaviour is identical).
                      const sel = design.selections ?? {};
                      const selStr = Object.keys(sel)
                        .map((k) => `${k}=${sel[k]}`)
                        .join(" ");
                      const prefixHead = selStr
                        ? `[intent_confirmed:${design.card_id} ${selStr}]`
                        : `[intent_confirmed:${design.card_id}]`;
                      const followUp = `${prefixHead} ${original}`;
                      void sendMessage(followUp, {
                        intent_spec: {
                          card_id: design.card_id,
                          inputs: design.inputs,
                          logic: design.logic,
                          presentation: design.presentation,
                        },
                      });
                    }}
                  />
                </div>
              ) : (
                <div style={{
                  maxWidth: "85%",
                  padding: "10px 14px",
                  borderRadius: msg.role === "user" ? "12px 12px 2px 12px" : "12px 12px 12px 2px",
                  fontSize: 13,
                  lineHeight: 1.6,
                  whiteSpace: "pre-wrap",
                  background: msg.role === "user" ? "#2b6cb0" : "#1a202c",
                  color: msg.role === "user" ? "#bee3f8" : "#e2e8f0",
                  border: msg.role === "agent" ? "1px solid #2d3748" : "none",
                }}>
                  {msg.content}
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div style={{ display: "flex", justifyContent: "flex-start" }}>
              <div style={{ padding: "10px 14px", background: "#1a202c", border: "1px solid #2d3748", borderRadius: "12px 12px 12px 2px", fontSize: 12, color: "#4a5568" }}>
                ● ● ●
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>
      )}

      {/* Console Tab */}
      {activeTab === "console" && (
        <div style={{
          flex: 1, background: "#0d1117", borderRadius: 6,
          border: "1px solid #1e2a3a", overflowY: "auto",
          padding: "8px 10px", fontFamily: "monospace", fontSize: 11, minHeight: 0,
        }}>
          {logs.length === 0 && (
            <div style={{ color: "#2d3748", paddingTop: 8 }}>— Agent console —</div>
          )}
          {logs.map((entry) => (
            <div key={entry.id} style={{ display: "flex", gap: 6, marginBottom: 3, alignItems: "flex-start" }}>
              <span style={{ color: "#4a5568", flexShrink: 0 }}>{entry.ts}</span>
              <span style={{ flexShrink: 0 }}>{entry.icon}</span>
              <span style={{ color: LEVEL_COLOR[entry.level], wordBreak: "break-word" }}>{entry.text}</span>
            </div>
          ))}
          <div ref={logsEndRef} />
        </div>
      )}

      {/* Input */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input); }
          }}
          placeholder="輸入訊息，Enter 送出..."
          disabled={loading}
          rows={3}
          style={{
            background: "#1a202c", border: "1px solid #2d3748", borderRadius: 6,
            color: "#e2e8f0", padding: "10px 12px", fontSize: 13,
            resize: "none", outline: "none", width: "100%", boxSizing: "border-box",
          }}
        />
        <button
          onClick={() => sendMessage(input)}
          disabled={loading || !input.trim()}
          style={{
            background: loading ? "#2d3748" : "#3182ce", color: "#fff",
            border: "none", borderRadius: 6, padding: "8px 16px",
            fontSize: 13, cursor: loading ? "not-allowed" : "pointer", alignSelf: "flex-end",
          }}
        >
          {loading ? "處理中..." : "送出"}
        </button>
      </div>
    </div>
  );
}
