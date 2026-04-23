"use client";

import { useState, useRef, useCallback, useEffect } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
}

/** Parsed structured commands from agent response */
export interface FillMcpPayload {
  name?: string;
  description?: string;
  is_handoff?: boolean;
  parameters?: Record<string, unknown>;
  usage_example?: string;
  output_description?: string;
}

export interface FillSkillPayload {
  name?: string;
  description?: string;
  mcp_sequence?: string[];
  event_trigger?: string;
  trigger_conditions?: string;
  diagnostic_prompt?: string;
  expected_output?: string;
}

interface Props {
  /** Called when agent returns a <fill_mcp_form> block */
  onFillMcp?: (payload: FillMcpPayload) => void;
  /** Called when agent returns a <fill_skill_form> block */
  onFillSkill?: (payload: FillSkillPayload) => void;
  collapsed?: boolean;
  onToggle?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let _seq = 0;
const nextId = () => ++_seq;

function parseFillCommands(text: string): { mcpFill?: FillMcpPayload; skillFill?: FillSkillPayload } {
  const result: { mcpFill?: FillMcpPayload; skillFill?: FillSkillPayload } = {};
  const mcpMatch = text.match(/<fill_mcp_form>([\s\S]*?)<\/fill_mcp_form>/);
  if (mcpMatch) {
    try { result.mcpFill = JSON.parse(mcpMatch[1].trim()); } catch { /* skip */ }
  }
  const skillMatch = text.match(/<fill_skill_form>([\s\S]*?)<\/fill_skill_form>/);
  if (skillMatch) {
    try { result.skillFill = JSON.parse(skillMatch[1].trim()); } catch { /* skip */ }
  }
  return result;
}

/** Strip XML fill tags from display text */
function stripFillTags(text: string): string {
  return text
    .replace(/<fill_mcp_form>[\s\S]*?<\/fill_mcp_form>/g, "")
    .replace(/<fill_skill_form>[\s\S]*?<\/fill_skill_form>/g, "")
    .trim();
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AdminChatPanel({ onFillMcp, onFillSkill, collapsed = false, onToggle }: Props) {
  const [messages, setMessages]     = useState<ChatMessage[]>([]);
  const [input, setInput]           = useState("");
  const [loading, setLoading]       = useState(false);
  const [pendingFill, setPendingFill] = useState<{ mcp?: FillMcpPayload; skill?: FillSkillPayload } | null>(null);
  const messagesEndRef              = useRef<HTMLDivElement>(null);
  const historyRef                  = useRef<{ role: "user" | "assistant"; content: string }[]>([]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || loading) return;
    const userMsg: ChatMessage = { id: nextId(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    historyRef.current = [...historyRef.current, { role: "user", content: text }];
    setInput("");
    setLoading(true);
    setPendingFill(null);

    const assistantId = nextId();
    setMessages((prev) => [...prev, { id: assistantId, role: "assistant", content: "" }]);

    let fullText = "";
    try {
      const res = await fetch("/api/admin/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: historyRef.current.slice(0, -1) }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          try {
            const ev = JSON.parse(line.slice(5).replace(/^\s/, ""));
            if (ev.type === "text") {
              fullText += ev.text;
              const display = stripFillTags(fullText);
              setMessages((prev) =>
                prev.map((m) => m.id === assistantId ? { ...m, content: display } : m)
              );
            }
          } catch { /* skip */ }
        }
      }

      // Check for fill commands
      const { mcpFill, skillFill } = parseFillCommands(fullText);
      if (mcpFill || skillFill) {
        setPendingFill({ mcp: mcpFill, skill: skillFill });
      }

      historyRef.current = [...historyRef.current, { role: "assistant", content: fullText }];
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setMessages((prev) =>
        prev.map((m) => m.id === assistantId ? { ...m, content: `❌ ${msg}` } : m)
      );
    } finally {
      setLoading(false);
    }
  }, [loading]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  function applyFill() {
    if (pendingFill?.mcp) onFillMcp?.(pendingFill.mcp);
    if (pendingFill?.skill) onFillSkill?.(pendingFill.skill);
    setPendingFill(null);
  }

  const SUGGESTIONS = [
    "幫我設計一個查詢 SPC OOC 後診斷根因的 Skill",
    "新增一個 MCP 可以查詢批次在某個站點的 APC 補償記錄",
    "幫我寫 diagnostic_prompt for SPC OOC skill",
    "現有哪些 MCP 可以用？",
  ];

  return (
    <div style={{
      width: collapsed ? 48 : 340,
      minWidth: collapsed ? 48 : 340,
      height: "100%",
      background: "#0f1117",
      borderLeft: "1px solid #1e2533",
      display: "flex",
      flexDirection: "column",
      transition: "width 0.2s ease, min-width 0.2s ease",
      overflow: "hidden",
      flexShrink: 0,
    }}>
      {/* Header */}
      <div style={{
        padding: collapsed ? "16px 0" : "12px 16px",
        borderBottom: "1px solid #1e2533",
        display: "flex",
        alignItems: "center",
        justifyContent: collapsed ? "center" : "space-between",
        flexShrink: 0,
      }}>
        {!collapsed && (
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#e2e8f0" }}>✨ AI 助理</div>
            <div style={{ fontSize: 10, color: "#4a5568", marginTop: 1 }}>設計 MCP / Skill</div>
          </div>
        )}
        <button onClick={onToggle} style={{
          background: "none", border: "none", cursor: "pointer",
          color: "#4a5568", fontSize: 16, padding: 4,
          display: "flex", alignItems: "center",
        }} title={collapsed ? "展開 AI 助理" : "收合"}>
          {collapsed ? "💬" : "→"}
        </button>
      </div>

      {!collapsed && (
        <>
          {/* Messages */}
          <div style={{ flex: 1, overflowY: "auto", padding: "12px 12px 4px" }}>
            {messages.length === 0 && (
              <div style={{ color: "#4a5568", fontSize: 12, marginBottom: 12 }}>
                <div style={{ marginBottom: 8, color: "#718096" }}>快速問題：</div>
                {SUGGESTIONS.map((s, i) => (
                  <button key={i} onClick={() => sendMessage(s)} style={{
                    display: "block", width: "100%", textAlign: "left",
                    background: "#1a202c", border: "1px solid #2d3748",
                    borderRadius: 4, padding: "6px 10px", marginBottom: 6,
                    color: "#a0aec0", fontSize: 11, cursor: "pointer",
                    lineHeight: 1.4,
                  }}>
                    {s}
                  </button>
                ))}
              </div>
            )}
            {messages.map((msg) => (
              <div key={msg.id} style={{
                marginBottom: 12,
                display: "flex",
                flexDirection: "column",
                alignItems: msg.role === "user" ? "flex-end" : "flex-start",
              }}>
                <div style={{
                  maxWidth: "92%",
                  background: msg.role === "user" ? "#2b4c7e" : "#1a202c",
                  border: `1px solid ${msg.role === "user" ? "#3182ce" : "#2d3748"}`,
                  borderRadius: 6,
                  padding: "7px 11px",
                  fontSize: 12,
                  color: msg.role === "user" ? "#90cdf4" : "#e2e8f0",
                  lineHeight: 1.55,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}>
                  {msg.content || (loading && msg.role === "assistant" ? (
                    <span style={{ color: "#4a5568" }}>▌</span>
                  ) : "")}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Apply Fill Banner */}
          {pendingFill && (
            <div style={{
              margin: "0 12px 8px",
              background: "#1a2c1a",
              border: "1px solid #276749",
              borderRadius: 6,
              padding: "8px 12px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 8,
            }}>
              <span style={{ fontSize: 11, color: "#68d391" }}>
                {pendingFill.mcp ? "✓ MCP 定義已就緒" : "✓ Skill 定義已就緒"}
              </span>
              <button onClick={applyFill} style={{
                background: "#276749", color: "#68d391", border: "none",
                borderRadius: 4, padding: "4px 12px", cursor: "pointer",
                fontSize: 11, fontWeight: 600,
              }}>
                套用到表單
              </button>
            </div>
          )}

          {/* Input */}
          <div style={{ padding: "8px 12px 12px", flexShrink: 0, borderTop: "1px solid #1e2533" }}>
            <div style={{ display: "flex", gap: 6 }}>
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="描述你的需求... (Enter 送出)"
                rows={2}
                style={{
                  flex: 1, background: "#1a202c", border: "1px solid #2d3748",
                  borderRadius: 4, padding: "6px 10px", color: "#e2e8f0",
                  fontSize: 12, resize: "none", fontFamily: "inherit", lineHeight: 1.5,
                  outline: "none",
                }}
              />
              <button
                onClick={() => sendMessage(input)}
                disabled={loading || !input.trim()}
                style={{
                  background: loading || !input.trim() ? "#2d3748" : "#3182ce",
                  color: loading || !input.trim() ? "#4a5568" : "#fff",
                  border: "none", borderRadius: 4, padding: "0 10px",
                  cursor: loading || !input.trim() ? "not-allowed" : "pointer",
                  fontSize: 14, flexShrink: 0,
                }}
              >
                ↑
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
