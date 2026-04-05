"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import type { AIOpsReportContract, SuggestedAction } from "aiops-contract";
import { isValidContract, isAgentAction, isHandoffAction } from "aiops-contract";
import { consumeSSE } from "@/lib/sse";
import { ContractCard } from "./ContractCard";
import { ChartIntentRenderer, type ChartIntent } from "./ChartIntentRenderer";
import type { UiRender } from "@/components/McpChartRenderer";
import ReactMarkdown from "react-markdown";

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

interface ChatMessage {
  id: number;
  role: "user" | "agent" | "mcp_result" | "chart_intents";
  content: string;
  contract?: AIOpsReportContract;
  mcpResult?: McpResult;
  chartIntents?: ChartIntent[];
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
  triggerMessage?: string | null;
  onTriggerConsumed?: () => void;
  contextEquipment?: string | null;
  onHandoff?: (mcp: string, params?: Record<string, unknown>) => void;
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

function getContextPrompts(equipment: string | null | undefined): string[] {
  if (equipment) {
    return [
      `分析 ${equipment} 目前狀態`,
      `${equipment} 最近 OOC 原因`,
      `${equipment} 需要排程維護嗎？`,
    ];
  }
  return [
    "目前所有機台狀態如何？",
    "最近有哪些告警事件？",
    "LOT-001 良率分析",
  ];
}

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
// AICopilot
// ---------------------------------------------------------------------------

export function AICopilot({
  onContract,
  triggerMessage,
  onTriggerConsumed,
  contextEquipment,
  onHandoff,
}: Props) {
  const [input, setInput]           = useState("");
  const [loading, setLoading]       = useState(false);
  const [stages, setStages]         = useState<StageState[]>([]);
  const [logs, setLogs]             = useState<LogEntry[]>([]);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [hitl, setHitl]             = useState<HitlRequest | null>(null);
  const [tokenIn, setTokenIn]       = useState(0);
  const [tokenOut, setTokenOut]     = useState(0);
  const [activeTab, setActiveTab]   = useState<"chat" | "console">("chat");
  const [reflection, setReflection] = useState<ReflectionState>({ status: null, amendment: "" });

  const sessionIdRef = useRef<string | null>(null);
  const chatEndRef   = useRef<HTMLDivElement>(null);
  const logsEndRef   = useRef<HTMLDivElement>(null);

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

    setLoading(true);
    setStages([]);
    setLogs([]);
    setHitl(null);
    setTokenIn(0);
    setTokenOut(0);
    setReflection({ status: null, amendment: "" });
    setInput("");
    setActiveTab("chat");

    setChatHistory((prev) => [...prev, { id: nextId(), role: "user", content: message }]);

    try {
      const res = await fetch("/api/agent/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, session_id: sessionIdRef.current }),
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
            const ragHits = (ev.rag_hits as Array<{ id: number; content: string }>) ?? [];
            addLog(makeLog("📦", `CTX | RAG 記憶: ${ev.rag_count ?? 0} 條 | 歷史: ${ev.history_turns ?? 0} 輪`, "info"));
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
            setTokenIn((p)  => p + inTok);
            setTokenOut((p) => p + outTok);
            addLog(makeLog("🔢", `LLM #${ev.iteration ?? "?"} in=${inTok} out=${outTok}`, "token"));
            break;
          }

          case "tool_start": {
            const inputStr = JSON.stringify(ev.input ?? {});
            addLog(makeLog("🔧",
              `${ev.tool ?? ""}(${inputStr.slice(0, 80)}${inputStr.length > 80 ? "…" : ""})`,
              "tool"
            ));
            break;
          }

          case "tool_done": {
            addLog(makeLog("✅", `${ev.tool ?? ""} → ${ev.result_summary ?? ""}`, "tool"));
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
              const mcp_output = card.mcp_output as Record<string, unknown> | undefined;
              const uiRender = mcp_output?.ui_render as UiRender | undefined;
              const hasChart = !!uiRender?.chart_data || (uiRender?.charts?.length ?? 0) > 0;
              if (hasChart) {
                setChatHistory(prev => [...prev, {
                  id: nextId(), role: "mcp_result" as const, content: "",
                  mcpResult: {
                    mcp_name: (card.mcp_name as string) ?? "MCP",
                    uiRender: uiRender!,
                    dataset: (mcp_output?.dataset as unknown[]) ?? [],
                  },
                }]);
              }
            }
            // Unified _chart DSL rendering — from execute_mcp (SPC auto-detect) or execute_jit
            const mcpIntents = card?.chart_intents as ChartIntent[] | undefined;
            const jitIntents = (card?.type === "utility")
              ? ((card.payload as Record<string, unknown> | undefined)?.chart_intents as ChartIntent[] | undefined)
              : undefined;
            const intents = mcpIntents ?? jitIntents;
            if (intents && Array.isArray(intents) && intents.length > 0) {
              setChatHistory(prev => [...prev, {
                id: nextId(), role: "chart_intents" as const,
                content: (card?.mcp_name as string) ?? (card?.tool_name as string) ?? "Chart",
                chartIntents: intents,
              }]);
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
            const text = (ev.text as string) ?? "";
            const displayText = text.replace(/<contract>[\s\S]*?<\/contract>/g, "").trim();
            if (isValidContract(ev.contract)) {
              const contract = ev.contract as AIOpsReportContract;
              onContract?.(contract);
              setChatHistory((prev) => [...prev, {
                id: nextId(), role: "agent",
                content: displayText || contract.summary || "",
                contract,
              }]);
            } else if (displayText) {
              setChatHistory((prev) => [...prev, { id: nextId(), role: "agent", content: displayText }]);
            }
            addLog(makeLog("💬", `Synthesis 完成 (${text.length} chars)`, "info"));
            break;
          }

          case "reflection_running":
            setReflection({ status: "running", amendment: "" });
            addLog(makeLog("🔍", "Stage 5 Self-Critique 驗證數值來源中…", "info"));
            break;

          case "reflection_pass":
            setReflection({ status: "pass", amendment: "" });
            addLog(makeLog("✅", "Self-Critique 通過 — 所有數值來源已確認", "info"));
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
  }, [loading, onContract, addLog]);

