"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useTranslations } from "next-intl";
import type { AIOpsReportContract, SuggestedAction } from "aiops-contract";
import { isValidContract, isAgentAction, isHandoffAction } from "aiops-contract";
import { consumeSSE } from "@/lib/sse";
import { useSession } from "next-auth/react";
import { activeLocale } from "@/i18n/format";
import { ContractCard } from "./ContractCard";
import { type PlanItem } from "./PlanRenderer";
import SlashCommandMenu from "./SlashCommandMenu";
import { ChartIntentRenderer, type ChartIntent } from "./ChartIntentRenderer";
import { ChartExplorer } from "./ChartExplorer";
import AgentConsole, { useConsoleStore, normalizeConsoleEvent } from "./AgentConsole";
import PbPipelineCard, { type PbPipelineCardData } from "./PbPipelineCard";
import { DraftCard, type DraftCardData, type TryRunChart } from "@/components/chatops/DraftCard";
import { KnowledgeAdminConfirmCard, type KnowledgeAdminData } from "./KnowledgeAdminConfirmCard";
import { MemoryRememberConfirmCard, type MemoryRememberData } from "./MemoryRememberConfirmCard";
import { AutomationConfirmCard, type AutomationHandoffData } from "./AutomationConfirmCard";
import { SkillActivateConfirmCard, type SkillActivateConfirmData } from "./SkillActivateConfirmCard";
import { AlarmActionConfirmCard, type AlarmActionData } from "./AlarmActionConfirmCard";
import { SkillAdminConfirmCard, type SkillAdminData } from "./SkillAdminConfirmCard";
import PbPatchProposalCard, { type PbPatchProposalData, type PipelinePatch } from "./PbPatchProposalCard";
import type { UiRender } from "@/components/McpChartRenderer";
import ChartRenderer from "@/components/pipeline-builder/ChartRenderer";
import type { FlatDataMetadata, UIConfig } from "@/context/FlatDataContext";
import { useAppContext } from "@/context/AppContext";
import { DesignIntentCard, type DesignIntentData, type DesignIntentChoice } from "./DesignIntentCard";
import { type GoalPhase, type PlanRemoval } from "@/components/pipeline-builder/v30/GoalPlanCard";
import { type PhaseRuntime } from "@/components/pipeline-builder/v30/PhaseTimeline";
import { type PlanPhase } from "@/components/chat/PlanConfirmCard";
import {
  IntentCard, BuildPlanCard, BuildDoneCard,
  renderUserContent, userBubbleStyle,
  type BuildPlanState, type BuildDoneState, type PhaseRuntimeUI,
} from "./BuildFlowCards";
import {
  JudgeClarifyCard,
  type JudgeClarifyData,
  type JudgeAction,
} from "@/components/chat/JudgeClarifyCard";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** modify-mode (2026-07-08): pull per-node OUTPUT columns from a pb card's
 *  node_results so a chat follow-up ships them for the column-aware
 *  situation report. Mirrors the sidecar's columns_from_node_results
 *  (reads preview.<port>.columns). */
function columnsFromNodeResults(
  nodeResults: Record<string, { preview?: Record<string, { columns?: string[] }> | null }> | undefined,
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [nid, nr] of Object.entries(nodeResults ?? {})) {
    const preview = nr?.preview;
    if (!preview) continue;
    const port = preview.data ?? Object.values(preview).find((p) => (p?.columns?.length ?? 0) > 0);
    if (port?.columns?.length) out[nid] = port.columns;
  }
  return out;
}

/** 草稿暫存區 (V78): thumbnail hint from the terminal chart block. */
function deriveDraftKind(pj: { nodes?: Array<{ block_id?: string }> } | undefined): string {
  const blocks = (pj?.nodes ?? []).map((n) => n.block_id ?? "");
  if (blocks.some((b) => b.includes("pareto"))) return "pareto";
  if (blocks.some((b) => b.includes("bar_chart"))) return "bar";
  if (blocks.some((b) => b.includes("data_view"))) return "table";
  if (blocks.some((b) => b.includes("panel"))) return "panel";
  if (blocks.some((b) => b.includes("line_chart") || b.includes("xbar") || b.includes("imr"))) return "spc_trend";
  if (blocks.some((b) => b.includes("chart"))) return "chart";
  return "";
}

/** 草稿暫存區 (V78): auto-park a chat-built pipeline. Fire-and-forget —
 *  a draft-save failure must never disrupt the chat. Dedupe by node signature
 *  so the same pipeline re-rendering doesn't create duplicate drafts. */
async function autoSaveDraft(
  pj: Record<string, unknown> | null,
  columns: Record<string, string[]> | null,
  nl: string,
): Promise<void> {
  const nodes = (pj?.nodes as unknown[]) ?? [];
  const edges = (pj?.edges as unknown[]) ?? [];
  if (!pj || nodes.length === 0) return;
  try {
    await fetch("/api/chat-drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: (pj.name as string) || nl.slice(0, 60) || "Chat 草稿",
        nl,
        pipeline_json: pj,
        columns: columns ?? {},
        kind: deriveDraftKind(pj as { nodes?: Array<{ block_id?: string }> }),
        node_count: nodes.length,
        edge_count: edges.length,
      }),
    });
  } catch {
    // ignore — draft staging is best-effort
  }
}

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

interface ClarifyOption {
  id: string;
  label: string;
  preview?: string;
}

interface ClarifyData {
  question: string;
  options: ClarifyOption[];
  fallbackLabel?: string;
  // Echoes the original user message so the re-submit can re-attach it
  // after the [intent=<id>] prefix.
  originalMessage: string;
  resolved?: boolean;  // flips to true once user picks; hides the buttons
}

interface IntentConfirmData {
  session_id: string;
  bullets: import("@/components/chat/BulletConfirmCard").IntentBullet[];
  too_vague_reason?: string;
  resolved?: "confirmed" | "refused" | "error";
}

interface ChatMessage {
  id: number;
  role: "user" | "agent" | "mcp_result" | "chart_intents" | "chart_explorer" | "pb_pipeline" | "pb_proposal" | "plan" | "clarify" | "design_intent" | "intent_confirm" | "build_plan" | "build_done" | "chart_inline" | "judge_clarify" | "automation_confirm" | "skill_activate" | "alarm_action" | "skill_admin" | "draft_card" | "knowledge_admin" | "memory_remember";
  content: string;
  /** 對話分頁重整（2026-07-05）— BUILD PLAN 卡單卡生命週期 state。 */
  buildPlan?: BuildPlanState;
  /** 完成卡（§3.5）。 */
  buildDone?: BuildDoneState;
  /** 建構開始後 INTENT 卡收斂為單行（§4）。 */
  intentCollapsed?: boolean;
  clarify?: ClarifyData;
  designIntent?: DesignIntentData;
  /** v19 (2026-05-14) — pb_intent_confirm card for chat-mode build clarify. */
  intentConfirm?: IntentConfirmData;
  /** v31 (2026-07-04) — pb_plan_confirm card: builder-style plan gate in chat. */
  /** v30.17j — pb_judge_clarify deficit pause card. */
  judgeClarify?: JudgeClarifyData;
  /** v30.17j — chat session id captured at card-emit time, needed when
   *  POSTing /chat/intent-respond with judge_decision body. */
  judgeChatSessionId?: string;
  /** v19 (2026-05-14) — pb_glass_chart inline chart_spec snapshot. */
  chartSpec?: Record<string, unknown>;
  chartNodeId?: string;
  /** For role === "design_intent": the user prompt that produced this card,
   *  needed to compose the [intent_confirmed:<id>] follow-up message. */
  designIntentPrompt?: string;
  contract?: AIOpsReportContract;
  mcpResult?: McpResult;
  chartIntents?: ChartIntent[];
  renderDecision?: RenderDecisionMeta;
  pbPipeline?: PbPipelineCardData;
  /** issue#1 (2026-07-08): render the pb card compact (header + actions only,
   *  no charts) because the DAG/results already live in the Lite Canvas. */
  pbCompact?: boolean;
  /** 草稿暫存區 P3b (2026-07-09): parsed automation config awaiting confirm. */
  automationConfirm?: AutomationHandoffData;
  /** F4 (2026-07-10): activate-skill confirm card (editable name/desc). */
  skillActivate?: SkillActivateConfirmData;
  /** Alarm 處理能力包 (2026-07-10): ack/dispose/resolve confirm card. */
  alarmAction?: AlarmActionData;
  /** Domain Skill 管理 (2026-07-10): deactivate/delete/rename confirm card. */
  skillAdmin?: SkillAdminData;
  /** My Drafts (2026-07-12): 草稿卡（B 案）— Try Run / 啟用 / 刪除都在對話內。 */
  draftCard?: DraftCardData;
  /** 知識管理 (2026-07-12): 刪除/停用規則確認卡。 */
  knowledgeAdmin?: KnowledgeAdminData;
  memoryRemember?: MemoryRememberData;
  pbProposal?: PbPatchProposalData;
  // v1.7: when role === "plan", planItems carries the live checklist that
  // updates in place via plan_update events keyed off the message id.
  planItems?: PlanItem[];
  // v31.1 (2026-07-04): builder-style v30 plan progress — when set, the
  // plan message renders PhaseTimeline (same card as builder mode).
  goalPhases?: GoalPhase[];
  phaseRuntime?: Record<string, PhaseRuntime>;
  // (2026-07-05) ops trail 自對話移除 — 建構過程歸 Console 分頁。
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
  // Phase E2: backend orchestrator mode hint — "chat" (default) or "builder".
  // Sent with each /api/agent/chat call so the SAME orchestrator biases its
  // tool-choice + prompt section appropriately. BuilderLayout passes
  // "builder" so the agent treats every prompt as a pipeline-modification
  // intent by default.
  agentMode?: "chat" | "builder";
  // Phase E3 follow-up: current canvas pipeline_json. When set (only in
  // builder context), the orchestrator surfaces declared inputs in the
  // user opening message so the LLM reuses $name references instead of
  // inventing parallel ones. Also carried into build_pipeline_live so
  // Glass Box subsessions see the same canvas state.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  pipelineSnapshot?: any | null;
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
  onGlassStart?: (ev: { session_id: string; goal?: string; base_pipeline?: unknown }) => void;
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
  // When true, the host already renders the pipeline DAG + results in a
  // separate surface (the Lite Canvas overlay), so chat should NOT echo a
  // second copy of the charts / DAG. Instead we leave a compact chip so the
  // user still sees a chat trace of the event.
  liteCanvasActive?: boolean;
  /** Phase B ChatOps (2026-07-10): seed the conversation with persisted text
   *  history when resuming a session from the ChatOps sidebar. Cards are not
   *  persisted — resumed history renders as plain text turns. */
  initialMessages?: Array<{ role: string; content: string }>;
  /** ChatOps / 手機 (2026-07-11)：把完整訊息串（含圖卡）持久化到 localStorage，
   *  重載時整包還原 — server session 只存文字輪次，圖卡曾在重載後消失。 */
  persistHistory?: boolean;
  /** My Drafts (2026-07-12): rail/抽屜點草稿 → 草稿卡插入對話（nonce 觸發）。 */
  insertDraft?: { data: DraftCardData; nonce: number } | null;
  /** Fires when the backend resolves/creates the session id (done event) so
   *  the ChatOps sidebar can refresh + highlight the active conversation. */
  onSessionResolved?: (sessionId: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let _seq = 0;
const nextId = () => ++_seq;

// ── ChatOps / 手機 rich-history 持久化 (2026-07-11) ─────────────────────────
// server session 只存文字輪次；圖卡（chartSpec / pbPipeline / 完成卡…）在
// 重載後會消失（手機瀏覽器切走就回收分頁，最常中）。ChatMessage 全是純資料，
// 直接整包存 localStorage、重載整包還原。
const HISTORY_VERSION = 1;
const HISTORY_KEY_PREFIX = "chatops:history:";
const HISTORY_TTL_MS = 7 * 24 * 3600_000;

function loadPersistedHistory(sid: string): ChatMessage[] | null {
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY_PREFIX + sid);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { v?: number; at?: number; items?: ChatMessage[] };
    if (parsed?.v !== HISTORY_VERSION || !Array.isArray(parsed.items) || parsed.items.length === 0) return null;
    // 還原的 id 要墊高計數器，否則新訊息 id 會撞號（feedback / in-place 更新靠 id）。
    const maxId = Math.max(...parsed.items.map((m) => Number(m.id) || 0));
    if (maxId >= _seq) _seq = maxId + 1;
    return parsed.items;
  } catch { return null; }
}

