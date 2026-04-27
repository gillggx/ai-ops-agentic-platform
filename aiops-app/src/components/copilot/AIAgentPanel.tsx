"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import type { AIOpsReportContract, SuggestedAction } from "aiops-contract";
import { isValidContract, isAgentAction, isHandoffAction } from "aiops-contract";
import { consumeSSE } from "@/lib/sse";
import { ContractCard } from "./ContractCard";
import { PlanRenderer, type PlanItem } from "./PlanRenderer";
import OpsConsole, { type GlassOpEntry } from "./OpsConsole";
import SlashCommandMenu from "./SlashCommandMenu";
import { ChartIntentRenderer, type ChartIntent } from "./ChartIntentRenderer";
import { ChartExplorer } from "./ChartExplorer";
import { PipelineConsole, type PipelineCard } from "./PipelineConsole";
import PbPipelineCard, { type PbPipelineCardData } from "./PbPipelineCard";
import PbPatchProposalCard, { type PbPatchProposalData, type PipelinePatch } from "./PbPatchProposalCard";
import type { UiRender } from "@/components/McpChartRenderer";
import type { FlatDataMetadata, UIConfig } from "@/context/FlatDataContext";
import { useAppContext } from "@/context/AppContext";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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

interface McpResult {
  mcp_name: string;
  uiRender: UiRender;
  dataset?: unknown[];
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type RenderOptionBlock = { id: string; label: string; kind: string; charts?: any[]; outputs?: any; output_schema?: any[]; recommended?: boolean };
type RenderDecisionMeta = {
  kind: string;
  primary?: RenderOptionBlock;
  alternatives?: RenderOptionBlock[];
  question?: string;
  options?: RenderOptionBlock[];  // for ask_user
};

interface ChatMessage {
  id: number;
  role: "user" | "agent" | "mcp_result" | "chart_intents" | "chart_explorer" | "pb_pipeline" | "pb_proposal" | "plan" | "ops";
  content: string;
  contract?: AIOpsReportContract;
  mcpResult?: McpResult;
  chartIntents?: ChartIntent[];
  renderDecision?: RenderDecisionMeta;
  pbPipeline?: PbPipelineCardData;
  pbProposal?: PbPatchProposalData;
  // v1.7: when role === "plan", planItems carries the live checklist that
  // updates in place via plan_update events keyed off the message id.
  planItems?: PlanItem[];
  // v1.7: when role === "ops", glassOps carries the build-op trail that
  // accumulates across pb_glass_op events keyed off the message id.
  glassOps?: GlassOpEntry[];
  // Generative UI
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  flatData?: Record<string, any[]>;
  flatMetadata?: FlatDataMetadata;
  uiConfig?: UIConfig;
  // Phase v1.3 P0: feedback tracking — only meaningful when role === "agent"
  // and message originated from a synthesis event. messageIdx is the running
  // synthesis count within the session so the backend can dedup ratings.
  messageIdx?: number;
  feedbackRating?: 1 | -1 | null;   // null = not yet rated
  feedbackSubmitting?: boolean;
}

interface HitlRequest {
  approval_token: string;
  tool: string;
  input?: Record<string, unknown>;
}

interface ReflectionState {
  status: "running" | "pass" | "amendment" | null;
  amendment: string;
}

interface Props {
  onContract?: (contract: AIOpsReportContract) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onDataExplorer?: (state: any) => void;
  triggerMessage?: string | null;
  onTriggerConsumed?: () => void;
  contextEquipment?: string | null;
  onHandoff?: (mcp: string, params?: Record<string, unknown>) => void;
  // Phase 5-UX-3b: session-tab mode.
  // "standalone" (default) — renders pb_pipeline card inline in chat (legacy behavior).
  // "session"              — does NOT render inline card; fires onPipelineUpdate so
  //                          the hosting BuilderLayout can update canvas + results.
  mode?: "standalone" | "session";
  // Phase 5-UX-5: fired during build_pipeline execution so a session-mode
  // host can draw the DAG structure immediately (all nodes pending) and
  // then light up each node as it finishes.
  onPbStructure?: (pipelineJson: unknown) => void;
  onPbNodeStart?: (evt: { node_id: string; block_id?: string; sequence?: number }) => void;
  onPbNodeDone?: (evt: { node_id: string; status: string; rows?: number | null; duration_ms?: number; error?: string | null }) => void;
  // Phase 5-UX-5 Copilot: when user clicks "套用到 Canvas" on a patch proposal
  // the host (BuilderLayout) applies it via BuilderContext actions.
  onApplyPatches?: (patches: PipelinePatch[]) => Promise<void> | void;
  // Phase 5-UX-5: focus chip — user's next question is about this node/edge
  // specifically. Set when user right-clicks a node or clicks "Ask about this".
  focusedNodeId?: string | null;
  focusedNodeLabel?: string | null;
  onClearFocus?: () => void;
  // Phase 5-UX-6: Glass Box event hooks. When chat agent calls build_pipeline_live,
  // the backend relays sub-agent events as pb_glass_* SSE events. Host component
  // consumes these to drive a live canvas overlay / session-embedded canvas.
  onGlassStart?: (ev: { session_id: string; goal?: string }) => void;
  onGlassOp?: (ev: { op: string; args: Record<string, unknown>; result: Record<string, unknown> }) => void;
  onGlassChat?: (ev: { content: string }) => void;
  onGlassError?: (ev: { message: string; op?: string; hint?: string }) => void;
  onGlassDone?: (ev: { status: string; summary?: string; pipeline_json?: unknown }) => void;
  // v1.4: parent (AppShell) relays plan items to LiveCanvasOverlay so the
  // checklist stays visible while the overlay covers AIAgentPanel.
  onPlanItemsChange?: (items: PlanItem[]) => void;
  // chat-driven build_pipeline_live finished + auto-run completed — hand
  // the result to AppShell which feeds the Lite Canvas overlay's "結果" tab.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onPipelineResult?: (summary: any, nodeResults: Record<string, any>) => void;
  // v1.6 Lite Canvas — auto-run lifecycle hooks so AppShell can drive the
  // overlay's status pill + auto-switch the tab on completion / failure.
  onAutoRunStart?: (nodeCount: number) => void;
  onAutoRunDone?: (durationMs?: number) => void;
  onAutoRunError?: (errorMessage: string) => void;
  // Phase 5-UX-6: fired whenever the user sends a message — host uses this to
  // mirror the message into the live canvas overlay's chat panel.
  onUserMessageSent?: (text: string) => void;
  // When provided, overrides the internal session id (used by /chat/[id] to pin
  // the panel to a specific conversation).
  sessionId?: string | null;
  // Phase 5-UX-3b: session mode only — fired when Agent builds a pipeline so the
  // host page can hydrate the canvas + results in place.
  onPipelineUpdate?: (card: PbPipelineCardData) => void;
  // Phase 5-UX-5: standalone mode — fired when user clicks "↗ 展開 canvas" on a
  // pb_pipeline result card so the host shell can mount a full-page overlay.
  onPbPipelineExpand?: (card: PbPipelineCardData) => void;
  // Optional seed prompt; auto-sent once when the panel first mounts.
  initialPrompt?: string | null;
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
  info:     "#2b6cb0",
  tool:     "#d69e2e",
  thinking: "#718096",
  memory:   "#805ad5",
  error:    "#e53e3e",
  hitl:     "#ed8936",
  token:    "#a0aec0",
};

// ---------------------------------------------------------------------------
// Quick prompts by context
// ---------------------------------------------------------------------------

// v1.7: contextual quick prompts retired in favour of <SlashCommandMenu/>
// triggered by typing "/" in the textarea. See SlashCommandMenu.tsx.

// ---------------------------------------------------------------------------
// Markdown styles — applied to agent message bubble
// ---------------------------------------------------------------------------

const MD_STYLES: React.CSSProperties = {
  // reset default browser/react-markdown margin that bleeds outside bubble
  lineHeight: 1.6,
};

// Global CSS injected once for markdown elements inside agent bubbles.
// We use a <style> tag approach to avoid adding a CSS file dependency.
const MD_CSS = `
.md-agent p  { margin: 0 0 6px; }
.md-agent p:last-child { margin-bottom: 0; }
.md-agent h1,.md-agent h2,.md-agent h3,.md-agent h4 {
  font-weight: 700; margin: 10px 0 4px; color: #1a202c; line-height: 1.3;
}
.md-agent h2 { font-size: 14px; border-bottom: 1px solid #e2e8f0; padding-bottom: 3px; }
.md-agent h3 { font-size: 13px; }
.md-agent h4 { font-size: 12px; color: #4a5568; }
.md-agent ul,.md-agent ol { margin: 4px 0 6px 16px; padding: 0; }
.md-agent li { margin-bottom: 2px; }
.md-agent code {
  font-family: monospace; font-size: 11px;
  background: #edf2f7; color: #2d3748;
  padding: 1px 5px; border-radius: 4px;
}
.md-agent pre {
  background: #edf2f7; border-radius: 6px;
  padding: 8px 10px; overflow-x: auto; margin: 6px 0;
}
.md-agent pre code { background: none; padding: 0; font-size: 11px; }
.md-agent table {
  width: 100%; border-collapse: collapse; font-size: 12px; margin: 6px 0;
}
.md-agent th {
  background: #ebf4ff; color: #2b6cb0; font-weight: 600;
  padding: 4px 8px; text-align: left; border: 1px solid #bee3f8;
}
.md-agent td {
  padding: 4px 8px; border: 1px solid #e2e8f0; vertical-align: top;
}
.md-agent tr:nth-child(even) td { background: #f7fbff; }
.md-agent strong { font-weight: 700; color: #1a202c; }
.md-agent blockquote {
  border-left: 3px solid #bee3f8; padding: 4px 10px;
  margin: 6px 0; color: #4a5568; background: #ebf4ff20;
}
.md-agent hr { border: none; border-top: 1px solid #e2e8f0; margin: 8px 0; }
`;

// ---------------------------------------------------------------------------
// IntentChipBar — Phase v1.3 P0 quick-prompt scaffolding.
// Three chips above the textarea cover the three components a good agent
// instruction needs: data scope, judgement logic, presentation.
// Click → prefills the textarea with a template; the [token] placeholders
// get auto-selected so the user just types over them.
// ---------------------------------------------------------------------------

// v1.7: IntentChipBar (查資料 / 診斷邏輯 / 呈現結果) retired in favour of
// <SlashCommandMenu/>. The catalog now lives in SlashCommandMenu.tsx.

// ---------------------------------------------------------------------------
// RenderDecisionChips — inline expandable chart switcher for MCP results
// ---------------------------------------------------------------------------

function RenderDecisionChips({ decision, onContract }: {
  decision: RenderDecisionMeta;
  onContract?: (contract: AIOpsReportContract) => void;
}) {
  // Collect all options (primary first, then alternatives)
  const allOptions: RenderOptionBlock[] = [];
  if (decision.primary) allOptions.push(decision.primary);
  if (decision.alternatives) allOptions.push(...decision.alternatives);
  if (decision.options) allOptions.push(...decision.options);

  if (allOptions.length === 0) return null;

  function handleClick(opt: RenderOptionBlock) {
    if (!onContract) return;
    // Build a contract from the render option → opens in center AnalysisPanel
    const charts = opt.charts ?? [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const contract: any = {
      $schema: "aiops-report/v1",
      summary: opt.label,
      evidence_chain: [],
      visualization: [],
      suggested_actions: [],
      charts,
      ...(opt.outputs ? {
        findings: { condition_met: false, summary: "", outputs: opt.outputs },
        output_schema: opt.output_schema ?? [],
      } : {}),
    };
    onContract(contract);
  }

  return (
    <div style={{ maxWidth: "90%", marginTop: 4 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {allOptions.map((opt) => (
          <button
            key={opt.id}
            onClick={() => handleClick(opt)}
            style={{
              padding: "3px 10px", fontSize: 11, borderRadius: 12,
              border: "1px solid #cbd5e0", background: "#fff",
              color: "#4a5568", cursor: "pointer", fontWeight: 400,
            }}
          >
            {opt.recommended ? "⭐ " : ""}{opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// FeedbackBar — 👍 / 👎 row under each agent synthesis message (Phase v1.3 P0).
// Stays minimal until a rating is submitted; afterwards shrinks to a confirmation.
// ---------------------------------------------------------------------------

function FeedbackBar({ message, onRate, onOpenReasonModal }: {
  message: ChatMessage;
  onRate: (rating: 1) => void;          // 👍 fires inline
  onOpenReasonModal: () => void;         // 👎 opens reason modal
}) {
  const submitting = message.feedbackSubmitting;
  const rated = message.feedbackRating;

  if (rated) {
    return (
      <div style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "2px 8px", marginTop: 4, borderRadius: 10,
        fontSize: 10, color: "#718096", background: "#f7f8fc",
      }}>
        <span>{rated === 1 ? "👍" : "👎"}</span>
        <span>已記錄</span>
      </div>
    );
  }

  const baseStyle = {
    background: "transparent", border: "1px solid #e2e8f0",
    cursor: submitting ? "wait" : "pointer", padding: "2px 8px",
    borderRadius: 10, fontSize: 12,
  } as const;

  return (
    <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
      <button
        type="button"
        disabled={submitting}
        title="這個回答有幫助"
        style={baseStyle}
        onClick={() => onRate(1)}
      >
        👍
      </button>
      <button
        type="button"
        disabled={submitting}
        title="這個回答有問題"
        style={baseStyle}
        onClick={onOpenReasonModal}
      >
        👎
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// FeedbackReasonModal — 👎 reason picker (Phase v1.3 P0).
// 3 reason chips + optional free-text. Confirms with `(reason, freeText)`.
// ---------------------------------------------------------------------------

const FEEDBACK_REASONS = [
  { code: "data_wrong",    label: "資料錯" },
  { code: "logic_wrong",   label: "邏輯錯" },
  { code: "chart_unclear", label: "圖表看不懂" },
] as const;

function FeedbackReasonModal({ onConfirm, onCancel }: {
  onConfirm: (reason: string, freeText: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState<string | null>(null);
  const [text, setText] = useState("");
  return (
    <div
      onClick={onCancel}
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(0,0,0,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff", borderRadius: 8, padding: 20, width: 360,
          maxWidth: "90vw", boxShadow: "0 10px 30px rgba(0,0,0,0.3)",
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: "#1a202c" }}>
          這個回答有什麼問題？
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
          {FEEDBACK_REASONS.map((r) => (
            <button
              key={r.code}
              type="button"
              onClick={() => setReason(r.code)}
              style={{
                padding: "6px 12px", borderRadius: 14, fontSize: 12,
                cursor: "pointer",
                border: `1px solid ${reason === r.code ? "#2b6cb0" : "#cbd5e0"}`,
                background: reason === r.code ? "#ebf4ff" : "#fff",
                color: reason === r.code ? "#2b6cb0" : "#4a5568",
                fontWeight: reason === r.code ? 600 : 400,
              }}
            >
              {r.label}
            </button>
          ))}
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="（選填）可以多說一點嗎？"
          rows={3}
          maxLength={500}
          style={{
            width: "100%", boxSizing: "border-box", padding: 8,
            border: "1px solid #e2e8f0", borderRadius: 4,
            fontSize: 12, resize: "vertical", fontFamily: "inherit",
          }}
        />
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
          <button
            type="button" onClick={onCancel}
            style={{ padding: "6px 14px", fontSize: 12, border: "1px solid #cbd5e0",
                     background: "#fff", borderRadius: 4, cursor: "pointer" }}
          >取消</button>
          <button
            type="button"
            disabled={!reason}
            onClick={() => reason && onConfirm(reason, text)}
            style={{ padding: "6px 14px", fontSize: 12, border: "none",
                     background: reason ? "#2b6cb0" : "#a0aec0", color: "#fff",
                     borderRadius: 4, cursor: reason ? "pointer" : "not-allowed" }}
          >送出</button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AICopilot
// ---------------------------------------------------------------------------

export function AIAgentPanel({
  onContract,
  onDataExplorer,
  triggerMessage,
  onTriggerConsumed,
  contextEquipment,
  onHandoff,
  mode = "standalone",
  sessionId: externalSessionId,
  onPipelineUpdate,
  onPbPipelineExpand,
  onPbStructure,
  onPbNodeStart,
  onPbNodeDone,
  onApplyPatches,
  focusedNodeId,
  focusedNodeLabel,
  onClearFocus,
  onGlassStart,
  onGlassOp,
  onGlassChat,
  onGlassError,
  onGlassDone,
  onPlanItemsChange,
  onPipelineResult,
  onAutoRunStart,
  onAutoRunDone,
  onAutoRunError,
  onUserMessageSent,
  initialPrompt,
}: Props) {
  // Part B (SPEC_context_engineering): pull selected equipment from AppContext
  // so chat requests can carry user focus to the agent's load_context_node.
  const { selectedEquipment } = useAppContext();
  const [input, setInput]           = useState("");
  const [loading, setLoading]       = useState(false);
  const [stages, setStages]         = useState<StageState[]>([]);
  const [logs, setLogs]             = useState<LogEntry[]>([]);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  // v1.7 — slash command menu (triggered by typing "/" at start of input).
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashFilter, setSlashFilter] = useState("");
  const slashKeyHandlerRef = useRef<((e: React.KeyboardEvent | KeyboardEvent) => boolean) | null>(null);
  // Phase v1.3 P0: count synthesis events emitted during this session so each
  // agent answer gets a stable message_idx for the feedback log.
  const synthesisIdxRef = useRef(0);
  // Phase v1.3 P0: 👎 modal state — null when closed.
  const [feedbackModal, setFeedbackModal] = useState<{ messageId: number; messageIdx: number } | null>(null);
  // v1.4 Plan Panel — agent-emitted todo list, refreshed each turn.
  const [planItems, setPlanItems] = useState<PlanItem[]>([]);
  // v1.7 — id of the inline plan chat-card so plan_update events know which
  // message to mutate. Reset at every pb_glass_start.
  const currentPlanMsgIdRef = useRef<number | null>(null);
  // v1.7 — id of the inline ops chat-card so each new pb_glass_op appends to
  // the right build session's trail. Reset at every pb_glass_start.
  const currentOpsMsgIdRef = useRef<number | null>(null);
  // v1.5 — Glass Box build ops accumulate here, surfaced via OpsConsole (default
  // collapsed). Cleared at the start of every new build session.
  // v1.7: glassOps standalone state retired — ops now live as a "ops"
  // chat-message inserted right after the plan card. See currentOpsMsgIdRef.
  // v1.4 — relay plan changes to parent (AppShell → LiveCanvasOverlay).
  useEffect(() => { onPlanItemsChange?.(planItems); }, [planItems, onPlanItemsChange]);
  // v1.4 Auto-Run — tracks pb_run_* lifecycle for progress display.
  const [autoRun, setAutoRun] = useState<{ status: "idle" | "running" | "done" | "error"; nodeCount?: number; startedAt?: number; durationMs?: number; error?: string }>({ status: "idle" });
  // v1.4 — captured from pb_glass_done so the "Open in Pipeline Builder"
  // link can stash the just-built pipeline into sessionStorage for the
  // /new route to pick up.
  const lastBuiltPipelineRef = useRef<unknown | null>(null);
  const [hitl, setHitl]             = useState<HitlRequest | null>(null);
  const [tokenIn, setTokenIn]       = useState(0);
  const [tokenOut, setTokenOut]     = useState(0);
  const [activeTab, setActiveTab]   = useState<"chat" | "console">("chat");
  const [reflection, setReflection] = useState<ReflectionState>({ status: null, amendment: "" });

  const sessionIdRef = useRef<string | null>(externalSessionId ?? null);
  // When parent changes externalSessionId (e.g. /chat/[id] hydration finishes),
  // keep the ref in sync so next chat POST targets the right conversation.
  useEffect(() => {
    if (externalSessionId !== undefined) {
      sessionIdRef.current = externalSessionId;
    }
  }, [externalSessionId]);
  const chatEndRef   = useRef<HTMLDivElement>(null);
  // Phase v1.3 P0: textarea ref so chip prefill can auto-select first [token].
  const inputRef     = useRef<HTMLTextAreaElement>(null);
  const logsEndRef   = useRef<HTMLDivElement>(null);
  const pendingRenderDecisionRef = useRef<RenderDecisionMeta | null>(null);
  const [pipelineCards, setPipelineCards] = useState<PipelineCard[]>([]);
  const [pipelineStats, setPipelineStats] = useState<{ llmCalls: number; totalTokens: number }>({ llmCalls: 0, totalTokens: 0 });
  // Pipeline Skill save state — stores plan + generated code from SSE events
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const lastPipelinePlanRef = useRef<Record<string, any> | null>(null);
  const lastTransformCodeRef = useRef<string | null>(null);
  const lastComputeCodeRef = useRef<string | null>(null);
  const [pipelineSaved, setPipelineSaved] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pendingFlatDataRef = useRef<{ flatData: Record<string, any[]>; metadata: FlatDataMetadata; uiConfig: UIConfig | null; queryInfo?: any } | null>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, loading]);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // Auto-send triggered message from parent
  useEffect(() => {
    if (triggerMessage) {
      sendMessage(triggerMessage);
      onTriggerConsumed?.();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triggerMessage]);

  // Phase 5-UX-3b: session mode — auto-send the seed prompt once when the
  // panel first mounts (from /chat/new?prompt=... flow).
  const initialPromptFiredRef = useRef(false);
  useEffect(() => {
    if (!initialPromptFiredRef.current && initialPrompt && externalSessionId) {
      initialPromptFiredRef.current = true;
      sendMessage(initialPrompt);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPrompt, externalSessionId]);

  const addLog = useCallback((entry: LogEntry) => {
    setLogs((prev) => [...prev.slice(-200), entry]);
  }, []);

  const resolveHitl = useCallback(async (token: string, approved: boolean) => {
    setHitl(null);
    addLog(makeLog(approved ? "✅" : "❌", `HITL | ${approved ? "批准" : "拒絕"}: ${token}`, "hitl"));
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

  const sendMessage = useCallback(async (message: string) => {
    if (!message.trim() || loading) return;

    // Phase 5-UX-5: prepend focus context so LLM knows which node the
    // user's question targets. Focus persists across turns until cleared.
    const focusPrefix = focusedNodeId
      ? `[Focused on ${focusedNodeLabel ?? focusedNodeId} (${focusedNodeId})]\n`
      : "";
    const messageToSend = focusPrefix + message;

    setLoading(true);
    setStages([]);
    setLogs([]);
    setPipelineCards([]);
    setPipelineStats({ llmCalls: 0, totalTokens: 0 });
    setHitl(null);
    setTokenIn(0);
    setTokenOut(0);
    setReflection({ status: null, amendment: "" });
    setPlanItems([]);
    currentPlanMsgIdRef.current = null;
    setAutoRun({ status: "idle" });
    setInput("");
    setActiveTab("chat");

    setChatHistory((prev) => [...prev, { id: nextId(), role: "user", content: message }]);
    onUserMessageSent?.(message);

    try {
      // Part B (SPEC_context_engineering): pass user-side state to the agent.
      // Currently `selected_equipment_id` only; future: current_page, last alarm, etc.
      const clientContext: Record<string, string> = {};
      if (selectedEquipment?.equipment_id) {
        clientContext.selected_equipment_id = selectedEquipment.equipment_id;
      }
      const res = await fetch("/api/agent/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: messageToSend,
          session_id: sessionIdRef.current,
          ...(Object.keys(clientContext).length > 0 ? { client_context: clientContext } : {}),
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
            const STAGE_NAMES: Record<number, string> = {
              1: "Context", 2: "Planning", 3: "Retrieval", 4: "Transform",
              5: "Compute", 6: "Presentation", 7: "Synthesis", 8: "Critique", 9: "Memory",
            };
            const label  = (ev.label as string) ?? STAGE_NAMES[stage] ?? `Stage ${stage}`;
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
            const ragHits = (ev.rag_hits as Array<{ id: number; content: string }>) ?? [];
            const ragCount = (ev.rag_count as number) ?? 0;
            const histTurns = (ev.history_turns as number) ?? 0;
            addLog(makeLog("📦", `CTX | RAG 記憶: ${ragCount} 條 | 歷史: ${histTurns} 輪`, "info"));
            if (ragHits.length > 0) {
              ragHits.slice(0, 5).forEach((m) => {
                addLog(makeLog("🧠", `[記憶 #${m.id}] ${m.content.slice(0, 80)}${m.content.length > 80 ? "…" : ""}`, "info"));
              });
            }
            // Pipeline card
            setPipelineCards((prev) => [...prev.filter(c => c.stage !== 1), {
              stage: 1, name: "Context Load", icon: "📦", status: "complete",
              summary: `RAG: ${ragCount} 條 | History: ${histTurns} 輪`,
              detail: { rag_count: ragCount, history_turns: histTurns },
            }]);
            break;
          }

          case "thinking":
            addLog(makeLog("💭", `${((ev.text as string) ?? "").slice(0, 200)}`, "thinking"));
            break;

          case "llm_usage": {
            const inTok  = (ev.input_tokens  as number) ?? 0;
            const outTok = (ev.output_tokens as number) ?? 0;
            setTokenIn((p)  => p + inTok);
            setTokenOut((p) => p + outTok);
            setPipelineStats((p) => ({ llmCalls: p.llmCalls + 1, totalTokens: p.totalTokens + inTok + outTok }));
            addLog(makeLog("🔢", `LLM #${ev.iteration ?? "?"} in=${inTok} out=${outTok}`, "token"));
            break;
          }

          case "plan": {
            // v1.7 — plan now lives inline in the chat thread, right after
            // the user's request, so each new build gets its own plan card.
            // If the agent re-emits create within the same build, replace the
            // existing card in place instead of stacking a duplicate.
            const items = ev.items as PlanItem[] | undefined;
            if (Array.isArray(items)) {
              const cloned = items.map((it) => ({ ...it }));
              const existingId = currentPlanMsgIdRef.current;
              setPlanItems(cloned);
              if (existingId != null) {
                setChatHistory((prev) => prev.map((m) =>
                  m.id === existingId && m.role === "plan"
                    ? { ...m, planItems: cloned }
                    : m,
                ));
              } else {
                const planMsgId = nextId();
                currentPlanMsgIdRef.current = planMsgId;
                setChatHistory((prev) => [...prev, {
                  id: planMsgId, role: "plan", content: "",
                  planItems: cloned,
                }]);
              }
              break;
            }
            // Legacy — free-text plan from LLM <plan>...</plan> reasoning
            const planText = (ev.text as string) ?? "";
            if (planText) {
              addLog(makeLog("📋", `Plan: ${planText.slice(0, 200)}`, "info"));
              setPipelineCards((prev) => [...prev.filter(c => c.stage !== 2), {
                stage: 2, name: "Planning", icon: "🧠", status: "complete",
                summary: planText.slice(0, 100),
                detail: { plan: planText },
              }]);
            }
            break;
          }
          case "plan_update": {
            const id = ev.id as string;
            const status = ev.status as PlanItem["status"];
            const note = ev.note as string | undefined;
            const planMsgId = currentPlanMsgIdRef.current;
            // Update both the standalone planItems mirror (kept for overlay
            // relay) and the inline plan chat card so users see status flip
            // to ✓ in place.
            setPlanItems((prev) => prev.map((it) =>
              it.id === id ? { ...it, status: status ?? it.status, note: note ?? it.note } : it,
            ));
            if (planMsgId != null) {
              setChatHistory((prev) => prev.map((m) => {
                if (m.id !== planMsgId || m.role !== "plan") return m;
                const items = (m.planItems ?? []).map((it) =>
                  it.id === id ? { ...it, status: status ?? it.status, note: note ?? it.note } : it,
                );
                return { ...m, planItems: items };
              }));
            }
            break;
          }

          case "tool_start": {
            // Use params_summary (human-readable) if available, else fallback to raw JSON
            const ps = (ev.params_summary as string) ?? "";
            const toolName = (ev.tool as string) ?? "";
            const displayLabel = ps ? `${toolName}(${ps})` : toolName;
            addLog(makeLog("🔧", displayLabel, "tool"));
            // Capture pipeline plan for "Save as My Skill"
            if (toolName === "plan_pipeline" && ev.input) {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              lastPipelinePlanRef.current = ev.input as Record<string, any>;
              lastTransformCodeRef.current = null;
              lastComputeCodeRef.current = null;
              setPipelineSaved(false);
            }
            break;
          }

          case "tool_done": {
            const toolLabel = (ev.tool as string) ?? "";
            const summary = (ev.result_summary as string) ?? "";
            const ds = ev.data_shape as Record<string, unknown> | undefined;
            const renderHint = ds?.render as string | undefined;
            const parts = [toolLabel];
            if (summary) parts.push(`→ ${summary}`);
            if (renderHint) parts.push(`[${renderHint}]`);
            addLog(makeLog("✅", parts.join(" "), "tool"));
            const card = ev.render_card as Record<string, unknown> | undefined;
            if (card?.type === "draft" && card.draft_type === "mcp") {
              const autoFill = (card.auto_fill ?? {}) as Record<string, unknown>;
              // Stash for cross-page navigation (admin/mcps reads sessionStorage on mount)
              try { sessionStorage.setItem("admin:fill_mcp_draft", JSON.stringify(autoFill)); } catch { /* ignore */ }
              // Fire immediately if listener is already mounted (same-page copilot)
              window.dispatchEvent(new CustomEvent("admin:fill_mcp", { detail: autoFill }));
              addLog(makeLog("📋", `MCP 草稿已備妥 — 前往 MCP Builder 自動填表`, "info"));
            } else if (card?.type === "navigate") {
              const target = card.target as string | undefined;
              if (target) window.location.href = target;
            } else if (card?.type === "mcp") {
              // Capture render_decision for later use by synthesis message
              const rd = card.render_decision as RenderDecisionMeta | undefined;
              if (rd) {
                pendingRenderDecisionRef.current = rd;
              }
            } else if (card?.type === "pb_patch_proposal") {
              // Phase 5-UX-5 Copilot: agent proposes patches; render card with
              // Apply/Reject in chat.
              setChatHistory((prev) => [...prev, {
                id: nextId(),
                role: "pb_proposal",
                content: "",
                pbProposal: card as unknown as PbPatchProposalData,
              }]);
            } else if (card?.type === "pb_pipeline" || card?.type === "pb_pipeline_published") {
              const pbCard = card as unknown as PbPipelineCardData;
              if (mode === "session" && onPipelineUpdate) {
                // Phase 5-UX-3b session mode: canvas lives in host — just notify
                // + leave a compact chip in chat so the user sees what changed.
                onPipelineUpdate(pbCard);
                const nodeCount = pbCard.type === "pb_pipeline"
                  ? (pbCard.pipeline_json?.nodes?.length ?? 0)
                  : 0;
                const chipText = pbCard.type === "pb_pipeline"
                  ? `🛠️ Pipeline 已更新 · ${nodeCount} nodes · 已套用至畫布`
                  : `📌 已執行已發佈 Skill: ${pbCard.skill_name ?? pbCard.slug ?? ""}`;
                setChatHistory((prev) => [...prev, {
                  id: nextId(),
                  role: "agent",
                  content: chipText,
                }]);
              } else {
                // Standalone mode (main shell / Alarm Center): render full card inline.
                setChatHistory((prev) => [...prev, {
                  id: nextId(),
                  role: "pb_pipeline",
                  content: "",
                  pbPipeline: pbCard,
                }]);
              }
            }
            // Charts now always go to the analysis panel (center) via contract.visualization.
            // No longer render chart_intents inline in copilot (right side).
            break;
          }

          case "flat_data": {
            // Generative UI: cache flat data for DataExplorer
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const fd = ev.flat_data as Record<string, any[]>;
            const meta = ev.metadata as FlatDataMetadata;
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const qInfo = ev.query_info as any;
            if (fd && meta) {
              pendingFlatDataRef.current = {
                flatData: fd,
                metadata: meta,
                uiConfig: pendingFlatDataRef.current?.uiConfig ?? null,
                queryInfo: qInfo ?? undefined,
              };
              addLog(makeLog("📊", `Data flattened: ${meta.total_events} events, ${meta.available_datasets?.length ?? 0} datasets`, "tool"));
            }
            break;
          }

          case "ui_config": {
            // Generative UI: store visualization config + extract queryInfo
            const cfg = ev.config as UIConfig;
            if (cfg && pendingFlatDataRef.current) {
              pendingFlatDataRef.current.uiConfig = cfg;
              // Extract queryInfo from ui_config (set by pipeline_executor)
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const qi = (cfg as any).query_info;
              if (qi) pendingFlatDataRef.current.queryInfo = qi;
            }
            break;
          }

          // Phase 5-UX-6: Glass Box events from build_pipeline_live sub-agent.
          // Fire host callbacks AND append to local chat history so the panel
          // itself shows the agent's work (not just in the overlay).
          case "pb_glass_start": {
            const goal = ev.goal as string | undefined;
            onGlassStart?.({ session_id: ev.session_id as string, goal });
            // v1.7 — new build means fresh plan + ops cards; drop the refs
            // so the next plan / op event creates new chat-messages instead
            // of mutating the previous build's cards.
            currentPlanMsgIdRef.current = null;
            currentOpsMsgIdRef.current = null;
            setAutoRun({ status: "idle" });
            setChatHistory((prev) => [...prev, {
              id: nextId(), role: "agent",
              content: goal ? `🛠️ **正在建立 pipeline**：${goal}` : "🛠️ 正在建立 pipeline…",
            }]);
            break;
          }
          case "pb_glass_op": {
            const op = ev.op as string;
            const args = (ev.args as Record<string, unknown>) ?? {};
            const result = (ev.result as Record<string, unknown>) ?? {};
            onGlassOp?.({ op, args, result });
            const OP_LABEL_MAP: Record<string, string> = {
              add_node: "加入 node", remove_node: "刪除 node",
              connect: "連邊", set_param: "設定參數",
              rename_node: "重新命名", finish: "完成",
              list_blocks: "查看 block 清單", preview: "預覽", validate: "驗證",
            };
            const label = OP_LABEL_MAP[op] ?? op;
            let detail = "";
            if (op === "add_node") detail = `\`${args.block_name ?? ""}\``;
            else if (op === "connect") detail = `\`${args.from_node}.${args.from_port}\` → \`${args.to_node}.${args.to_port}\``;
            else if (op === "remove_node") detail = `\`${args.node_id}\``;
            else if (op === "set_param") detail = `\`${args.node_id}.${args.key}\``;
            else if (op === "rename_node") detail = `\`${args.node_id}\` → \`${args.label ?? args.display_label ?? "?"}\``;
            const newEntry: GlassOpEntry = {
              id: nextId(), op, label, detail, ts: Date.now(),
            };
            // v1.7: ops live as an inline "ops" chat-message, pushed once per
            // build session and updated in place via the message id ref so
            // the build-ops trail sits right under the plan in conversation
            // order instead of pinned at the top of the rail.
            const opsMsgId = currentOpsMsgIdRef.current;
            if (opsMsgId == null) {
              const newId = nextId();
              currentOpsMsgIdRef.current = newId;
              setChatHistory((prev) => [...prev, {
                id: newId, role: "ops", content: "", glassOps: [newEntry],
              }]);
            } else {
              setChatHistory((prev) => prev.map((m) => {
                if (m.id !== opsMsgId || m.role !== "ops") return m;
                return { ...m, glassOps: [...(m.glassOps ?? []), newEntry] };
              }));
            }
            break;
          }
          case "pb_glass_chat": {
            const content = (ev.content as string) ?? "";
            onGlassChat?.({ content });
            if (content.trim()) {
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "agent", content: `💬 ${content}`,
              }]);
            }
            break;
          }
          case "pb_glass_error": {
            const msg = (ev.message as string) ?? "";
            const opName = ev.op as string | undefined;
            onGlassError?.({
              message: msg,
              op: opName,
              hint: ev.hint as string | undefined,
            });
            const errEntry: GlassOpEntry = {
              id: nextId(),
              op: opName ?? "error",
              label: opName ? `${opName} 失敗` : "錯誤",
              detail: msg,
              ts: Date.now(),
              isError: true,
            };
            // v1.7: append to the inline ops chat-message (same pattern as
            // pb_glass_op), so build errors stay grouped with their build.
            const opsMsgId = currentOpsMsgIdRef.current;
            if (opsMsgId == null) {
              const newId = nextId();
              currentOpsMsgIdRef.current = newId;
              setChatHistory((prev) => [...prev, {
                id: newId, role: "ops", content: "", glassOps: [errEntry],
              }]);
            } else {
              setChatHistory((prev) => prev.map((m) => {
                if (m.id !== opsMsgId || m.role !== "ops") return m;
                return { ...m, glassOps: [...(m.glassOps ?? []), errEntry] };
              }));
            }
            setChatHistory((prev) => [...prev, {
              id: nextId(), role: "agent", content: `⚠️ ${msg}`,
            }]);
            break;
          }
          case "pb_glass_done": {
            const summary = ev.summary as string | undefined;
            // v1.4 — stash for the edit-link card later.
            if (ev.pipeline_json) lastBuiltPipelineRef.current = ev.pipeline_json;
            onGlassDone?.({
              status: (ev.status as string) ?? "finished",
              summary,
              pipeline_json: ev.pipeline_json,
            });
            setChatHistory((prev) => [...prev, {
              id: nextId(), role: "agent",
              content: `✓ **${summary || "完成"}**`,
            }]);
            break;
          }

          // Phase 5-UX-5: build_pipeline progressive events (legacy, kept
          // for any clients still streaming them; build_pipeline itself retired)
          case "pb_structure": {
            onPbStructure?.(ev.pipeline_json);
            break;
          }
          case "pb_node_start": {
            onPbNodeStart?.({
              node_id: ev.node_id as string,
              block_id: ev.block_id as string | undefined,
              sequence: ev.sequence as number | undefined,
            });
            addLog(makeLog("▶", `pb node start: ${ev.node_id}`, "tool"));
            break;
          }
          case "pb_node_done": {
            onPbNodeDone?.({
              node_id: ev.node_id as string,
              status: (ev.status as string) ?? "success",
              rows: ev.rows as number | null | undefined,
              duration_ms: ev.duration_ms as number | undefined,
              error: ev.error as string | null | undefined,
            });
            const icon = ev.status === "success" ? "✅" : ev.status === "skipped" ? "⏭️" : "❌";
            addLog(makeLog(icon, `pb node ${ev.node_id} ${ev.status} (${ev.rows ?? "—"} rows)`, "tool"));
            break;
          }
            // pb_run_start / pb_run_done / pb_run_error are handled below
            // (v1.4 Auto-Run section) — do NOT add a quiet stub here, JS
            // switch only runs the first matching case.

          case "pipeline_stage": {
            // 9-Stage Pipeline: each stage gets its own console log + stage dot
            const stageNum = (ev.stage as number) ?? 0;
            const icon = (ev.icon as string) ?? "▶";
            const name = (ev.name as string) ?? `Stage ${stageNum}`;
            const status = (ev.status as string) ?? "complete";
            const elapsed = (ev.elapsed as number) ?? 0;
            const summary = (ev.summary as string) ?? "";
            const statusIcon = status === "complete" ? "✅" : status === "error" ? "❌" : status === "skipped" ? "⏭️" : "🔄";

            // Add to stage indicators
            const stageStatus = status === "complete" ? "complete" : status === "error" ? "error" : "running";
            setStages((prev) => {
              const idx = prev.findIndex((s) => s.stage === stageNum);
              if (idx >= 0) {
                const u = [...prev]; u[idx] = { stage: stageNum, label: name, status: stageStatus as "running" | "complete" | "error" }; return u;
              }
              return [...prev, { stage: stageNum, label: name, status: stageStatus as "running" | "complete" | "error" }];
            });

            // Add console log (skip if skipped)
            if (status !== "skipped") {
              addLog(makeLog(icon, `${name} ${statusIcon} ${elapsed}s — ${summary}`, status === "error" ? "error" : "tool"));
            }

            // Capture generated code for "Save as My Skill"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const stageDetail = ev.detail as Record<string, any> | undefined;
            if (stageNum === 4 && stageDetail?.custom_code) {
              lastTransformCodeRef.current = stageDetail.custom_code as string;
            }
            if (stageNum === 5 && stageDetail?.code) {
              lastComputeCodeRef.current = stageDetail.code as string;
            }

            // Collect pipeline card for PipelineConsole
            const pipelineStatus = status === "complete" ? "complete" : status === "error" ? "error" : status === "skipped" ? "skipped" : "running";
            setPipelineCards((prev) => {
              const idx = prev.findIndex((c) => c.stage === stageNum);
              const card: PipelineCard = {
                stage: stageNum, name, icon, summary, elapsed,
                status: pipelineStatus as PipelineCard["status"],
                detail: ev.detail as Record<string, unknown> | undefined,
              };
              if (idx >= 0) {
                const u = [...prev]; u[idx] = card; return u;
              }
              return [...prev, card];
            });
            break;
          }

          case "memory_write": {
            const content = (ev.fix_rule ?? ev.content ?? "") as string;
            addLog(makeLog("💡", `[${ev.memory_type ?? ev.source ?? "mem"}] ${content.slice(0, 100)}`, "memory"));
            setPipelineCards((prev) => [...prev.filter(c => c.stage !== 9), {
              stage: 9, name: "Memory", icon: "💡", status: "complete",
              summary: content.slice(0, 60),
            }]);
            break;
          }

          case "approval_required": {
            const req: HitlRequest = {
              approval_token: ev.approval_token as string,
              tool:           ev.tool as string,
              input:          ev.input as Record<string, unknown> | undefined,
            };
            addLog(makeLog("⚠️", `HITL 等待批准: ${req.tool}`, "hitl"));
            setHitl(req);
            break;
          }

          case "synthesis": {
            const text = (ev.text as string) ?? "";
            const displayText = text.replace(/<contract>[\s\S]*?<\/contract>/g, "").trim();
            // Phase v1.3 P0 — assign a stable index for feedback dedup.
            synthesisIdxRef.current += 1;
            const _msgIdx = synthesisIdxRef.current - 1;
            if (isValidContract(ev.contract)) {
              const contract = ev.contract as AIOpsReportContract;
              onContract?.(contract);
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "agent",
                content: displayText || contract.summary || "",
                contract,
                messageIdx: _msgIdx,
                feedbackRating: null,
              }]);
            } else if (displayText) {
              // Attach flat data from query_data (Generative UI ChartExplorer)
              const pending = pendingFlatDataRef.current;
              pendingFlatDataRef.current = null;
              const rd = pendingRenderDecisionRef.current;
              pendingRenderDecisionRef.current = null;

              // Add text message
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "agent", content: displayText,
                ...(rd ? { renderDecision: rd } : {}),
                messageIdx: _msgIdx,
                feedbackRating: null,
              }]);

              // Open DataExplorer if we have flat data with actual events
              const hasEvents = (pending?.metadata?.total_events ?? 0) > 0 && (pending?.metadata?.available_datasets?.length ?? 0) > 0;
              if (pending?.flatData && pending.metadata && hasEvents) {
                onDataExplorer?.({
                  flatData: pending.flatData,
                  metadata: pending.metadata,
                  uiConfig: pending.uiConfig ?? undefined,
                  queryInfo: pending.queryInfo,
                });
              }
            }
            addLog(makeLog("💬", `Synthesis 完成 (${text.length} chars)`, "info"));
            setPipelineCards((prev) => [...prev.filter(c => c.stage !== 7), {
              stage: 7, name: "Synthesis", icon: "💬", status: "complete",
              summary: `${text.length} chars`,
            }]);
            break;
          }

          case "reflection_running":
            setReflection({ status: "running", amendment: "" });
            addLog(makeLog("🔍", "Self-Critique 驗證中…", "info"));
            break;

          case "reflection_pass":
            setReflection({ status: "pass", amendment: "" });
            addLog(makeLog("✅", "Self-Critique 通過 — 所有數值來源已確認", "info"));
            setPipelineCards((prev) => [...prev.filter(c => c.stage !== 8), {
              stage: 8, name: "Critique", icon: "🔍", status: "complete", summary: "PASS",
            }]);
            break;

          case "reflection_amendment": {
            const amendment = (ev.amendment as string) ?? "";
            setReflection({ status: "amendment", amendment });
            if (amendment) {
              setChatHistory((prev) => [
                ...prev,
                { id: nextId(), role: "agent", content: `🔍 **[自動修正]** ${amendment}` },
              ]);
            }
            addLog(makeLog("⚠️", `Self-Critique 修正: ${amendment.slice(0, 100)}`, "info"));
            break;
          }

          case "done":
            sessionIdRef.current = ev.session_id as string;
            break;

          // ── Auto-Run after build_pipeline_live ──────────────────
          // v1.6: takeover / link cards moved into the Lite Canvas overlay
          // (header "🛠 開啟編輯" + 結果 tab footer). Chat panel only logs
          // lifecycle and forwards events to AppShell.
          case "pb_run_start": {
            const nodeCount = (ev.node_count as number) ?? 0;
            setAutoRun({ status: "running", nodeCount, startedAt: Date.now() });
            addLog(makeLog("▶", `Auto-run 開始（${nodeCount} nodes）`, "info"));
            onAutoRunStart?.(nodeCount);
            break;
          }
          case "pb_run_done": {
            const durationMs = ev.duration_ms as number | undefined;
            setAutoRun((prev) => ({ ...prev, status: "done", durationMs }));
            addLog(makeLog("✅", `Auto-run 完成（${durationMs ?? "?"} ms）`, "info"));
            const nodeResults = (ev.node_results as Record<string, unknown>) ?? {};
            const summary = ev.result_summary as Record<string, unknown> | undefined;
            if (summary) {
              onPipelineResult?.(summary, nodeResults as Record<string, unknown>);
            }
            onAutoRunDone?.(durationMs);
            break;
          }
          case "pb_run_error": {
            const errMsg = (ev.error_message as string) ?? "execution failed";
            setAutoRun({ status: "error", error: errMsg });
            addLog(makeLog("❌", `Auto-run 失敗: ${errMsg}`, "error"));
            onAutoRunError?.(errMsg);
            break;
          }

          case "error": {
            const errMsg = (ev.message as string) ?? "Agent 發生錯誤";
            addLog(makeLog("❌", errMsg, "error"));
            setChatHistory((prev) => [...prev, {
              id: nextId(), role: "agent",
              content: `⚠️ ${errMsg.includes("authentication") || errMsg.includes("api_key") || errMsg.includes("auth_token")
                ? "Agent 無法連線 LLM — 請確認 ANTHROPIC_API_KEY 已設定並重啟 Agent。"
                : `Agent 錯誤：${errMsg}`}`,
            }]);
            break;
          }
        }
      }, (err) => {
        addLog(makeLog("❌", `連線失敗: ${err.message}`, "error"));
      });
    } finally {
      setLoading(false);
    }
  }, [loading, onContract, addLog, focusedNodeId, focusedNodeLabel]);

  // Phase v1.3 P0 — submit a 👍 / 👎 rating.
  // 👍 fires immediately; 👎 opens reason modal which calls back through here.
  const submitFeedback = useCallback(async (
    msg: ChatMessage,
    rating: 1 | -1,
    reason?: string,
    freeText?: string,
  ) => {
    if (msg.messageIdx === undefined || !sessionIdRef.current) return;
    setChatHistory((prev) => prev.map((m) =>
      m.id === msg.id ? { ...m, feedbackSubmitting: true } : m,
    ));
    try {
      // Java is configured with Jackson SNAKE_CASE — keys must match.
      const body: Record<string, unknown> = {
        session_id: sessionIdRef.current,
        message_idx: msg.messageIdx,
        rating,
      };
      if (rating === -1) {
        body.reason = reason;
        if (freeText) body.free_text = freeText;
      }
      // Snapshot the answer so post-hoc review can read context standalone.
      body.contract_summary = msg.contract?.summary ?? msg.content.slice(0, 500);
      const res = await fetch("/api/agent/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const ok = res.ok;
      setChatHistory((prev) => prev.map((m) =>
        m.id === msg.id
          ? { ...m, feedbackSubmitting: false, feedbackRating: ok ? rating : null }
          : m,
      ));
      if (!ok) {
        const err = await res.json().catch(() => ({}));
        addLog(makeLog("⚠️", `回饋送出失敗 (${res.status}): ${err.message ?? ""}`, "error"));
      }
    } catch (e) {
      setChatHistory((prev) => prev.map((m) =>
        m.id === msg.id ? { ...m, feedbackSubmitting: false } : m,
      ));
      addLog(makeLog("⚠️", `回饋送出失敗: ${e instanceof Error ? e.message : e}`, "error"));
    }
  }, [addLog]);

  async function handleSuggestedAction(action: SuggestedAction) {
    if (isAgentAction(action)) {
      sendMessage(action.message);
    } else if (isHandoffAction(action)) {
      onHandoff?.(action.mcp, action.params);
    } else if ((action as Record<string, unknown>).trigger === "promote_analysis") {
      const payload = (action as Record<string, unknown>).payload as Record<string, unknown> | undefined;
      if (!payload) { alert("無法儲存：缺少分析步驟資料"); return; }
      const title = (payload.title as string) || "Ad-hoc 分析";
      const name = prompt("儲存為 My Skill\n\n名稱：", title);
      if (!name) return;
      try {
        const res = await fetch("/api/admin/analysis/promote", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name,
            description: `從 Agent chat promote：${title}`,
            auto_check_description: title,
            steps_mapping: payload.steps_mapping,
            input_schema: payload.input_schema,
            output_schema: payload.output_schema || [],
          }),
        });
        if (res.ok) {
          alert(`已儲存為 Skill: ${name}\n\n前往 Knowledge Studio → My Skills 查看`);
        } else {
          const err = await res.json().catch(() => ({}));
          alert(`儲存失敗: ${(err as Record<string, string>).message || res.statusText}`);
        }
      } catch (e) {
        alert(`儲存失敗: ${e instanceof Error ? e.message : "未知錯誤"}`);
      }
    }
  }

