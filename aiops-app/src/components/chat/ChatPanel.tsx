"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import type { AIOpsReportContract } from "aiops-contract";
import { isValidContract } from "aiops-contract";
import { consumeSSE } from "@/lib/sse";

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
  role: "user" | "agent";
  content: string;
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

  const sendMessage = useCallback(async (message: string) => {
    if (!message.trim() || loading) return;

    setLoading(true);
    setStages([]);
    setLogs([]);
    setHitl(null);
    setTokenIn(0);
    setTokenOut(0);
    setInput("");
    setActiveTab("chat");

    // Add user message to chat history
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