function savePersistedHistory(sid: string, items: ChatMessage[]): void {
  try {
    // 順手清 7 天前的舊 key（別的 session 留下的）。
    for (const k of Object.keys(window.localStorage)) {
      if (!k.startsWith(HISTORY_KEY_PREFIX)) continue;
      try {
        const at = (JSON.parse(window.localStorage.getItem(k) || "{}") as { at?: number }).at ?? 0;
        if (Date.now() - at > HISTORY_TTL_MS) window.localStorage.removeItem(k);
      } catch { window.localStorage.removeItem(k); }
    }
    const write = (slice: ChatMessage[]) =>
      window.localStorage.setItem(HISTORY_KEY_PREFIX + sid,
        JSON.stringify({ v: HISTORY_VERSION, at: Date.now(), items: slice }));
    try { write(items.slice(-30)); }
    catch { try { write(items.slice(-10)); } catch { /* quota — 放棄，文字輪次仍有 server 備援 */ } }
  } catch { /* localStorage unavailable */ }
}

function makeLog(icon: string, text: string, level: LogLevel): LogEntry {
  return {
    id: nextId(), icon, text, level,
    ts: new Date().toLocaleTimeString("zh-TW", { hour12: false }),
  };
}

const LEVEL_COLOR: Record<LogLevel, string> = {
  info:     "var(--p, #2b6cb0)",
  tool:     "#d69e2e",
  thinking: "#718096",
  memory:   "#805ad5",
  error:    "#e53e3e",
  hitl:     "#ed8936",
  token:    "#a0aec0",
};