  function handleSuggestedAction(action: SuggestedAction) {
    if (isAgentAction(action)) {
      sendMessage(action.message);
    } else if (isHandoffAction(action)) {
      onHandoff?.(action.mcp, action.params);
    }
  }

  const contextPrompts = getContextPrompts(contextEquipment);

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
            <span style={{ fontSize: 14, fontWeight: 700, color: "#1a202c" }}>AI Co-Pilot</span>
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

        {/* Stage dots */}
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
              {msg.role === "chart_intents" && msg.chartIntents ? (
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
                        <ReactMarkdown>{msg.content}</ReactMarkdown>
                      </div>
                    )}
                  </div>
                  {msg.role === "agent" && msg.contract && (
                    <div style={{ maxWidth: "90%", width: "100%" }}>
                      <ContractCard contract={msg.contract} onTrigger={handleSuggestedAction} />
                    </div>
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
          flex: 1, background: "#1a202c", margin: "8px",
          borderRadius: 6, overflowY: "auto",
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

      {/* Quick Prompts */}
      <div style={{ padding: "8px 12px 0", flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {contextPrompts.map((p) => (
            <button
              key={p}
              onClick={() => sendMessage(p)}
              disabled={loading}
              style={{
                padding: "4px 10px",
                background: "#f7f8fc",
                border: "1px solid #e2e8f0",
                borderRadius: 12,
                fontSize: 11,
                color: "#4a5568",
                cursor: loading ? "not-allowed" : "pointer",
                opacity: loading ? 0.5 : 1,
              }}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Input */}
      <div style={{ padding: "8px 12px 12px", flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input); }
            }}
            placeholder="輸入訊息，Enter 送出..."
            disabled={loading}
            rows={2}
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
    </div>
  );
}