  // v1.7: contextPrompts removed; slash menu replaces example pills.

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100%",
      background: "#ffffff",
      borderLeft: "1px solid #e2e8f0",
    }}>
      <style>{MD_CSS}</style>
      {/* Panel Header */}
      <div style={{
        padding: "12px 16px 0",
        borderBottom: "1px solid #e2e8f0",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: "#1a202c" }}>AI Agent</span>
            {contextEquipment && (
              <span style={{
                fontSize: 11,
                padding: "2px 8px",
                background: "#ebf4ff",
                color: "#2b6cb0",
                borderRadius: 10,
                fontWeight: 500,
              }}>
                {contextEquipment}
              </span>
            )}
          </div>
          {(tokenIn > 0 || tokenOut > 0) && (
            <span style={{ fontSize: 10, color: "#a0aec0", fontFamily: "monospace" }}>
              {tokenIn.toLocaleString()} / {tokenOut.toLocaleString()} tok
            </span>
          )}
        </div>

        {/* v1.5 — Stage strip first, then Plan Panel sits directly under so the
            checklist visually extends the progress strip. */}
        {stages.length > 0 && (
          <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
            {stages.map((s) => (
              <div key={s.stage} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
                <span style={{
                  width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                  background: s.status === "complete" ? "#38a169" : s.status === "error" ? "#e53e3e" : "#d69e2e",
                }} />
                <span style={{ color: s.status === "complete" ? "#a0aec0" : "#4a5568" }}>
                  {s.label || `S${s.stage}`}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* v1.6: Plan Panel moved into the chat tab body so it scrolls with
            the conversation instead of being pinned in the rail header. */}

        {autoRun.status !== "idle" && autoRun.status !== "running" && (
          <div style={{
            margin: "6px 12px 0",
            padding: "6px 10px",
            borderRadius: 6,
            fontSize: 11,
            background: autoRun.status === "error" ? "#fed7d7" : "#ebf4ff",
            color: autoRun.status === "error" ? "#c53030" : "#2b6cb0",
            border: `1px solid ${autoRun.status === "error" ? "#feb2b2" : "#bee3f8"}`,
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <span>
              {autoRun.status === "done" && `✓ Auto-Run 完成${autoRun.durationMs ? ` (${autoRun.durationMs} ms)` : ""}`}
              {autoRun.status === "error" && `✕ Auto-Run 失敗：${autoRun.error}`}
            </span>
          </div>
        )}

        {/* Tab Pills */}
        <div style={{ display: "flex", gap: 4 }}>
          {(["chat", "console"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                padding: "5px 12px",
                background: activeTab === tab ? "#ebf4ff" : "transparent",
                border: "none",
                borderRadius: "6px 6px 0 0",
                cursor: "pointer",
                fontSize: 12,
                fontWeight: activeTab === tab ? 600 : 400,
                color: activeTab === tab ? "#2b6cb0" : "#718096",
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              {tab === "chat" ? "💬 對話" : "⚙ Console"}
              {tab === "console" && loading && (
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#d69e2e", flexShrink: 0 }} />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* HITL */}
      {hitl && (
        <div style={{ margin: "8px 12px", background: "#fffaf0", border: "1px solid #fbd38d", borderRadius: 8, padding: "10px 12px", flexShrink: 0 }}>
          <div style={{ fontSize: 12, color: "#c05621", fontWeight: 600, marginBottom: 4 }}>⚠️ 需要確認</div>
          <div style={{ fontSize: 12, color: "#744210", marginBottom: 8 }}>工具：<code>{hitl.tool}</code></div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={() => resolveHitl(hitl.approval_token, true)} style={{ padding: "5px 12px", background: "#c6f6d5", color: "#276749", border: "none", borderRadius: 5, fontSize: 12, cursor: "pointer", fontWeight: 600 }}>批准</button>
            <button onClick={() => resolveHitl(hitl.approval_token, false)} style={{ padding: "5px 12px", background: "#fed7d7", color: "#9b2c2c", border: "none", borderRadius: 5, fontSize: 12, cursor: "pointer", fontWeight: 600 }}>拒絕</button>
          </div>
        </div>
      )}

      {/* Chat Tab */}
      {activeTab === "chat" && (
        <div style={{ flex: 1, overflowY: "auto", padding: "12px 12px 0", display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>
          {/* v1.7: plan + ops both live inline in chatHistory as message
              cards so each build's progress appears under its request. */}
          {chatHistory.length === 0 && (
            <div style={{ color: "#a0aec0", fontSize: 13, textAlign: "center", paddingTop: 24 }}>
              輸入訊息開始對話
            </div>
          )}
          {chatHistory.map((msg) => (
            <div
              key={msg.id}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: msg.role === "user" ? "flex-end" : "flex-start",
              }}
            >
              {msg.role === "plan" && msg.planItems ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <PlanRenderer items={msg.planItems} />
                </div>
              ) : msg.role === "ops" && msg.glassOps ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <OpsConsole ops={msg.glassOps} />
                </div>
              ) : msg.role === "pb_proposal" && msg.pbProposal ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <PbPatchProposalCard
                    proposal={msg.pbProposal}
                    onApply={onApplyPatches}
                  />
                </div>
              ) : msg.role === "pb_pipeline" && msg.pbPipeline ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <PbPipelineCard card={msg.pbPipeline} onExpand={onPbPipelineExpand} />
                </div>
              ) : msg.role === "chart_explorer" && msg.flatData && msg.flatMetadata ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <ChartExplorer
                    flatData={msg.flatData}
                    metadata={msg.flatMetadata}
                    uiConfig={msg.uiConfig}
                  />
                </div>
              ) : msg.role === "chart_intents" && msg.chartIntents ? (
                <div style={{ width: "100%", maxWidth: "90%" }}>
                  <ChartIntentRenderer charts={msg.chartIntents} />
                </div>
              ) : msg.role === "mcp_result" && msg.mcpResult ? (
                <div style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "4px 10px",
                  borderRadius: 6,
                  border: "1px solid #e2e8f0",
                  background: "#f7f8fc",
                  fontSize: 11, color: "#718096",
                }}>
                  <span>📊</span>
                  <span style={{ fontFamily: "monospace", color: "#2b6cb0" }}>{msg.mcpResult.mcp_name}</span>
                  <span>· 結果已載入分析面板</span>
                </div>
              ) : (
                <>
                  <div style={{
                    maxWidth: "90%",
                    padding: "9px 12px",
                    borderRadius: msg.role === "user" ? "12px 12px 2px 12px" : "12px 12px 12px 2px",
                    fontSize: 13,
                    lineHeight: 1.6,
                    background: msg.role === "user" ? "#2b6cb0" : "#f7f8fc",
                    color: msg.role === "user" ? "#fff" : "#1a202c",
                    border: msg.role === "agent" ? "1px solid #e2e8f0" : "none",
                  }}>
                    {msg.role === "user" ? (
                      <span style={{ whiteSpace: "pre-wrap" }}>{msg.content}</span>
                    ) : (
                      <div style={MD_STYLES} className="md-agent">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                      </div>
                    )}
                  </div>
                  {msg.role === "agent" && msg.contract && (
                    <div style={{ maxWidth: "90%", width: "100%" }}>
                      <ContractCard contract={msg.contract} onTrigger={handleSuggestedAction} />
                    </div>
                  )}
                  {msg.role === "agent" && msg.renderDecision && (
                    <RenderDecisionChips decision={msg.renderDecision} onContract={onContract} />
                  )}
                  {msg.role === "agent" && msg.messageIdx !== undefined && (
                    <FeedbackBar
                      message={msg}
                      onRate={() => submitFeedback(msg, 1)}
                      onOpenReasonModal={() => setFeedbackModal({ messageId: msg.id, messageIdx: msg.messageIdx! })}
                    />
                  )}
                </>
              )}
            </div>
          ))}
          {loading && (
            <div style={{ display: "flex", justifyContent: "flex-start" }}>
              <div style={{ padding: "10px 14px", background: "#f7f8fc", border: "1px solid #e2e8f0", borderRadius: "12px 12px 12px 2px", fontSize: 12, color: "#a0aec0" }}>
                ● ● ●
              </div>
            </div>
          )}
          {reflection.status && !loading && (
            <div style={{ display: "flex", paddingLeft: 4, paddingBottom: 4 }}>
              <span style={{
                fontSize: 10,
                padding: "3px 9px",
                borderRadius: 10,
                fontWeight: 600,
                border: "1px solid",
                ...(reflection.status === "pass"
                  ? { background: "#f0fff4", color: "#276749", borderColor: "#9ae6b4" }
                  : reflection.status === "amendment"
                  ? { background: "#fffff0", color: "#744210", borderColor: "#f6e05e" }
                  : { background: "#ebf4ff", color: "#2b6cb0", borderColor: "#bee3f8" }),
              }}>
                {reflection.status === "running" && "🔍 驗證數值來源…"}
                {reflection.status === "pass"    && "✓ 數值已驗證"}
                {reflection.status === "amendment" && "⚠ 已自動修正"}
              </span>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>
      )}

      {/* Console Tab */}
      {activeTab === "console" && (
        <div style={{
          flex: 1, background: "#fff", margin: "8px",
          borderRadius: 6, overflowY: "auto",
          border: "1px solid #e2e8f0", minHeight: 0,
        }}>
          <PipelineConsole
            cards={pipelineCards.sort((a, b) => a.stage - b.stage)}
            totalTime={pipelineCards.reduce((sum, c) => sum + (c.elapsed ?? 0), 0)}
            llmCalls={pipelineStats.llmCalls}
            totalTokens={pipelineStats.totalTokens}
            canSaveAsSkill={!!lastPipelinePlanRef.current && !pipelineSaved && pipelineCards.some(c => c.status === "complete" && c.stage >= 3)}
            saved={pipelineSaved}
            onSaveAsSkill={async () => {
              const plan = lastPipelinePlanRef.current;
              if (!plan) return;
              const name = prompt("儲存為 My Skill\n\n名稱：", plan.intent || "Pipeline Skill");
              if (!name) return;
              try {
                const res = await fetch("/api/admin/my-skills/from-pipeline", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    name,
                    description: plan.intent || name,
                    pipeline_plan: plan,
                    transform_code: lastTransformCodeRef.current,
                    compute_code: lastComputeCodeRef.current,
                  }),
                });
                if (res.ok) {
                  setPipelineSaved(true);
                  alert(`已儲存為 Skill: ${name}\n\n前往 Knowledge Studio → My Skills 查看`);
                } else {
                  const err = await res.json().catch(() => ({}));
                  alert(`儲存失敗: ${(err as Record<string, string>).message || res.statusText}`);
                }
              } catch (e) {
                alert(`儲存失敗: ${e instanceof Error ? e.message : "未知錯誤"}`);
              }
            }}
          />
          <div ref={logsEndRef} />
        </div>
      )}

      {/* v1.7: example-prompt pills retired in favour of slash menu */}

      {/* Phase 5-UX-5: focus chip — user's next message targets a specific node */}
      {focusedNodeId && (
        <div style={{ padding: "4px 12px 0", flexShrink: 0 }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 4px 3px 10px",
              background: "#ede9fe",
              border: "1px solid #c4b5fd",
              borderRadius: 12,
              fontSize: 11,
              color: "#4c1d95",
              fontWeight: 500,
            }}
          >
            <span style={{ fontSize: 10 }}>📌</span>
            <span>Focused on {focusedNodeLabel ?? focusedNodeId}</span>
            <button
              onClick={() => onClearFocus?.()}
              style={{
                border: "none",
                background: "transparent",
                color: "#6b46c1",
                cursor: "pointer",
                fontSize: 12,
                padding: "0 4px",
                lineHeight: 1,
              }}
              title="清除 focus"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* Input */}
      <div style={{ padding: "8px 12px 12px", flexShrink: 0, position: "relative" }}>
        {/* v1.7 — Slash-command menu. Triggered when textarea starts with "/". */}
        <SlashCommandMenu
          open={slashOpen}
          filter={slashFilter}
          onPick={(cmd) => {
            setInput(cmd.tpl);
            setSlashOpen(false);
            requestAnimationFrame(() => {
              const ta = inputRef.current;
              if (!ta) return;
              ta.focus();
              const m = cmd.tpl.match(/\[[^\]]+\]/);
              if (m && m.index !== undefined) {
                ta.setSelectionRange(m.index, m.index + m[0].length);
              } else {
                ta.setSelectionRange(cmd.tpl.length, cmd.tpl.length);
              }
            });
          }}
          onClose={() => setSlashOpen(false)}
          registerKeyHandler={(h) => { slashKeyHandlerRef.current = h; }}
        />
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => {
              const v = e.target.value;
              setInput(v);
              if (v.startsWith("/")) {
                setSlashOpen(true);
                setSlashFilter(v.slice(1));
              } else if (slashOpen) {
                setSlashOpen(false);
              }
            }}
            onKeyDown={(e) => {
              // Slash menu eats arrow keys / Enter / Esc when open.
              if (slashOpen && slashKeyHandlerRef.current?.(e)) {
                e.preventDefault();
                return;
              }
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input); }
            }}
            placeholder="輸入訊息… 或打 / 開啟常用指令選單"
            disabled={loading}
            rows={3}
            style={{
              flex: 1,
              background: "#f7f8fc",
              border: "1px solid #e2e8f0",
              borderRadius: 8,
              color: "#1a202c",
              padding: "9px 12px",
              fontSize: 13,
              resize: "none",
              outline: "none",
              boxSizing: "border-box",
              fontFamily: "inherit",
              minHeight: 60,
            }}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim()}
            style={{
              background: loading || !input.trim() ? "#e2e8f0" : "#2b6cb0",
              color: loading || !input.trim() ? "#a0aec0" : "#fff",
              border: "none",
              borderRadius: 8,
              padding: "9px 16px",
              fontSize: 13,
              fontWeight: 600,
              cursor: loading || !input.trim() ? "not-allowed" : "pointer",
              flexShrink: 0,
              height: 58,
            }}
          >
            {loading ? "…" : "送出"}
          </button>
        </div>
      </div>

      {/* Phase v1.3 P0 — 👎 reason modal (rendered at panel root so portal-like) */}
      {feedbackModal && (
        <FeedbackReasonModal
          onCancel={() => setFeedbackModal(null)}
          onConfirm={(reason, freeText) => {
            const msg = chatHistory.find((m) => m.id === feedbackModal.messageId);
            if (msg) submitFeedback(msg, -1, reason, freeText);
            setFeedbackModal(null);
          }}
        />
      )}
    </div>
  );
}