// Agent-loop role banner colors (Director orchestrates, Planner plans, Builder builds).
const ROLE_COLOR: Record<string, string> = {
  Director: "#4F46E5",
  Planner:  "#0891B2",
  Builder:  "#059669",
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
  background: var(--pl, #ebf4ff); color: var(--pd, #2b6cb0); font-weight: 600;
  padding: 4px 8px; text-align: left; border: 1px solid #bee3f8;
}
.md-agent td {
  padding: 4px 8px; border: 1px solid #e2e8f0; vertical-align: top;
}
.md-agent tr:nth-child(even) td { background: #f7fbff; }
.md-agent strong { font-weight: 700; color: #1a202c; }
.md-agent blockquote {
  border-left: 3px solid #bee3f8; padding: 4px 10px;
  margin: 6px 0; color: #4a5568; background: var(--pl, #ebf4ff);
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
  const t = useTranslations("agentPanel");
  const submitting = message.feedbackSubmitting;
  const rated = message.feedbackRating;

  if (rated) {
    return (
      <div style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "2px 8px", marginTop: 4, borderRadius: 10,
        fontSize: 10, color: "#718096", background: "var(--pn, #f7f8fc)",
      }}>
        <span>{rated === 1 ? t("feedbackDoneHelpful") : t("feedbackDoneInaccurate")}</span>
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
        title={t("feedbackHelpfulTitle")}
        style={baseStyle}
        onClick={() => onRate(1)}
      >
        {t("helpful")}
      </button>
      <button
        type="button"
        disabled={submitting}
        title={t("feedbackInaccurateTitle")}
        style={baseStyle}
        onClick={onOpenReasonModal}
      >
        {t("inaccurate")}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// FeedbackReasonModal — 👎 reason picker (Phase v1.3 P0).
// 3 reason chips + optional free-text. Confirms with `(reason, freeText)`.
// ---------------------------------------------------------------------------

const FEEDBACK_REASONS = [
  { code: "data_wrong",    labelKey: "reasonDataWrong" },
  { code: "logic_wrong",   labelKey: "reasonLogicWrong" },
  { code: "chart_unclear", labelKey: "reasonChartUnclear" },
] as const;

function FeedbackReasonModal({ onConfirm, onCancel }: {
  onConfirm: (reason: string, freeText: string) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("agentPanel");
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
          {t("feedbackReasonTitle")}
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
                border: `1px solid ${reason === r.code ? "var(--p, #2b6cb0)" : "#cbd5e0"}`,
                background: reason === r.code ? "var(--pl, #ebf4ff)" : "#fff",
                color: reason === r.code ? "var(--p, #2b6cb0)" : "#4a5568",
                fontWeight: reason === r.code ? 600 : 400,
              }}
            >
              {t(r.labelKey)}
            </button>
          ))}
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("feedbackFreeTextPlaceholder")}
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
          >{t("cancel")}</button>
          <button
            type="button"
            disabled={!reason}
            onClick={() => reason && onConfirm(reason, text)}
            style={{ padding: "6px 14px", fontSize: 12, border: "none",
                     background: reason ? "var(--p, #2b6cb0)" : "#a0aec0", color: "#fff",
                     borderRadius: 4, cursor: reason ? "pointer" : "not-allowed" }}
          >{t("send")}</button>
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
  agentMode = "chat",
  pipelineSnapshot,
  liteCanvasActive = false,
  initialMessages,
  persistHistory = false,
  insertDraft = null,
  onSessionResolved,
}: Props) {
  // Part B (SPEC_context_engineering): pull selected equipment from AppContext
  // so chat requests can carry user focus to the agent's load_context_node.
  const { selectedEquipment } = useAppContext();
  // i18n (2026-07-05) — captured in component scope so stream-event handlers
  // (useCallback closures) can compose translated agent messages.
  const t = useTranslations("agentPanel");
  const [input, setInput]           = useState("");
  const [loading, setLoading]       = useState(false);
  const [stages, setStages]         = useState<StageState[]>([]);
  // Live role banner (Director / Planner / Builder) while the agent-loop
  // drives a long build — makes the「等十幾秒」transparent (who is doing what).
  const [activeRole, setActiveRole] = useState<{ role: string; text: string } | null>(null);
  const [logs, setLogs]             = useState<LogEntry[]>([]);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>(() => {
    // ChatOps / 手機 resume：優先整包還原本機的 rich history（含圖卡）；
    // 沒有才退回 server 的文字輪次。
    if (persistHistory && externalSessionId) {
      const restored = loadPersistedHistory(externalSessionId);
      if (restored) return restored;
    }
    return (initialMessages ?? [])
      .filter((m) => typeof m.content === "string" && m.content.trim())
      .map((m) => ({
        id: nextId(),
        role: (m.role === "user" ? "user" : "agent") as "user" | "agent",
        content: m.content,
      }));
  });
  // v1.7 — slash command menu (triggered by typing "/" at start of input).
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashFilter, setSlashFilter] = useState("");
  const slashKeyHandlerRef = useRef<((e: React.KeyboardEvent | KeyboardEvent) => boolean) | null>(null);
  // Phase v1.3 P0: count synthesis events emitted during this session so each
  // agent answer gets a stable message_idx for the feedback log.
  const synthesisIdxRef = useRef(0);
  // Phase v1.3 P0: 👎 modal state — null when closed.
  const [feedbackModal, setFeedbackModal] = useState<{ messageId: number; messageIdx: number } | null>(null);
  // v1.4 Plan Panel — agent-emitted todo list; 2026-07-05 起僅作
  // LiteCanvas relay state（訊息流的 todo 卡已移除）。
  const [planItems, setPlanItems] = useState<PlanItem[]>([]);
  // 2026-07-05 對話重整 — 單卡生命週期：一次 build 只有一張 BUILD PLAN 卡
  // （同 message id 原地變身 草案 → 建構中 → 完成）。pb_plan_confirm /
  // pb_glass_chat(plan) / phase_update / pb_glass_op / pb_glass_done 全部
  // 對這個 id 做 in-place 更新。ops trail 已自對話移除（歸 Console）。
  const currentBuildCardIdRef = useRef<number | null>(null);
  // 完成卡 id — reflection_pass 事件把「數值已驗證」寫進卡而非漂浮 chip。
  const currentBuildDoneIdRef = useRef<number | null>(null);
  // v1.4 — relay plan changes to parent (AppShell → LiveCanvasOverlay).
  useEffect(() => { onPlanItemsChange?.(planItems); }, [planItems, onPlanItemsChange]);
  // v1.4 Auto-Run — tracks pb_run_* lifecycle for progress display.
  const [autoRun, setAutoRun] = useState<{ status: "idle" | "running" | "done" | "error"; nodeCount?: number; startedAt?: number; durationMs?: number; error?: string }>({ status: "idle" });
  // v1.4 — captured from pb_glass_done so the "Open in Pipeline Builder"
  // link can stash the just-built pipeline into sessionStorage for the
  // /new route to pick up.
  const lastBuiltPipelineRef = useRef<unknown | null>(null);
  // 草稿描述修正 (2026-07-12)：build goal（pb_glass_start 帶入）— park 草稿的
  // 描述來源，避免存到 build 期間的追問訊息。
  const lastBuildGoalRef = useRef<string>("");
  // Bug 2 fix (2026-05-05): continuation SSE consumer used to ignore every
  // pb_glass_* event, leaving the chat panel stuck on the pre-pause state
  // even after the build resumed and finished. Park the main dispatcher
  // here so /agent/build/continue can re-enter the same handler.
  const buildStreamHandlerRef = useRef<((ev: Record<string, unknown>) => void) | null>(null);


  // v31.1 — plan-confirm decision: POST resume + drain through the SAME
  // stream handler so PhaseTimeline / ops / charts render live.
  const decidePlan = useCallback(async (msgId: number, confirmed: boolean, phases: GoalPhase[], removals?: PlanRemoval[]) => {
    let target: ChatMessage | undefined;
    setChatHistory((prev) => {
      target = prev.find((m) => m.id === msgId);
      return prev;
    });
    // `||` not `??`: a card whose sessionId came through as "" (agent-loop
    // streaming race) must fall through to sessionIdRef.current (set by the
    // turn's `done` event) — `??` would keep the empty string and POST "".
    const chatSid = target?.buildPlan?.sessionId || sessionIdRef.current || "";
    const hm = new Date();
    const confirmedAt = `${String(hm.getHours()).padStart(2, "0")}:${String(hm.getMinutes()).padStart(2, "0")}`;
    if (confirmed) {
      // 單卡生命週期：同 message 原地變身 草案 → 建構中（§3.4 / §5）。
      const originalGoals = new Map(
        (target?.buildPlan?.phases ?? []).map((p) => [p.id, p.goal]),
      );
      const editedIds = phases
        .filter((p) => originalGoals.has(p.id) && originalGoals.get(p.id) !== p.goal)
        .map((p) => p.id);
      setChatHistory((prev) => prev.map((m) => {
        if (m.id === msgId && m.buildPlan) {
          return { ...m, buildPlan: {
            ...m.buildPlan, phases, status: "building" as const,
            confirmedAt, editedIds,
          }};
        }
        // 建構開始 → INTENT 卡收斂為單行摘要（§4 第三列）。
        if (m.role === "intent_confirm") return { ...m, intentCollapsed: true };
        return m;
      }));
    } else {
      setChatHistory((prev) => prev.map((m) =>
        m.id === msgId && m.buildPlan
          ? { ...m, buildPlan: { ...m.buildPlan, status: "cancelled" as const } }
          : m,
      ));
    }
    try {
      const res = await fetch("/api/agent/chat/intent-respond", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chatSessionId: chatSid,
          plan_decision: confirmed
            ? { confirmed, phases, removals: removals ?? [] }
            : { confirmed },
        }),
      });
      const handler = buildStreamHandlerRef.current;
      if (handler && res.ok) {
        await consumeSSE(res, (ev: Record<string, unknown>) => {
          handler(ev as Parameters<typeof handler>[0]);
        }, () => {});
      } else if (!res.ok && confirmed) {
        setChatHistory((prev) => prev.map((m) =>
          m.id === msgId && m.buildPlan
            ? { ...m, buildPlan: { ...m.buildPlan, status: "error" as const, errorReason: t("planSubmitFailed", { status: res.status }) } }
            : m,
        ));
      }
    } catch (e) {
      if (confirmed) {
        setChatHistory((prev) => prev.map((m) =>
          m.id === msgId && m.buildPlan
            ? { ...m, buildPlan: { ...m.buildPlan, status: "error" as const, errorReason: e instanceof Error ? e.message : String(e) } }
            : m,
        ));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [hitl, setHitl]             = useState<HitlRequest | null>(null);
  const [tokenIn, setTokenIn]       = useState(0);
  const [tokenOut, setTokenOut]     = useState(0);
  // Phase 2-A: cache transparency. cacheWrite is the one-time $3.75/MTok cost
  // of populating the cache; cacheRead is the recurring $0.30/MTok discount.
  // Sum across V2 chat + Glass Box subagent calls.
  const [cacheWrite, setCacheWrite] = useState(0);
  const [cacheRead, setCacheRead]   = useState(0);
  // SPEC_glassbox_continuation §B: live Glass Box turn counter shown above
  // the plan card. {turn_used, turn_budget, percent, warning}.
  const [glassProgress, setGlassProgress] = useState<{ turn_used: number; turn_budget: number; percent: number; warning: boolean } | null>(null);
  const [activeTab, setActiveTab]   = useState<"chat" | "console">("chat");
  // 稿 1d — 記憶 chip 行為按角色：PE/IT_ADMIN 進工房，其餘開唯讀浮卡
  const { data: _session } = useSession();
  const _roles: string[] = ((_session as unknown as { roles?: string[] })?.roles) ?? [];
  const memoryEditable = _roles.includes("PE") || _roles.includes("IT_ADMIN");
  const [reflection, setReflection] = useState<ReflectionState>({ status: null, amendment: "" });

  const sessionIdRef = useRef<string | null>(externalSessionId ?? null);
  // Track the most recent user-typed prompt so design_intent_confirm cards
  // can carry it forward when the user clicks ✅ / ✏️.
  const lastUserPromptRef = useRef<string>("");
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
  // Agent Console (2026-07-04): single events[] store, everything derived.
  // Replaces the dead 9-Stage PipelineConsole (stage 3-6 event sources were
  // removed with the old plan_pipeline path).
  const [consoleState, consoleDispatch] = useConsoleStore();
  // W-codes learned this build (for the completion card's 「這次學到 n 筆」).
  const memoryWritesRef = useRef<string[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pendingFlatDataRef = useRef<{ flatData: Record<string, any[]>; metadata: FlatDataMetadata; uiConfig: UIConfig | null; queryInfo?: any } | null>(null);

  // Phase E3 follow-up: keep pipelineSnapshot in a ref so sendMessage's
  // fetch body always reads the latest canvas state without re-creating the
  // callback every time the user moves a node.
  const pipelineSnapshotRef = useRef(pipelineSnapshot);
  useEffect(() => { pipelineSnapshotRef.current = pipelineSnapshot; }, [pipelineSnapshot]);

  // 2026-07-08 (A1 fix): chat has no builder canvas, but the LAST ad-hoc
  // pb_pipeline card IS the on-screen pipeline. Keep its pipeline_json in a
  // ref so a follow-up like「拿掉區帶」ships it as pipeline_snapshot — that is
  // what the G1 coordinator_triage fast path needs to recognise a chart
  // tweak (else it falls to a full rebuild + plan-confirm card).
  const lastChatPipelineRef = useRef<Record<string, unknown> | null>(null);
  // 2026-07-08 modify-mode: per-node output columns of that same pipeline,
  // shipped so the Coordinator situation report is column-aware (knows a
  // tooltip field like lotID/RECIPE already flows to the chart node).
  const lastChatColumnsRef = useRef<Record<string, string[]> | null>(null);
  // 草稿暫存區 (V78): signature of the last auto-saved pipeline, so the same
  // build re-rendering doesn't create duplicate drafts.
  const lastSavedDraftSigRef = useRef<string>("");

  // rich-history 持久化 (2026-07-11)：debounce 存檔（streaming 期間變動頻繁）。
  useEffect(() => {
    if (!persistHistory) return;
    const sid = sessionIdRef.current;
    if (!sid || chatHistory.length === 0) return;
    const timer = setTimeout(() => savePersistedHistory(sid, chatHistory), 800);
    return () => clearTimeout(timer);
  }, [chatHistory, persistHistory]);

  // V85 (2026-07-11) — rich history 的 server 備份（跨裝置）。3s debounce：
  // streaming 期間不打；停下來才 PUT 最終狀態。失敗靜默（本機 localStorage 仍在）。
  useEffect(() => {
    if (!persistHistory) return;
    const sid = sessionIdRef.current;
    if (!sid || chatHistory.length === 0) return;
    const timer = setTimeout(() => {
      try {
        let payload = JSON.stringify({ v: 1, at: Date.now(), items: chatHistory.slice(-30) });
        if (payload.length > 1_200_000) {
          payload = JSON.stringify({ v: 1, at: Date.now(), items: chatHistory.slice(-12) });
        }
        void fetch(`/api/agent/session/${encodeURIComponent(sid)}/rich-history`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rich_history: payload }),
        }).catch(() => { /* server 備份 best-effort */ });
      } catch { /* ignore */ }
    }, 3000);
    return () => clearTimeout(timer);
  }, [chatHistory, persistHistory]);

  // V85 (2026-07-11) — 工作與畫面非同步：重載後查此對話的背景工作。
  // running → 重新接上事件流（回放緩衝+即時）；離線期間完成 → 回放收尾事件
  // 補上完成卡與圖。輕量 dispatcher（進度行 in-place + 圖卡/完成卡 append），
  // 不動主 dispatcher。
  const reattachedRef = useRef(false);
  useEffect(() => {
    if (!persistHistory || !externalSessionId || reattachedRef.current) return;
    reattachedRef.current = true;
    let cancelled = false;
    const restored = chatHistory; // 還原快照（deps=[] 的 closure 正是要這份）
    (async () => {
      try {
        const r = await fetch(
          `/api/agent/tasks?session_id=${encodeURIComponent(externalSessionId)}`,
          { cache: "no-store" });
        if (!r.ok) return;
        const d = await r.json();
        const tasks = (d?.tasks ?? []) as Array<{
          task_id: string; status: string; goal?: string;
          has_terminal_events?: boolean;
        }>;
        const running = tasks.find((t) => t.status === "running");
        const roles = restored.map((m) => m.role);
        const lastPlanIdx = roles.lastIndexOf("build_plan");
        const doneAfter = lastPlanIdx >= 0 &&
          roles.slice(lastPlanIdx).includes("build_done");
        const unresolved = lastPlanIdx >= 0 && !doneAfter;
        const target = running
          ?? (unresolved ? tasks.find((t) => t.status === "finished") : undefined);
        if (!target || cancelled) return;

        const seenCharts = new Set(
          restored.filter((m) => m.role === "chart_inline").map((m) => m.chartNodeId));
        // F2 fix (2026-07-11): 還原的 BUILD PLAN 卡要接回事件流原地更新 —
        // 之前只有獨立進度行在動，計畫卡凍在重載當下（user:「沒有繼續更新」）。
        const planCardId = [...restored].reverse()
          .find((m) => m.role === "build_plan" && m.buildPlan)?.id ?? null;
        const patchPlan = (fn: (rt: Record<string, PhaseRuntimeUI>) => Record<string, PhaseRuntimeUI>,
                           status?: "building" | "done" | "error") => {
          if (planCardId == null) return;
          setChatHistory((prev) => prev.map((m) => {
            if (m.id !== planCardId || !m.buildPlan) return m;
            return { ...m, buildPlan: {
              ...m.buildPlan, runtime: fn({ ...m.buildPlan.runtime }),
              ...(status ? { status } : {}),
            }};
          }));
        };
        let doneSeen = false;
        let ops = 0;
        const progressId = nextId();
        setChatHistory((prev) => [...prev, {
          id: progressId, role: "agent",
          content: running
            ? "[接續] 背景建構進行中——已重新接上進度。"
            : "[接續] 離線期間建構已完成，回放結果…",
        }]);

        const handle = (ev: Record<string, unknown>) => {
          const type = String(ev.type ?? "");
          if (type === "pb_glass_op") {
            ops += 1;
            setChatHistory((prev) => prev.map((m) => m.id === progressId
              ? { ...m, content: `[接續] 建構進行中——第 ${ops} 步（${String(ev.op ?? "")}）` }
              : m));
          } else if (type === "pb_glass_chat") {
            // 計畫卡 phase 進度（phase_update / ff_update）→ 原地更新還原的卡。
            const pu = ev.phase_update as { phase_id?: string; status?: string } | undefined;
            const ff = ev.ff_update as { phase_ids?: string[] } | undefined;
            if (ff && Array.isArray(ff.phase_ids)) {
              patchPlan((rt) => {
                for (const fid of ff.phase_ids ?? []) {
                  rt[String(fid)] = { ...(rt[String(fid)] ?? {}), status: "completed" };
                }
                return rt;
              });
            } else if (pu?.phase_id) {
              const s = String(pu.status ?? "");
              const mapped: PhaseRuntimeUI["status"] =
                ["completed", "handover_take_over"].includes(s) ? "completed"
                : ["failed", "handover_drop"].includes(s) ? "failed"
                : "in_progress";
              patchPlan((rt) => {
                rt[pu.phase_id!] = { ...(rt[pu.phase_id!] ?? {}), status: mapped };
                return rt;
              });
            }
          } else if (type === "pb_glass_chart") {
            const chartSpec = ev.chart_spec as Record<string, unknown> | undefined;
            const nodeId = String(ev.node_id ?? "");
            if (chartSpec && !seenCharts.has(nodeId)) {
              seenCharts.add(nodeId);
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "chart_inline", content: "",
                chartSpec, chartNodeId: nodeId,
              }]);
            }
          } else if (type === "pb_glass_done") {
            if (doneSeen) return; // build_finalized + done 兩發，取一
            doneSeen = true;
            const pj = ev.pipeline_json as { nodes?: unknown[]; edges?: unknown[] } | undefined;
            if (pj && Array.isArray(pj.nodes) && pj.nodes.length > 0) {
              lastChatPipelineRef.current = pj as unknown as Record<string, unknown>;
            }
            const ok = ["finished", "success"].includes(String(ev.status ?? "finished"));
            // 計畫卡收尾：全 phase 標完成 + 卡片轉 done/error 狀態。
            patchPlan((rt) => {
              for (const k of Object.keys(rt)) {
                if (rt[k]?.status === "in_progress" && ok) rt[k] = { ...rt[k], status: "completed" };
              }
              return rt;
            }, ok ? "done" : "error");
            const text = ok
              ? `建構完成 — ${(pj?.nodes ?? []).length} nodes / ${(pj?.edges ?? []).length} edges（背景完成，畫面離線期間照跑）`
              : `建構結束：${String(ev.status ?? "?")}`;
            setChatHistory((prev) => [
              ...prev.map((m) => m.id === progressId ? { ...m, content: "[接續] 建構結果：" } : m),
              { id: nextId(), role: "build_done" as const, content: "",
                buildDone: { text, learned: [], rating: null } },
            ]);
          } else if (type === "error") {
            setChatHistory((prev) => [...prev, {
              id: nextId(), role: "agent",
              content: `建構失敗：${String(ev.message ?? "")}`,
            }]);
          }
        };

        const res = await fetch(
          `/api/agent/tasks/${encodeURIComponent(target.task_id)}/stream`,
          { cache: "no-store" });
        const reader = res.body?.getReader();
        if (!reader) return;
        const decoder = new TextDecoder();
        let buf = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done || cancelled) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            try { handle(JSON.parse(line.slice(5).trim())); } catch { /* skip */ }
          }
        }
      } catch { /* reattach 是加值功能——失敗靜默，本機還原仍完整 */ }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // My Drafts (2026-07-12)：rail/抽屜點草稿 → 插入草稿卡訊息（B 案）。
  const lastDraftNonceRef = useRef(0);
  useEffect(() => {
    if (!insertDraft || insertDraft.nonce === lastDraftNonceRef.current) return;
    lastDraftNonceRef.current = insertDraft.nonce;
    setChatHistory((prev) => [...prev, {
      id: nextId(), role: "draft_card", content: "", draftCard: insertDraft.data,
    }]);
  }, [insertDraft]);

  // 草稿卡「啟用」→ 掃可變欄位候選後接既有 skill_activate 確認卡。
  const enableDraft = useCallback(async (pj: Record<string, unknown>, name: string, nl: string) => {
    let candidates: unknown[] = [];
    try {
      const r = await fetch("/api/pipeline/parameterize", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pipeline_json: pj }),
      });
      if (r.ok) candidates = (await r.json())?.candidates ?? [];
    } catch { /* scan best-effort */ }
    setChatHistory((prev) => [...prev, {
      id: nextId(), role: "skill_activate", content: "",
      skillActivate: {
        slug: null, suggested_name: name, suggested_description: nl,
        pipeline_json: pj,
        param_candidates: candidates as SkillActivateConfirmData["param_candidates"],
      },
    }]);
  }, []);

  // 還原後補回「畫面上這張圖」的 snapshot — 沒有它，重載後說「啟用／改圖」
  // 會被當成沒有圖可用而反問（缺口 D1 的 client 端解法）。
  useEffect(() => {
    if (!persistHistory || lastChatPipelineRef.current) return;
    // Loose cast: the union's published variant has no pipeline_json.
    const pjOf = (m: ChatMessage) =>
      (m.pbPipeline as unknown as { pipeline_json?: { nodes?: unknown[] } } | undefined)?.pipeline_json;
    const last = [...chatHistory].reverse().find((m) => {
      const pj = pjOf(m);
      return Array.isArray(pj?.nodes) && pj.nodes.length > 0;
    });
    if (last) {
      lastChatPipelineRef.current = pjOf(last) as unknown as Record<string, unknown>;
    }
    // 只在還原的初始 render 跑一次。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  // 草稿暫存區 P2 (V78, 2026-07-08): "打開" a draft from /drafts stashes it and
  // navigates here. Load it as the on-screen pipeline so the agent co-designs
  // it via modify-mode: seed the snapshot refs (so「拿掉區帶」/「換機台」reach
  // coordinator_triage as deltas), execute once to render the chart inline,
  // and greet with the adjustable options. Inline card (not Lite Canvas) keeps
  // it robust — modify deltas then render as fresh inline cards too.
  const openDraftFiredRef = useRef(false);
  useEffect(() => {
    if (openDraftFiredRef.current || agentMode === "builder") return;
    let raw: string | null = null;
    try { raw = sessionStorage.getItem("pb:open_draft"); } catch { return; }
    if (!raw) return;
    openDraftFiredRef.current = true;
    try { sessionStorage.removeItem("pb:open_draft"); } catch { /* ignore */ }
    let d: { id?: number; name?: string; nl?: string;
             pipeline_json?: { nodes?: Array<{ id?: string; block_id?: string }> };
             columns?: Record<string, string[]> };
    try { d = JSON.parse(raw); } catch { return; }
    const pj = d.pipeline_json;
    if (!pj || !(pj.nodes?.length)) return;
    // seed modify-mode context
    lastChatPipelineRef.current = pj as unknown as Record<string, unknown>;
    lastChatColumnsRef.current = d.columns ?? null;
    lastSavedDraftSigRef.current = JSON.stringify((pj.nodes ?? []).map((n) => [n.id, n.block_id]));
    sessionIdRef.current = `draft-${d.id ?? "adhoc"}`;
    const title = d.name || d.nl || "草稿";
    void (async () => {
      let card: PbPipelineCardData | null = null;
      try {
        const r = await fetch("/api/pipeline-builder/execute", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pipeline_json: pj }),
        });
        const res = await r.json();
        const data = (res.data ?? res) as { node_results?: Record<string, unknown>; result_summary?: unknown };
        card = {
          type: "pb_pipeline",
          pipeline_json: pj as never,
          node_results: (data.node_results ?? {}) as never,
          result_summary: (data.result_summary ?? null) as never,
          goal: d.nl || title,
        } as PbPipelineCardData;
      } catch { /* execute failed — still greet so the user can drive */ }
      setChatHistory((prev) => [
        ...prev,
        ...(card ? [{ id: nextId(), role: "pb_pipeline" as const, content: "", pbPipeline: card }] : []),
        { id: nextId(), role: "agent" as const,
          content: `已載入草稿「${title}」。想怎麼調直接說 —— 例如「拿掉區帶」「加 tooltip 顯示 lotID」「換成 EQP-05」。` },
      ]);
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Phase 5-UX-3b: session mode — auto-send the seed prompt once when the
  // panel first mounts (from /chat/new?prompt=... flow).
  // Phase 11 v6 — also auto-fires for Skill embed (BuilderLayout passes
  // `initialPrompt` from sessionStorage skill ctx).
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

  const sendMessage = useCallback(async (
    message: string,
    extraContext?: Record<string, unknown>,
  ) => {
    if (!message.trim() || loading) return;

    // Phase 5-UX-5: prepend focus context so LLM knows which node the
    // user's question targets. Focus persists across turns until cleared.
    const focusPrefix = focusedNodeId
      ? `[Focused on ${focusedNodeLabel ?? focusedNodeId} (${focusedNodeId})]\n`
      : "";
    const messageToSend = focusPrefix + message;
    // Track the latest user prompt so design_intent_confirm cards can attach
    // it to themselves; the follow-up "confirm" reply needs the original.
    // 2026-07-05 §2 — 卡片確認後的 re-POST（[intent_confirmed:] / [intent=]
    // prefix）是內部 follow-up：照送後端，但不進訊息流（不重複 user 泡）、
    // 不覆蓋 lastUserPromptRef（原句才是 prompt）。
    const isInternalFollowUp = /^\s*\[(intent_confirmed:|intent=)/.test(message);
    if (!isInternalFollowUp) lastUserPromptRef.current = message;

    setLoading(true);
    setStages([]);
    setLogs([]);
    setHitl(null);
    setTokenIn(0);
    setTokenOut(0);
    setCacheWrite(0);
    setCacheRead(0);
    setGlassProgress(null);
    setReflection({ status: null, amendment: "" });
    setPlanItems([]);
    currentBuildCardIdRef.current = null;
    currentBuildDoneIdRef.current = null;
    setAutoRun({ status: "idle" });
    setInput("");
    setActiveTab("chat");

    if (!isInternalFollowUp) {
      setChatHistory((prev) => [...prev, { id: nextId(), role: "user", content: message }]);
    }
    onUserMessageSent?.(message);

    try {
      // Part B (SPEC_context_engineering): pass user-side state to the agent.
      // Currently `selected_equipment_id` only; future: current_page, last alarm, etc.
      const clientContext: Record<string, unknown> = {};
      // i18n P4 — 對話跟隨 UI 語系（sidecar llm_call/advisor 注入 prompt）。
      clientContext.locale = activeLocale();
      if (selectedEquipment?.equipment_id) {
        clientContext.selected_equipment_id = selectedEquipment.equipment_id;
      }
      // 2026-05-04: caller can attach extra context (e.g. intent_spec from
      // the design intent confirm card) so we don't need to inline JSON
      // into the user_message text.
      if (extraContext) {
        Object.assign(clientContext, extraContext);
      }
      // Phase E3 follow-up: in builder mode, ship the current canvas
      // pipeline_json so the orchestrator can surface declared inputs in
      // the user opening message AND so build_pipeline_live's Glass Box
      // subsession sees the same canvas state.
      // 2026-07-08 (A1 fix): in chat mode there is no canvas, but the last
      // built pb_pipeline card IS the on-screen pipeline — ship it so the G1
      // coordinator_triage presentation fast path can recognise a chart
      // tweak instead of triggering a full rebuild.
      const snapshot = agentMode === "builder"
        ? pipelineSnapshotRef.current
        : lastChatPipelineRef.current;
      const sendSnapshot =
        snapshot &&
        typeof snapshot === "object" &&
        ((snapshot.nodes?.length ?? 0) > 0 || (snapshot.inputs?.length ?? 0) > 0);
      const res = await fetch("/api/agent/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: messageToSend,
          session_id: sessionIdRef.current,
          ...(Object.keys(clientContext).length > 0 ? { client_context: clientContext } : {}),
          // Phase E2: tell backend whether we're in chat or builder context
          // so the orchestrator's mode-aware system prompt section kicks in.
          mode: agentMode,
          ...(sendSnapshot ? { pipeline_snapshot: snapshot } : {}),
          ...(sendSnapshot && agentMode !== "builder" && lastChatColumnsRef.current
            ? { pipeline_columns: lastChatColumnsRef.current } : {}),
        }),
      });

      if (!res.ok) {
        addLog(makeLog("❌", `Agent error: ${res.status}`, "error"));
        return;
      }

      const handleStreamEvent = (ev: Record<string, unknown>) => {
        const type = ev.type as string;

        // Agent Console: every SSE event may carry console signal — the
        // normaliser understands both chat (pb_glass_*) and raw builder
        // shapes so the two surfaces stay identical.
        try {
          if (type === "pb_glass_start") {
            consoleDispatch({ t: "start" });
            memoryWritesRef.current = [];
          } else if (type === "pb_glass_done") {
            consoleDispatch({ t: "done", status: String(ev.status ?? "finished") });
          } else {
            normalizeConsoleEvent(ev).forEach((a) => {
              if (a.t === "event" && a.ev.kind === "write" && a.ev.write) {
                memoryWritesRef.current.push(a.ev.write.code);
              }
              // 2026-07-05 — BUILD PLAN 卡的拒 n / 修復後通過 chip 由
              // agent_console 側訊號驅動（chat/builder 同一來源）。
              if (a.t === "event" && (a.ev.kind === "verdict_reject" || a.ev.kind === "repair_start")) {
                const cardId = currentBuildCardIdRef.current;
                const pid = a.ev.phaseId;
                const isReject = a.ev.kind === "verdict_reject";
                if (cardId != null && pid) {
                  setChatHistory((prev) => prev.map((m) => {
                    if (m.id !== cardId || !m.buildPlan) return m;
                    const rt = { ...m.buildPlan.runtime };
                    const cur: PhaseRuntimeUI = rt[pid] ?? { status: "in_progress" };
                    rt[pid] = isReject
                      ? { ...cur, rejects: (cur.rejects ?? 0) + 1 }
                      : { ...cur, repair: true };
                    return { ...m, buildPlan: { ...m.buildPlan, runtime: rt } };
                  }));
                }
              }
              consoleDispatch(a);
            });
          }
        } catch { /* console rendering must never break the chat stream */ }

        switch (type) {
          case "role_marker": {
            // Agent-loop live role banner: Director orchestrates, Planner
            // plans, Builder builds. Shows who is active during a long build.
            const role = String(ev.role ?? "");
            const text = String(ev.text ?? "");
            setActiveRole(role ? { role, text } : null);
            addLog(makeLog("[·]", `${role}｜${text}`, "tool"));
            break;
          }

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
            break;
          }

          case "thinking":
            addLog(makeLog("💭", `${((ev.text as string) ?? "").slice(0, 200)}`, "thinking"));
            break;

          case "llm_usage": {
            const inTok  = (ev.input_tokens  as number) ?? 0;
            const outTok = (ev.output_tokens as number) ?? 0;
            const ccw    = (ev.cache_creation_input_tokens as number) ?? 0;
            const crd    = (ev.cache_read_input_tokens     as number) ?? 0;
            setTokenIn((p)  => p + inTok);
            setTokenOut((p) => p + outTok);
            setCacheWrite((p) => p + ccw);
            setCacheRead((p)  => p + crd);
            addLog(makeLog("🔢", `LLM #${ev.iteration ?? "?"} in=${inTok} out=${outTok} cache(w=${ccw} r=${crd})`, "token"));
            break;
          }

          case "glass_usage": {
            // Phase 2-A: Glass Box subagent's per-LLM-call usage. Same
            // accumulation as llm_usage so the chat-panel counter reflects
            // the real total cost, not just the outer chat turns.
            const inTok  = (ev.input_tokens  as number) ?? 0;
            const outTok = (ev.output_tokens as number) ?? 0;
            const ccw    = (ev.cache_creation_input_tokens as number) ?? 0;
            const crd    = (ev.cache_read_input_tokens     as number) ?? 0;
            setTokenIn((p)  => p + inTok);
            setTokenOut((p) => p + outTok);
            setCacheWrite((p) => p + ccw);
            setCacheRead((p)  => p + crd);
            addLog(makeLog("🔢", `Glass turn ${ev.turn ?? "?"} in=${inTok} out=${outTok} cache(w=${ccw} r=${crd})`, "token"));
            break;
          }

          case "glass_progress": {
            setGlassProgress({
              turn_used: (ev.turn_used as number) ?? 0,
              turn_budget: (ev.turn_budget as number) ?? 50,
              percent: (ev.percent as number) ?? 0,
              warning: !!ev.warning,
            });
            break;
          }

          case "advisor_answer": {
            // 2026-05-02: Builder Mode Block Advisor — chat orchestrator
            // routed an EXPLAIN/COMPARE/RECOMMEND/AMBIGUOUS intent to the
            // advisor graph; the markdown reply lands here. We render it
            // as an `agent` chat message (not a special role) so it flows
            // with the conversation; the kindLabel prefix tells the user
            // it's a structured Q&A response, not a generic chat.
            const kindLabels: Record<string, string> = {
              explain: t("advisorExplain"),
              compare: t("advisorCompare"),
              recommend: t("advisorRecommend"),
              ambiguous: t("advisorAmbiguous"),
              compare_failed: t("advisorCompareFailed"),
              error: t("advisorError"),
            };
            const kind = (ev.kind as string) || "answer";
            const md = (ev.markdown as string) || "";
            const label = kindLabels[kind] ?? "";
            const body = label ? `**${label}**\n\n${md}` : md;
            setChatHistory((prev) => [...prev, {
              id: nextId(), role: "agent", content: body,
            }]);
            break;
          }

          case "design_intent_confirm": {
            // SPEC_design_intent_confirm: agent decided the prompt is too
            // ambiguous to translate directly into a pipeline. Show the
            // structured intent for the user to confirm / edit / cancel.
            const design: DesignIntentData = {
              card_id: (ev.card_id as string) ?? `intent-${Date.now()}`,
              inputs: (ev.inputs as DesignIntentData["inputs"]) ?? [],
              logic: (ev.logic as string) ?? "",
              presentation: (ev.presentation as DesignIntentData["presentation"]) ?? "mixed",
              alternatives: (ev.alternatives as DesignIntentData["alternatives"]) ?? [],
              clarifications: (ev.clarifications as DesignIntentData["clarifications"]) ?? [],
              plan_steps: (ev.plan_steps as DesignIntentData["plan_steps"]) ?? [],
              interactive_brief: (ev.interactive_brief as boolean) ?? false,
              resolved: false,
            };
            setChatHistory((prev) => [...prev, {
              id: nextId(), role: "design_intent", content: "",
              designIntent: design,
              designIntentPrompt: lastUserPromptRef.current,
            }]);
            break;
          }

          case "clarify": {
            // Part A: agent-side intent classifier flagged the query as vague.
            // Render a quick-pick card; user click re-submits with [intent=<id>] prefix.
            const question = (ev.question as string) ?? t("clarifyQuestionFallback");
            const options = (ev.options as ClarifyOption[]) ?? [];
            const fallbackLabel = (ev.fallback_label as string | undefined)
                || (ev.fallbackLabel as string | undefined)
                || t("clarifyFallbackAll");
            // Find most recent user message in this turn for re-submit.
            let originalMessage = "";
            setChatHistory((prev) => {
              for (let i = prev.length - 1; i >= 0; i--) {
                if (prev[i].role === "user") { originalMessage = prev[i].content; break; }
              }
              return [...prev, {
                id: nextId(), role: "clarify", content: "",
                clarify: { question, options, fallbackLabel, originalMessage, resolved: false },
              }];
            });
            break;
          }

          case "plan": {
            // 2026-07-05 §2 — 計畫 todo 卡自訊息流移除（與 BUILD PLAN 卡
            // 合併為單卡生命週期）。planItems state 仍更新：LiteCanvas
            // overlay 透過 onPlanItemsChange 繼續收到 relay。
            const items = ev.items as PlanItem[] | undefined;
            if (Array.isArray(items)) {
              setPlanItems(items.map((it) => ({ ...it })));
              break;
            }
            // Legacy — free-text plan from LLM <plan>...</plan> reasoning
            const planText = (ev.text as string) ?? "";
            if (planText) {
              addLog(makeLog("📋", `Plan: ${planText.slice(0, 200)}`, "info"));
            }
            break;
          }
          case "plan_update": {
            const id = ev.id as string;
            const status = ev.status as PlanItem["status"];
            const note = ev.note as string | undefined;
            setPlanItems((prev) => prev.map((it) =>
              it.id === id ? { ...it, status: status ?? it.status, note: note ?? it.note } : it,
            ));
            break;
          }

          case "tool_start": {
            // Use params_summary (human-readable) if available, else fallback to raw JSON
            const ps = (ev.params_summary as string) ?? "";
            const toolName = (ev.tool as string) ?? "";
            const displayLabel = ps ? `${toolName}(${ps})` : toolName;
            addLog(makeLog("🔧", displayLabel, "tool"));
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
            // 2026-05-23: dropped "draft mcp" handling — /admin/mcps page
            // removed in dead-code cleanup; no listener for the
            // admin:fill_mcp event / sessionStorage stash remains.
            if (card?.type === "navigate") {
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
            } else if (card?.type === "automation_handoff") {
              // 草稿暫存區 P3b (redesigned): hand off to the Skill-Library
              // automate page — no fabricated config, consistent UX.
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "automation_confirm", content: "",
                automationConfirm: {
                  pipeline_json: (card.pipeline_json ?? {}) as Record<string, unknown>,
                  // F2 (2026-07-10): keep the user's original prompt as the
                  // skill NL — was silently persisted as "" before.
                  goal: lastUserPromptRef.current.replace(/^\s*\[[^\]]*\]\s*/, "").trim(),
                },
              }]);
            } else if (card?.type === "skill_admin_confirm") {
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "skill_admin", content: "",
                skillAdmin: card as unknown as SkillAdminData,
              }]);
            } else if (card?.type === "knowledge_admin_confirm") {
              // 知識管理 (2026-07-12): 刪除/停用規則 — browser-side write on confirm.
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "knowledge_admin", content: "",
                knowledgeAdmin: card as unknown as KnowledgeAdminData,
              }]);
            } else if (card?.type === "memory_remember_confirm") {
              // Memory v1 (2026-07-12): 記偏好 — 索引行可編，確認才寫入。
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "memory_remember", content: "",
                memoryRemember: card as unknown as MemoryRememberData,
              }]);
            } else if (card?.type === "draft_card") {
              // My Drafts (2026-07-12): agent 出草稿卡 — 動作全在卡上由使用者按。
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "draft_card", content: "",
                draftCard: card as unknown as DraftCardData,
              }]);
            } else if (card?.type === "alarm_action_confirm") {
              // Alarm 處理 (2026-07-10): browser-side write on user confirm.
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "alarm_action", content: "",
                alarmAction: card as unknown as AlarmActionData,
              }]);
            } else if (card?.type === "skill_activate_confirm") {
              // F4 (2026-07-10): activation is a confirm-card write — the
              // browser performs create/rename/activate only on 確認.
              const sa = card as unknown as SkillActivateConfirmData;
              if (!sa.suggested_description) {
                sa.goal = lastUserPromptRef.current.replace(/^\s*\[[^\]]*\]\s*/, "").trim();
              }
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "skill_activate", content: "", skillActivate: sa,
              }]);
            } else if (card?.type === "pb_pipeline" || card?.type === "pb_pipeline_published") {
              const pbCard = card as unknown as PbPipelineCardData;
              // A1 fix: remember the freshest ad-hoc pipeline so a chat
              // follow-up can ship it as the triage snapshot + its columns.
              if (pbCard.type === "pb_pipeline" && (pbCard.pipeline_json?.nodes?.length ?? 0) > 0) {
                lastChatPipelineRef.current =
                  pbCard.pipeline_json as unknown as Record<string, unknown>;
                lastChatColumnsRef.current = columnsFromNodeResults(pbCard.node_results);
                // 草稿暫存區 (V78): auto-park ONLY a standalone fresh build.
                // In Lite Canvas / session mode this render_card is a modify
                // DELTA (a tweak), and Lite Canvas fresh builds are already
                // saved via pb_glass_done — so don't create a draft per tweak.
                if (!liteCanvasActive && mode !== "session") {
                  const sig = JSON.stringify(
                    (pbCard.pipeline_json?.nodes ?? []).map((n) => [n.id, n.block_id]));
                  if (sig !== lastSavedDraftSigRef.current) {
                    lastSavedDraftSigRef.current = sig;
                    void autoSaveDraft(
                      pbCard.pipeline_json as unknown as Record<string, unknown>,
                      lastChatColumnsRef.current,
                      (pbCard.goal || lastUserPromptRef.current).replace(/^\s*\[[^\]]*\]\s*/, "").trim(),
                    );
                  }
                }
              }
              // Thread the user's original prompt (intent prefix stripped) so
              // 存為 Skill records it as the skill's NL instead of losing it.
              if (pbCard.type === "pb_pipeline" && !pbCard.goal) {
                pbCard.goal = lastUserPromptRef.current
                  .replace(/^\s*\[[^\]]*\]\s*/, "")  // drop [intent_confirmed:…] / [intent=…] prefix
                  .trim();
              }
              const sessionMode = mode === "session" && onPipelineUpdate;
              if (sessionMode) {
                // Phase 5-UX-3b session mode: canvas lives in host — just notify
                // + leave a compact chip in chat so the user sees what changed.
                onPipelineUpdate(pbCard);
              }
              if ((sessionMode || liteCanvasActive) && pbCard.type === "pb_pipeline") {
                // 2026-07-08 modify-mode fix: a delta result arrives as a
                // pb_pipeline render_card (NOT pb_run_done), so the Lite Canvas
                // "結果" tab was never refreshed — the user saw the OLD chart and
                // thought the edit failed. Push the new results into the overlay
                // so「拿掉區帶」/「改虛線」visibly update in place.
                if (liteCanvasActive && pbCard.result_summary) {
                  onPipelineResult?.(pbCard.result_summary, pbCard.node_results ?? {});
                }
                // issue#1 (2026-07-08): the DAG/charts already live in the Lite
                // Canvas / host canvas — but the ad-hoc pipeline still needs its
                // 存為 Skill / Edit-in-Builder actions (otherwise D-class
                // parameterize is untestable from Lite Canvas). Render a COMPACT
                // card (header + ActionBar, no duplicate charts) instead of a
                // bare text chip.
                setChatHistory((prev) => [...prev, {
                  id: nextId(),
                  role: "pb_pipeline",
                  content: "",
                  pbPipeline: pbCard,
                  pbCompact: true,
                }]);
              } else if ((sessionMode || liteCanvasActive) && pbCard.type === "pb_pipeline_published") {
                // Published-skill invoke has no save action — keep the chip.
                const chipText = t("skillExecuted", { name: pbCard.skill_name ?? pbCard.slug ?? "" });
                setChatHistory((prev) => [...prev, {
                  id: nextId(),
                  role: "agent",
                  content: chipText,
                }]);
              } else {
                // True standalone (no Lite Canvas, no session host) — render
                // full card inline so the user can still inspect the result.
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
            // 草稿描述修正 (2026-07-12)：park 草稿時用 build goal，不用
            // lastUserPromptRef — build 期間使用者的追問（如「啟用成 skill」）
            // 曾被誤存成草稿描述。
            if (goal) lastBuildGoalRef.current = goal;
            onGlassStart?.({ session_id: ev.session_id as string, goal, base_pipeline: ev.base_pipeline });
            // 2026-07-05 — 新 build 只重置 plan-todo ref 與 done-card ref。
            // BUILD PLAN 卡 id 不清：resume（plan confirm）會再收到一次
            // pb_glass_start，此時卡已存在且必須原地變身而非另開新卡。
            // 敘事泡（「正在建立 pipeline…」）已移除 — 卡片 chip 表達狀態。
            currentBuildDoneIdRef.current = null;
            setAutoRun({ status: "idle" });
            break;
          }
          case "pb_glass_op": {
            const op = ev.op as string;
            const args = (ev.args as Record<string, unknown>) ?? {};
            const result = (ev.result as Record<string, unknown>) ?? {};
            onGlassOp?.({ op, args, result });
            // 2026-07-05 — ops log 自對話移除（歸 Console 分頁）。這裡只餵
            // BUILD PLAN 卡的進行中 meta：`r{n}/32 · last: add_node → n3`，
            // 讓卡片持續有「還活著」的訊號（含空 round 後的下一動）。
            const pid = args._phase_id != null ? String(args._phase_id) : null;
            const rnd = Number(args._round);
            const tgt = String(
              (args.node_id as string)
              ?? (args.block_name as string)
              ?? (args.to_node as string)
              ?? (args.block_id as string)
              ?? "",
            );
            if (pid && currentBuildCardIdRef.current != null) {
              const targetId = currentBuildCardIdRef.current;
              setChatHistory((prev) => prev.map((m) => {
                if (m.id !== targetId || !m.buildPlan) return m;
                const rt = { ...m.buildPlan.runtime };
                const cur: PhaseRuntimeUI = rt[pid] ?? { status: "in_progress" };
                rt[pid] = {
                  ...cur,
                  status: cur.status === "completed" || cur.status === "failed" ? cur.status : "in_progress",
                  rounds: Number.isFinite(rnd) ? rnd : cur.rounds,
                  lastOp: tgt ? `${op} → ${tgt.slice(0, 24)}` : op,
                };
                return { ...m, buildPlan: { ...m.buildPlan, runtime: rt } };
              }));
            }
            break;
          }
          case "pb_glass_chat": {
            const content = (ev.content as string) ?? "";
            onGlassChat?.({ content });

            // 2026-05-20 — goal_plan_proposed (v30 ReAct) carries a
            // structured `plan` payload alongside the text. Render as a
            // PlanRenderer card (same look as the v1.7 todo card) and
            // mutate phases live via `plan_confirmed` / `phase_update`
            // payloads on subsequent pb_glass_chat events. If any of these
            // structured fields are present we suppress the text bubble to
            // avoid showing the same plan twice (text + card).
            const planPayload = ev.plan as {
              summary?: string;
              phases?: Array<{
                id?: string; goal?: string; expected?: string; auto_injected?: boolean;
              }>;
            } | undefined;
            const planConfirmed = ev.plan_confirmed as { auto?: boolean; n_phases?: number } | undefined;
            const phaseUpdate = ev.phase_update as {
              phase_id?: string;
              status?: string;
              rationale?: string;
              reason?: string;
              alternative?: string;
            } | undefined;

            if (planPayload && Array.isArray(planPayload.phases) && planPayload.phases.length > 0) {
              const gp: GoalPhase[] = planPayload.phases.map((p) => ({
                id: String(p.id ?? ""),
                goal: String(p.goal ?? ""),
                expected: (["raw_data", "transform", "verdict", "chart", "table", "scalar", "alarm"]
                  .includes(String(p.expected)) ? String(p.expected) : "transform") as GoalPhase["expected"],
              }));
              // 單卡生命週期：confirm-gate 已建卡 → 原地更新 phases；
              // auto-confirm 路徑（沒經過 pb_plan_confirm）→ 這裡建卡，
              // 直接進入建構中狀態。
              const existing = currentBuildCardIdRef.current;
              if (existing != null) {
                setChatHistory((prev) => prev.map((m) =>
                  m.id === existing && m.buildPlan
                    ? { ...m, buildPlan: {
                        ...m.buildPlan, phases: gp,
                        summary: planPayload.summary || m.buildPlan.summary,
                      }}
                    : m,
                ));
              } else {
                const newId = nextId();
                currentBuildCardIdRef.current = newId;
                setChatHistory((prev) => [...prev, {
                  id: newId, role: "build_plan", content: "",
                  buildPlan: {
                    sessionId: sessionIdRef.current ?? "",
                    summary: planPayload.summary || undefined,
                    phases: gp, status: "building", runtime: {},
                  },
                }]);
              }
              break;
            }

            // v31.1 — fast-forward: one block covered multiple phases
            const ffUpdate = ev.ff_update as {
              advanced_by_block?: string; advanced_by_node?: string; phase_ids?: string[];
            } | undefined;
            if (ffUpdate && Array.isArray(ffUpdate.phase_ids) && currentBuildCardIdRef.current != null) {
              const targetId = currentBuildCardIdRef.current;
              setChatHistory((prev) => prev.map((m) => {
                if (m.id !== targetId || !m.buildPlan) return m;
                const rt = { ...m.buildPlan.runtime };
                for (const fid of ffUpdate.phase_ids ?? []) {
                  const key = String(fid);
                  rt[key] = {
                    ...(rt[key] ?? {}),
                    status: "completed",
                    result: ffUpdate.advanced_by_block
                      ? `ff: ${ffUpdate.advanced_by_block}${ffUpdate.advanced_by_node ? ` → ${ffUpdate.advanced_by_node}` : ""}`
                      : rt[key]?.result,
                  };
                }
                return { ...m, buildPlan: { ...m.buildPlan, runtime: rt } };
              }));
              break;
            }

            if (planConfirmed && currentBuildCardIdRef.current != null) {
              const targetId = currentBuildCardIdRef.current;
              setChatHistory((prev) => prev.map((m) => {
                if (m.role === "intent_confirm") return { ...m, intentCollapsed: true };
                if (m.id !== targetId || !m.buildPlan) return m;
                // 建構正式開始 — 第一個 phase 進行中，卡進 building 狀態。
                const rt = { ...m.buildPlan.runtime };
                const first = m.buildPlan.phases[0];
                if (first && !rt[first.id]) rt[first.id] = { status: "in_progress" };
                return { ...m, buildPlan: { ...m.buildPlan, status: "building", runtime: rt } };
              }));
              break;
            }

            if (phaseUpdate && phaseUpdate.phase_id && currentBuildCardIdRef.current != null) {
              const targetId = currentBuildCardIdRef.current;
              const pid = phaseUpdate.phase_id;
              const rawStatus = phaseUpdate.status ?? "";
              let mapped: PhaseRuntimeUI["status"] = "in_progress";
              let note: string | undefined;
              switch (rawStatus) {
                case "completed":
                case "handover_take_over":
                  mapped = "completed";
                  break;
                case "failed":
                case "handover_drop":
                  mapped = "failed";
                  note = phaseUpdate.reason || undefined;
                  break;
                case "revising":
                  note = phaseUpdate.reason ? t("revisingWithReason", { reason: phaseUpdate.reason }) : t("revising");
                  break;
                case "revising_retry":
                  note = phaseUpdate.alternative ? t("retryStrategyWith", { alternative: phaseUpdate.alternative }) : t("retryStrategy");
                  break;
                default:
                  mapped = "in_progress";
              }
              setChatHistory((prev) => prev.map((m) => {
                if (m.id !== targetId || !m.buildPlan) return m;
                const rt = { ...m.buildPlan.runtime };
                rt[pid] = {
                  ...(rt[pid] ?? {}),
                  status: mapped,
                  note,
                  result: mapped === "completed"
                    ? (phaseUpdate.rationale || rt[pid]?.result)
                    : rt[pid]?.result,
                };
                if (mapped === "completed") {
                  const nxt = m.buildPlan.phases.find((g) => !rt[g.id] || rt[g.id].status === "pending");
                  if (nxt) rt[nxt.id] = { ...(rt[nxt.id] ?? {}), status: "in_progress" };
                }
                return { ...m, buildPlan: { ...m.buildPlan, runtime: rt } };
              }));
              break;
            }

            // 敘事泡不重述卡片操作（§1.4）— 建構中的 free-text 旁白已移除，
            // 內部逐步運作歸 Console 分頁。
            break;
          }

          // v19 (2026-05-14): pb_glass_chart — actual chart_spec from dry_run.
          // After build done, /chat/intent-respond runs the pipeline and emits
          // one of these per chart_spec terminal so chat shows the chart inline.
          case "pb_glass_chart": {
            const chartSpec = ev.chart_spec as Record<string, unknown> | undefined;
            const nodeId = String(ev.node_id ?? "");
            if (chartSpec && typeof chartSpec === "object") {
              setChatHistory((prev) => [...prev, {
                id: nextId(),
                role: "chart_inline",
                content: "",
                chartSpec,
                chartNodeId: nodeId,
              }]);
            }
            break;
          }

          // v19 (2026-05-14): chat-mode build hit intent_confirm_required.
          // Render BulletConfirmCard inline. Same SSE event the chat tool_execute
          // emits for both ChatPanel (standalone /chat/[id]) and AIAgentPanel
          // (Skill Builder right side). User clicks ✓ → POST /api/agent/chat/
          // intent-respond which resumes the paused build.
          case "pb_intent_confirm": {
            const sid = String(
              (ev.session_id as string) || (ev.build_session_id as string) || "",
            );
            const bullets = (ev.bullets as IntentConfirmData["bullets"]) ?? [];
            const reason = (ev.too_vague_reason as string | undefined) || undefined;
            if (bullets.length > 0) {
              setChatHistory((prev) => [...prev, {
                id: nextId(),
                role: "intent_confirm",
                content: "",
                intentConfirm: { session_id: sid, bullets, too_vague_reason: reason },
              }]);
            }
            break;
          }
          // v31 (2026-07-04): chat-mode build paused at goal_plan_confirm_gate.
          // Render PlanConfirmCard (builder-style editable P1..PN); resume via
          // /chat/intent-respond with plan_decision body.
          case "pb_plan_confirm": {
            const phases = (ev.phases as PlanPhase[]) ?? [];
            const chatSid =
              sessionIdRef.current
              || String((ev.session_id as string) || "");
            // Pin the resolved chat sid now so decidePlan has it even if the
            // turn's `done` event is delayed/dropped (agent-loop streaming).
            if (chatSid) sessionIdRef.current = chatSid;
            if (phases.length > 0) {
              const gp: GoalPhase[] = phases.map((p) => ({
                id: p.id,
                goal: p.goal,
                expected: (["raw_data", "transform", "verdict", "chart", "table", "scalar", "alarm"]
                  .includes(String(p.expected)) ? String(p.expected) : "transform") as GoalPhase["expected"],
              }));
              const draftPlan: BuildPlanState = {
                sessionId: chatSid,
                buildSessionId: String((ev.build_session_id as string) || ""),
                summary: (ev.plan_summary as string) || undefined,
                phases: gp,
                removals: (ev.removals as PlanRemoval[]) || [],
                status: "draft",
                runtime: {},
              };
              // 單卡生命週期：goal_plan_proposed 的 plan payload 常比這個
              // pause 事件先到、已建了卡 — 復用同一張原地轉草案，否則會出現
              // 兩張 BUILD PLAN（一張永遠卡在建構中 0/n）。
              const existing = currentBuildCardIdRef.current;
              if (existing != null) {
                setChatHistory((prev) => prev.map((m) =>
                  m.id === existing && m.buildPlan
                    ? { ...m, buildPlan: draftPlan }
                    : m,
                ));
              } else {
                const newId = nextId();
                currentBuildCardIdRef.current = newId;
                setChatHistory((prev) => [...prev, {
                  id: newId, role: "build_plan", content: "", buildPlan: draftPlan,
                }]);
              }
            }
            break;
          }
          // v30.17j — judge_clarify deficit pause card. Sidecar pauses graph
          // when data source returns < 80% of user's count quantifier
          // (e.g. user asked '100 筆' but data has 7). User picks 3-way:
          // continue / replan / cancel; we POST /chat/intent-respond with
          // judge_decision body to resume.
          case "pb_judge_clarify": {
            const jcData: JudgeClarifyData = {
              phase_id: (ev.phase_id as string) ?? "?",
              requested_n: (ev.requested_n as number) ?? 0,
              actual_rows: (ev.actual_rows as number) ?? 0,
              ratio: (ev.ratio as number) ?? 0,
              value_desc: (ev.value_desc as string) ?? "",
              block_id: (ev.block_id as string) ?? "",
            };
            // v30.17j hotfix: phase_verifier emits this event with
            // build_session_id in `session_id` field, but pending_judge is
            // keyed by CHAT session id. Always use sessionIdRef (the chat
            // session) for the POST. Falls back to ev fields only if we
            // somehow lost the ref.
            const chatSid =
              sessionIdRef.current
              || String((ev.session_id as string) || (ev.build_session_id as string) || "");
            setChatHistory((prev) => [...prev, {
              id: nextId(),
              role: "judge_clarify",
              content: "",
              judgeClarify: jcData,
              judgeChatSessionId: chatSid,
            }]);
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
            // 2026-07-05 — 錯誤進 BUILD PLAN 卡（琥珀 ▲ 原因行），不再貼
            // ops entry / 敘事泡。沒有卡（非 build 流程）才退回文字訊息。
            const cardId = currentBuildCardIdRef.current;
            if (cardId != null) {
              setChatHistory((prev) => prev.map((m) =>
                m.id === cardId && m.buildPlan
                  ? { ...m, buildPlan: {
                      ...m.buildPlan, status: "error" as const,
                      errorReason: opName ? t("errorWithOp", { op: opName, msg }) : msg,
                    }}
                  : m,
              ));
            } else {
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "agent", content: t("errorOccurred", { msg }),
              }]);
            }
            break;
          }
          case "pb_glass_done": {
            const summary = ev.summary as string | undefined;
            const doneStatus = (ev.status as string) ?? "finished";
            // v1.4 — stash for the edit-link card later.
            if (ev.pipeline_json) lastBuiltPipelineRef.current = ev.pipeline_json;
            // 2026-07-08 modify-mode fix: a Lite Canvas build completes via
            // pb_glass_done (NOT a pb_pipeline render_card), so the render_card
            // capture below never ran and lastChatPipelineRef stayed null — the
            // next follow-up shipped no snapshot and every edit rebuilt. Capture
            // the built pipeline here too so「拿掉區帶」/「加 tooltip」/「換機台」
            // reach the Coordinator triage as deltas.
            {
              const pjDone = ev.pipeline_json as {
                nodes?: unknown[]; node_results?: Record<string, { preview?: Record<string, { columns?: string[] }> | null }>;
              } | undefined;
              if (doneStatus !== "refused" && doneStatus !== "failed"
                  && (pjDone?.nodes?.length ?? 0) > 0) {
                lastChatPipelineRef.current = pjDone as unknown as Record<string, unknown>;
                // glass_done usually has no node_results; leave columns null so
                // the backend harvests them once (run_modify fallback).
                lastChatColumnsRef.current = pjDone?.node_results
                  ? columnsFromNodeResults(pjDone.node_results) : null;
                // 草稿暫存區 (V78): auto-park this fresh build (dedupe by nodes).
                const sig = JSON.stringify(pjDone?.nodes ?? []);
                if (sig !== lastSavedDraftSigRef.current) {
                  lastSavedDraftSigRef.current = sig;
                  void autoSaveDraft(
                    pjDone as unknown as Record<string, unknown>,
                    lastChatColumnsRef.current,
                    (lastBuildGoalRef.current
                      || lastUserPromptRef.current.replace(/^\s*\[[^\]]*\]\s*/, "")).trim(),
                  );
                }
              }
            }
            onGlassDone?.({
              status: doneStatus,
              summary,
              pipeline_json: ev.pipeline_json,
            });
            // ③ 卡片原地收斂：BUILD PLAN 卡 → 完成 / 中止 / 已取消。
            const cardId = currentBuildCardIdRef.current;
            const cardStatus: BuildPlanState["status"] =
              doneStatus === "refused" ? "cancelled"
              : doneStatus === "failed" ? "error" : "done";
            if (cardId != null) {
              setChatHistory((prev) => prev.map((m) =>
                m.id === cardId && m.buildPlan
                  ? { ...m, buildPlan: {
                      ...m.buildPlan,
                      status: m.buildPlan.status === "error" ? "error" : cardStatus,
                      ...(cardStatus === "error" && summary ? { errorReason: summary } : {}),
                    }}
                  : m,
              ));
            }
            // 完成卡（§3.5）— 只在真的完成時收尾；取消 / 失敗由 plan 卡
            // chip 表達，不再貼卡。
            if (cardStatus === "done") {
              const pj = ev.pipeline_json as { nodes?: unknown[]; edges?: unknown[] } | undefined;
              if (pj && (pj.nodes ?? []).length > 0) {
                // keep the freshest built pipeline for the完成卡's 展開 link
                lastChatPipelineRef.current = pj as unknown as Record<string, unknown>;
              }
              const counts = pj
                ? t("buildDoneCounts", { nodes: (pj.nodes ?? []).length, edges: (pj.edges ?? []).length })
                : "";
              const text = t("buildDone", { counts, summary: summary || t("buildDoneDefaultSummary") });
              // 2026-07-10: a build streams pb_glass_done TWICE
              // (build_finalized + graph done) — we used to append two
              // near-identical完成卡 (user:「多餘又占版面」). One card per
              // build: the second event just refreshes the text (the later
              // one carries node/edge counts).
              const existingId = currentBuildDoneIdRef.current;
              if (existingId != null) {
                setChatHistory((prev) => prev.map((m) =>
                  m.id === existingId && m.buildDone
                    ? { ...m, buildDone: { ...m.buildDone, text } }
                    : m,
                ));
              } else {
                const learned = memoryWritesRef.current;
                const doneId = nextId();
                currentBuildDoneIdRef.current = doneId;
                setChatHistory((prev) => [...prev, {
                  id: doneId, role: "build_done", content: "",
                  buildDone: { text, learned: [...learned], rating: null },
                }]);
              }
            }
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

            break;
          }

          case "memory_write": {
            const content = (ev.fix_rule ?? ev.content ?? "") as string;
            addLog(makeLog("💡", `[${ev.memory_type ?? ev.source ?? "mem"}] ${content.slice(0, 100)}`, "memory"));
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
            setActiveRole(null);   // build/turn finished — drop the role banner
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
            break;
          }

          case "reflection_running":
            setReflection({ status: "running", amendment: "" });
            addLog(makeLog("🔍", "Self-Critique 驗證中…", "info"));
            break;

          case "reflection_pass": {
            // 漂浮「數值已驗證」chip 移除（§2）— build 流程寫進完成卡的
            // ▣ 結果行；非 build 對話（Q&A）維持原 chip。
            const doneId = currentBuildDoneIdRef.current;
            if (doneId != null) {
              setChatHistory((prev) => prev.map((m) =>
                m.id === doneId && m.buildDone
                  ? { ...m, buildDone: { ...m.buildDone, verified: t("valuesVerified") } }
                  : m,
              ));
              setReflection({ status: null, amendment: "" });
            } else {
              setReflection({ status: "pass", amendment: "" });
            }
            addLog(makeLog("✅", "Self-Critique 通過 — 所有數值來源已確認", "info"));
            break;
          }

          case "reflection_amendment": {
            const amendment = (ev.amendment as string) ?? "";
            setReflection({ status: "amendment", amendment });
            if (amendment) {
              setChatHistory((prev) => [
                ...prev,
                { id: nextId(), role: "agent", content: t("autoAmendment", { amendment }) },
              ]);
            }
            addLog(makeLog("⚠️", `Self-Critique 修正: ${amendment.slice(0, 100)}`, "info"));
            break;
          }

          case "done":
            sessionIdRef.current = ev.session_id as string;
            if (ev.session_id) onSessionResolved?.(ev.session_id as string);
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
            const errMsg = (ev.message as string) ?? t("agentErrorGeneric");
            addLog(makeLog("❌", errMsg, "error"));
            setChatHistory((prev) => [...prev, {
              id: nextId(), role: "agent",
              content: errMsg.includes("authentication") || errMsg.includes("api_key") || errMsg.includes("auth_token")
                ? t("llmConnectError")
                : t("agentError", { msg: errMsg }),
            }]);
            break;
          }
        }
      };
      buildStreamHandlerRef.current = handleStreamEvent;
      await consumeSSE(res, handleStreamEvent, (err) => {
        addLog(makeLog("❌", `連線失敗: ${err.message}`, "error"));
      });
    } finally {
      setLoading(false);
      setActiveRole(null);
    }
  }, [loading, onContract, addLog, focusedNodeId, focusedNodeLabel, t]);

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
      if (!payload) { alert(t("promoteMissingData")); return; }
      const title = (payload.title as string) || t("promoteDefaultTitle");
      const name = prompt(t("promoteNamePrompt"), title);
      if (!name) return;
      try {
        const res = await fetch("/api/admin/analysis/promote", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name,
            description: `從 Agent chat promote：${title}`, // i18n-exempt: 存 DB 的 description，非 locale UI
            auto_check_description: title,
            steps_mapping: payload.steps_mapping,
            input_schema: payload.input_schema,
            output_schema: payload.output_schema || [],
          }),
        });
        if (res.ok) {
          alert(t("promoteSaved", { name }));
        } else {
          const err = await res.json().catch(() => ({}));
          alert(t("promoteSaveFailed", { msg: (err as Record<string, string>).message || res.statusText }));
        }
      } catch (e) {
        alert(t("promoteSaveFailed", { msg: e instanceof Error ? e.message : t("unknownError") }));
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
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: "#1a202c" }}>AI Agent</span>
          {contextEquipment && (
            <span style={{
              fontSize: 11,
              padding: "2px 8px",
              background: "var(--pl, #ebf4ff)",
              color: "var(--p, #2b6cb0)",
              borderRadius: 10,
              fontWeight: 500,
            }}>
              {contextEquipment}
            </span>
          )}
        </div>
        {/* 2026-07-05 對話重整 §2 — header token 統計移除；成本歸 Console
            分頁的 per-agent 成本 footer。 */}

        {/* SPEC_glassbox_continuation §B — live Glass Box turn counter shown
            above the plan card. Goes orange at 70%, red at 90%. Hidden when
            no Glass Box build is active. */}
        {glassProgress && (
          <div style={{
            fontSize: 11,
            color: glassProgress.percent >= 90 ? "#c53030" : glassProgress.warning ? "#c05621" : "#4a5568",
            background: glassProgress.percent >= 90 ? "#fed7d7" : glassProgress.warning ? "#feebc8" : "#edf2f7",
            border: "1px solid",
            borderColor: glassProgress.percent >= 90 ? "#fc8181" : glassProgress.warning ? "#f6ad55" : "#e2e8f0",
            borderRadius: 4,
            padding: "4px 8px",
            marginBottom: 6,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}>
            <span>🔧 Glass Box</span>
            <span style={{ fontFamily: "monospace" }}>
              {glassProgress.turn_used}/{glassProgress.turn_budget} turns ({glassProgress.percent}%)
            </span>
            {glassProgress.warning && (
              <span style={{ fontWeight: 600 }}>· {t("glassNearLimit")}</span>
            )}
          </div>
        )}

        {/* 2026-07-05 對話重整 §2 — header stage 圓點列移除；進度歸
            BUILD PLAN 卡（chip + phase glyph）與 Console 分頁。 */}

        {/* v1.6: Plan Panel moved into the chat tab body so it scrolls with
            the conversation instead of being pinned in the rail header. */}

        {autoRun.status !== "idle" && autoRun.status !== "running" && (
          <div style={{
            margin: "6px 12px 0",
            padding: "6px 10px",
            borderRadius: 6,
            fontSize: 11,
            background: autoRun.status === "error" ? "#fed7d7" : "var(--pl, #ebf4ff)",
            color: autoRun.status === "error" ? "#c53030" : "var(--p, #2b6cb0)",
            border: `1px solid ${autoRun.status === "error" ? "#feb2b2" : "var(--pl, #bee3f8)"}`,
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <span>
              {autoRun.status === "done" && `✓ ${t("autoRunDone")}${autoRun.durationMs ? ` (${autoRun.durationMs} ms)` : ""}`}
              {autoRun.status === "error" && `✕ ${t("autoRunFailed", { error: autoRun.error ?? "" })}`}
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
                background: activeTab === tab ? "var(--pl, #ebf4ff)" : "transparent",
                border: "none",
                borderRadius: "6px 6px 0 0",
                cursor: "pointer",
                fontSize: 12,
                fontWeight: activeTab === tab ? 600 : 400,
                color: activeTab === tab ? "var(--p, #2b6cb0)" : "#718096",
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              {tab === "chat" ? t("tabChat") : t("tabConsole")}
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
          <div style={{ fontSize: 12, color: "#c05621", fontWeight: 600, marginBottom: 4 }}>{t("hitlTitle")}</div>
          <div style={{ fontSize: 12, color: "#744210", marginBottom: 8 }}>{t("hitlTool")}<code>{hitl.tool}</code></div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={() => resolveHitl(hitl.approval_token, true)} style={{ padding: "5px 12px", background: "#c6f6d5", color: "#276749", border: "none", borderRadius: 5, fontSize: 12, cursor: "pointer", fontWeight: 600 }}>{t("approve")}</button>
            <button onClick={() => resolveHitl(hitl.approval_token, false)} style={{ padding: "5px 12px", background: "#fed7d7", color: "#9b2c2c", border: "none", borderRadius: 5, fontSize: 12, cursor: "pointer", fontWeight: 600 }}>{t("reject")}</button>
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
              {t("emptyState")}
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
              {msg.role === "build_plan" && msg.buildPlan ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <BuildPlanCard
                    state={msg.buildPlan}
                    onConfirm={(phases, removals) => void decidePlan(msg.id, true, phases, removals)}
                    onCancel={() => void decidePlan(msg.id, false, [])}
                    onConsoleLink={() => setActiveTab("console")}
                  />
                </div>
              ) : msg.role === "build_done" && msg.buildDone ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <BuildDoneCard
                    state={msg.buildDone}
                    onExpand={onPbPipelineExpand && lastChatPipelineRef.current ? () => {
                      onPbPipelineExpand({
                        type: "pb_pipeline",
                        pipeline_json: lastChatPipelineRef.current,
                        node_results: {},
                      } as unknown as PbPipelineCardData);
                    } : undefined}
                    onRate={(rating) => {
                      setChatHistory((prev) => prev.map((m) =>
                        m.id === msg.id && m.buildDone
                          ? { ...m, buildDone: { ...m.buildDone, rating } }
                          : m,
                      ));
                      void submitFeedback({
                        ...msg,
                        content: msg.buildDone?.text ?? "build done",
                        messageIdx: msg.messageIdx ?? synthesisIdxRef.current,
                      }, rating);
                    }}
                  />
                </div>
              ) : msg.role === "clarify" && msg.clarify ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <ClarifyCard data={msg.clarify} onPick={(intentId) => {
                    setChatHistory((prev) => prev.map((m) =>
                      m.id === msg.id && m.clarify
                        ? { ...m, clarify: { ...m.clarify, resolved: true } }
                        : m,
                    ));
                    const original = msg.clarify?.originalMessage ?? "";
                    if (intentId === "__fallback__") {
                      void sendMessage(original);
                    } else {
                      void sendMessage(`[intent=${intentId}] ${original}`);
                    }
                  }} />
                </div>
              ) : msg.role === "design_intent" && msg.designIntent ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
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
                        // No follow-up — just acknowledge in chat.
                        setChatHistory((prev) => [...prev, {
                          id: nextId(), role: "agent",
                          content: t("designCancelled"),
                        }]);
                        return;
                      }
                      // choice === "confirm" — design may be the original or
                      // user-edited via the inline form. 2026-05-04: spec
                      // travels via client_context.intent_spec instead of
                      // being inlined as JSON in the user_message text, so
                      // the chat history shows only human-readable content.
                      // 2026-05-11: also encode Plan-Mode multi-choice picks
                      // (selections) into the prefix, e.g.
                      // [intent_confirmed:abc scope=all_machines metric=apc] ...
                      // The backend's parse_resolutions_from_prefix reads them
                      // and augment_goal_for_resolutions splices deterministic
                      // guidance hints into the build_pipeline_live goal text.
                      const sel = design.selections ?? {};
                      // Only space-free canonical picks can ride the prefix
                      // (parse_resolutions_from_prefix splits on spaces). 其它
                      // free-text picks contain spaces, so ALL resolutions also
                      // travel structured via client_context.intent_resolutions
                      // (backend merges, client_context wins).
                      const selStr = Object.keys(sel)
                        .filter((k) => sel[k] !== "" && !/\s/.test(sel[k]))
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
                        intent_resolutions: sel,
                      });
                    }}
                  />
                </div>
              ) : msg.role === "chart_inline" && msg.chartSpec ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <div style={{
                    background: "#fff",
                    border: "1px solid #2d3748",
                    borderRadius: 8,
                    padding: 8,
                  }}>
                    {msg.chartNodeId && (
                      <div style={{
                        fontSize: 10, color: "#718096",
                        fontFamily: "monospace", marginBottom: 4,
                      }}>
                        node: {msg.chartNodeId}
                      </div>
                    )}
                    <ChartRenderer spec={msg.chartSpec as Parameters<typeof ChartRenderer>[0]["spec"]} />
                  </div>
                </div>
              ) : msg.role === "intent_confirm" && msg.intentConfirm ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <IntentCard
                      bullets={msg.intentConfirm.bullets}
                      tooVagueReason={msg.intentConfirm.too_vague_reason}
                      resolved={msg.intentConfirm.resolved}
                      collapsed={msg.intentCollapsed}
                      onSubmit={async (confirmations) => {
                        // POST to chat resume; reuse the SAME stream handler
                        // as /chat so pb_glass_* events still apply ops to
                        // canvas + update chat history.
                        const res = await fetch("/api/agent/chat/intent-respond", {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            chatSessionId: msg.intentConfirm?.session_id,
                            confirmations,
                          }),
                        });
                        const handler = buildStreamHandlerRef.current;
                        let finalStatus: "confirmed" | "refused" | "error" = "confirmed";
                        if (handler) {
                          await consumeSSE(res, (ev: Record<string, unknown>) => {
                            handler(ev as Parameters<typeof handler>[0]);
                            const evType = (ev.type as string) || "";
                            if (evType === "pb_glass_done") {
                              const st = ev.status as string;
                              if (st === "refused") finalStatus = "refused";
                              else if (st === "failed") finalStatus = "error";
                            }
                          }, () => {});
                        } else {
                          // No handler available — drain manually
                          try { await res.body?.cancel(); } catch { /* ignore */ }
                        }
                        setChatHistory((prev) => prev.map((m) =>
                          m.id === msg.id && m.intentConfirm
                            ? { ...m, intentConfirm: { ...m.intentConfirm, resolved: finalStatus } }
                            : m,
                        ));
                      }}
                    />
                </div>
              ) : msg.role === "judge_clarify" && msg.judgeClarify ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <JudgeClarifyCard
                    data={msg.judgeClarify}
                    onPick={async (action: JudgeAction) => {
                      const phaseId = msg.judgeClarify?.phase_id;
                      const chatSid = msg.judgeChatSessionId;
                      // Disable buttons + show summary in card
                      setChatHistory((prev) => prev.map((m) =>
                        m.id === msg.id && m.judgeClarify
                          ? { ...m, judgeClarify: { ...m.judgeClarify, resolved: action } }
                          : m,
                      ));
                      try {
                        const res = await fetch("/api/agent/chat/intent-respond", {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            chatSessionId: chatSid,
                            judge_decision: { phase_id: phaseId, action },
                          }),
                        });
                        if (!res.ok) {
                          // Common case: pending_judge already consumed (e.g.
                          // user double-clicked, or another card was acted on
                          // first). Show a small inline note rather than
                          // crashing on the error SSE shape.
                          setChatHistory((prev) => [...prev, {
                            id: nextId(), role: "agent",
                            content: t("judgeSubmitFailed", { status: res.status }),
                          }]);
                          try { await res.body?.cancel(); } catch { /* ignore */ }
                          return;
                        }
                        const handler = buildStreamHandlerRef.current;
                        if (handler) {
                          await consumeSSE(res, (ev: Record<string, unknown>) => {
                            try {
                              handler(ev as Parameters<typeof handler>[0]);
                            } catch (innerErr) {
                              console.error("judge resume event handler crashed", innerErr, ev);
                            }
                          }, (err: Error) => {
                            console.error("judge resume SSE stream error", err);
                          });
                        } else {
                          try { await res.body?.cancel(); } catch { /* ignore */ }
                        }
                      } catch (e) {
                        console.error("judge_clarify resume failed", e);
                        setChatHistory((prev) => [...prev, {
                          id: nextId(), role: "agent",
                          content: t("judgeExecFailed", { msg: e instanceof Error ? e.message : String(e) }),
                        }]);
                      }
                    }}
                  />
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
                  <PbPipelineCard card={msg.pbPipeline} onExpand={onPbPipelineExpand} compact={msg.pbCompact} />
                </div>
              ) : msg.role === "automation_confirm" && msg.automationConfirm ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <AutomationConfirmCard data={msg.automationConfirm} />
                </div>
              ) : msg.role === "skill_activate" && msg.skillActivate ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  {/* 跨裝置一致 (2026-07-12)：處理結果寫回訊息資料 → 隨 rich
                      history 同步 → 別台裝置還原時卡片顯示已處理不可再按。 */}
                  <SkillActivateConfirmCard data={msg.skillActivate}
                    onResolved={(patch) => setChatHistory((prev) => prev.map((m) =>
                      m.id === msg.id && m.skillActivate
                        ? { ...m, skillActivate: { ...m.skillActivate, ...patch } } : m))} />
                </div>
              ) : msg.role === "alarm_action" && msg.alarmAction ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <AlarmActionConfirmCard data={msg.alarmAction}
                    onResolved={(st) => setChatHistory((prev) => prev.map((m) =>
                      m.id === msg.id && m.alarmAction
                        ? { ...m, alarmAction: { ...m.alarmAction, resolved: st } } : m))} />
                </div>
              ) : msg.role === "skill_admin" && msg.skillAdmin ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <SkillAdminConfirmCard data={msg.skillAdmin}
                    onResolved={(st) => setChatHistory((prev) => prev.map((m) =>
                      m.id === msg.id && m.skillAdmin
                        ? { ...m, skillAdmin: { ...m.skillAdmin, resolved: st } } : m))} />
                </div>
              ) : msg.role === "knowledge_admin" && msg.knowledgeAdmin ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <KnowledgeAdminConfirmCard data={msg.knowledgeAdmin}
                    onResolved={(st) => setChatHistory((prev) => prev.map((m) =>
                      m.id === msg.id && m.knowledgeAdmin
                        ? { ...m, knowledgeAdmin: { ...m.knowledgeAdmin, resolved: st } } : m))} />
                </div>
              ) : msg.role === "memory_remember" && msg.memoryRemember ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <MemoryRememberConfirmCard data={msg.memoryRemember}
                    onResolved={(st) => setChatHistory((prev) => prev.map((m) =>
                      m.id === msg.id && m.memoryRemember
                        ? { ...m, memoryRemember: { ...m.memoryRemember, resolved: st } } : m))} />
                </div>
              ) : msg.role === "draft_card" && msg.draftCard ? (
                <div style={{ width: "100%", maxWidth: "100%" }}>
                  <DraftCard data={msg.draftCard}
                    onPatch={(patch) => setChatHistory((prev) => prev.map((m) =>
                      m.id === msg.id && m.draftCard
                        ? { ...m, draftCard: { ...m.draftCard, ...patch } } : m))}
                    onCharts={(charts: TryRunChart[], note: string) =>
                      setChatHistory((prev) => [...prev,
                        { id: nextId(), role: "agent" as const, content: note },
                        ...charts.map((c) => ({
                          id: nextId(), role: "chart_inline" as const, content: "",
                          chartSpec: c.chart_spec, chartNodeId: c.node_id,
                        })),
                      ])}
                    onEnable={(pj, name, nl) => void enableDraft(pj, name, nl)} />
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
                  background: "var(--pn, #f7f8fc)",
                  fontSize: 11, color: "#718096",
                }}>
                                    <span style={{ fontFamily: "monospace", color: "var(--p, #2b6cb0)" }}>{msg.mcpResult.mcp_name}</span>
                  <span>· {t("mcpResultLoaded")}</span>
                </div>
              ) : (
                <>
                  {msg.role === "user" ? (
                    /* §3.1 — 淡色泡 + context tag chip；內部 tag 不顯示 */
                    <div style={userBubbleStyle}>
                      {renderUserContent(msg.content)}
                    </div>
                  ) : (
                    <div style={{
                      maxWidth: "90%",
                      padding: "9px 12px",
                      borderRadius: "12px 12px 12px 2px",
                      fontSize: 13,
                      lineHeight: 1.6,
                      background: "var(--pn, #f7f8fc)",
                      color: "#1a202c",
                      border: msg.role === "agent" ? "1px solid #e2e8f0" : "none",
                    }}>
                      <div style={MD_STYLES} className="md-agent">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            // ChatOps continuity (2026-07-10): agent 回覆常帶
                            // /skills/N、/agent-knowledge 等站內連結；同分頁跳走
                            // 會把進行中的對話換掉 — 一律開新分頁。
                            a: ({ href, children }) => (
                              <a href={href} target="_blank" rel="noreferrer">{children}</a>
                            ),
                          }}
                        >{msg.content}</ReactMarkdown>
                      </div>
                    </div>
                  )}
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
              {activeRole ? (
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 13px", background: "var(--pn, #f7f8fc)", border: "1px solid #e2e8f0", borderRadius: "12px 12px 12px 2px" }}>
                  <span style={{ fontSize: 10.5, fontWeight: 700, color: "#fff", background: ROLE_COLOR[activeRole.role] ?? "#4F46E5", padding: "2px 8px", borderRadius: 6, letterSpacing: 0.3 }}>
                    {activeRole.role}
                  </span>
                  <span style={{ fontSize: 12, color: "#64748B" }}>{activeRole.text}</span>
                </div>
              ) : (
                <div style={{ padding: "10px 14px", background: "var(--pn, #f7f8fc)", border: "1px solid #e2e8f0", borderRadius: "12px 12px 12px 2px", fontSize: 12, color: "#a0aec0" }}>
                  ● ● ●
                </div>
              )}
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
                  : { background: "var(--pl, #ebf4ff)", color: "var(--p, #2b6cb0)", borderColor: "var(--pl, #bee3f8)" }),
              }}>
                {reflection.status === "running" && t("reflectionRunning")}
                {reflection.status === "pass"    && t("reflectionVerified")}
                {reflection.status === "amendment" && t("reflectionAmended")}
              </span>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>
      )}

      {/* Console Tab — agent 視角（Agent Console, 2026-07-04 design handoff） */}
      {activeTab === "console" && (
        <AgentConsole
          state={consoleState}
          memoryEditable={memoryEditable}
          onTeach={({ blockId, phaseId }) => {
            const qs = new URLSearchParams();
            if (blockId) qs.set("prefill_block", blockId);
            if (phaseId) qs.set("prefill_phase", phaseId);
            if (lastUserPromptRef.current) qs.set("prefill_instruction", lastUserPromptRef.current.slice(0, 300));
            window.open(`/agent-knowledge?${qs.toString()}`, "_blank");
          }}
          onOpenMemory={(id) => window.open(`/agent-knowledge?id=${String(id).replace(/^#/, "")}`, "_blank")}
        />
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
              background: "var(--pl, #ede9fe)",
              border: "1px solid var(--pl, #c4b5fd)",
              borderRadius: 12,
              fontSize: 11,
              color: "var(--pd, #4c1d95)",
              fontWeight: 500,
            }}
          >
                        <span>{t("focusedOn", { label: focusedNodeLabel ?? focusedNodeId })}</span>
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
              title={t("clearFocus")}
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
            placeholder={t("inputPlaceholder")}
            disabled={loading}
            rows={3}
            style={{
              flex: 1,
              background: "var(--pn, #f7f8fc)",
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
              background: loading || !input.trim() ? "#e2e8f0" : "var(--p, #2b6cb0)",
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
            {loading ? "…" : t("send")}
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


// Part A — clarify quick-pick card. Inline because it's tightly coupled to
// the AIAgentPanel chat-history shape (ChatMessage.clarify) and only used here.
function ClarifyCard({
  data,
  onPick,
}: {
  data: ClarifyData;
  onPick: (intentId: string) => void;
}) {
  const disabled = !!data.resolved;
  return (
    <div style={{
      width: "100%",
      border: "1px solid #cbd5e0",
      borderRadius: 8,
      padding: "12px 14px",
      background: "#f7fafc",
      fontSize: 13,
      color: "#2d3748",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 600, marginBottom: 8 }}>
        <span>{data.question}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {data.options.map((opt) => (
          <button
            key={opt.id}
            disabled={disabled}
            onClick={() => onPick(opt.id)}
            style={{
              textAlign: "left",
              padding: "8px 10px",
              border: "1px solid #e2e8f0",
              borderRadius: 6,
              background: disabled ? "#edf2f7" : "#ffffff",
              cursor: disabled ? "default" : "pointer",
              opacity: disabled ? 0.6 : 1,
              fontSize: 13,
              color: "#2d3748",
            }}
          >
            <span style={{ fontWeight: 600 }}>{opt.label}</span>
            {opt.preview && (
              <span style={{ marginLeft: 8, color: "#718096", fontSize: 12 }}>
                {opt.preview}
              </span>
            )}
          </button>
        ))}
        {data.fallbackLabel && (
          <button
            disabled={disabled}
            onClick={() => onPick("__fallback__")}
            style={{
              textAlign: "left",
              padding: "6px 10px",
              border: "1px dashed #cbd5e0",
              borderRadius: 6,
              background: "transparent",
              cursor: disabled ? "default" : "pointer",
              opacity: disabled ? 0.6 : 1,
              fontSize: 12,
              color: "#4a5568",
              marginTop: 2,
            }}
          >
            {data.fallbackLabel}
          </button>
        )}
      </div>
    </div>
  );
}
