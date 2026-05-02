"use client";

/**
 * AgentBuilderPanel — Glass Box agent for Pipeline Builder.
 *
 * Talks to /api/v1/agent/build — the LLM iteratively adds nodes, connects
 * edges, sets params via tool calls. Each `operation` SSE event is applied to
 * the canvas in real time via BuilderContext actions, so the user sees the
 * DAG grow step-by-step.
 *
 * SSE event types (from agent_builder/orchestrator.py):
 *   - chat           → narrated text message into chat
 *   - operation      → { op, args, result }; dispatch to BuilderContext action
 *   - suggestion_card → proposal card (PR-E3b) — rendered as plain chat here
 *   - error          → inline error bubble
 *   - done           → final { status, pipeline_json, summary }
 */

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useBuilder } from "@/context/pipeline-builder/BuilderContext";
import type { BlockSpec } from "@/lib/pipeline-builder/types";
import { applyGlassOp, OP_LABELS, opDetail, autoLayoutPipeline } from "@/lib/pipeline-builder/glass-ops";
import { PlanRenderer, type PlanItem } from "@/components/copilot/PlanRenderer";
import { ContinuationCard, type ContinuationData, type ContinuationOption } from "@/components/copilot/ContinuationCard";

type ChatRole = "user" | "agent" | "op" | "error" | "continuation" | "advisor";
interface ChatLine {
  id: number;
  role: ChatRole;
  text: string;
  op?: { label: string; detail: string };
  continuation?: ContinuationData;
  /** When role==='advisor' — markdown body + which advisor bucket fired. */
  advisor?: { kind: string; markdown: string; meta?: Record<string, unknown> };
}

interface Props {
  blockCatalog: BlockSpec[];
  /** When editing an existing pipeline, pass its id so agent starts from
   *  current canvas state (server loads pipeline_json from DB). */
  basePipelineId?: number | null;
  /** Phase 5-UX-5: focus chip info propagated from parent. */
  focusedNodeId?: string | null;
  focusedNodeLabel?: string | null;
  onClearFocus?: () => void;
}

let _seq = 0;
const nextId = () => ++_seq;

export default function AgentBuilderPanel({
  blockCatalog,
  basePipelineId,
  focusedNodeId,
  focusedNodeLabel,
  onClearFocus,
}: Props) {
  const { state, actions } = useBuilder();
  const [input, setInput] = useState("");
  const [lines, setLines] = useState<ChatLine[]>([]);
  // v1.4 Plan Panel — agent-emitted todo list, refreshed each send.
  const [planItems, setPlanItems] = useState<PlanItem[]>([]);
  const [running, setRunning] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Local canvas snapshot keyed to this panel, used to reconcile if agent
  // returns a final pipeline_json that diverges from our incremental state.
  const currentNodesRef = useRef(state.pipeline.nodes);
  useEffect(() => { currentNodesRef.current = state.pipeline.nodes; }, [state.pipeline.nodes]);
  // Phase 5-UX-6: keep a live ref to full state so stream handlers always read
  // latest edges when auto-layouting after done.
  const stateRef = useRef(state);
  useEffect(() => { stateRef.current = state; }, [state]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  const applyOperation = useCallback((op: string, args: Record<string, unknown>, result: Record<string, unknown>) => {
    const res = applyGlassOp(op, args, result, actions, blockCatalog);
    if (!res.ok) {
      setLines((p) => [...p, { id: nextId(), role: "error", text: `apply ${op} failed: ${res.error}` }]);
    }
  }, [actions, blockCatalog]);

  // Shared SSE consumer for both /api/agent/build and /api/agent/build/continue.
  // Both endpoints emit the same event types; the only thing that differs
  // upstream is the request body.
  const consumeBuildStream = useCallback(async (streamRes: Response) => {
    if (!streamRes.ok || !streamRes.body) {
      const errText = await streamRes.text().catch(() => "");
      throw new Error(`Agent stream failed (${streamRes.status}): ${errText.slice(0, 160)}`);
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

        let eventType = "message";
        const dataLines: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) eventType = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        const dataStr = dataLines.join("\n");
        let data: Record<string, unknown> = {};
        try { data = dataStr ? JSON.parse(dataStr) : {}; } catch { data = { _raw: dataStr }; }

        if (eventType === "plan") {
          const items = (data.items as PlanItem[]) ?? [];
          setPlanItems(items.map((it) => ({ ...it })));
        } else if (eventType === "plan_update") {
          const id = data.id as string;
          const status = data.status as PlanItem["status"];
          const note = data.note as string | undefined;
          setPlanItems((prev) => prev.map((it) =>
            it.id === id ? { ...it, status: status ?? it.status, note: note ?? it.note } : it,
          ));
        } else if (eventType === "chat") {
          const text = (data.content as string) || "";
          if (text) setLines((p) => [...p, { id: nextId(), role: "agent", text }]);
        } else if (eventType === "operation") {
          const op = data.op as string;
          const args = (data.args as Record<string, unknown>) || {};
          const result = (data.result as Record<string, unknown>) || {};
          applyOperation(op, args, result);
          const label = OP_LABELS[op] ?? op;
          const detail = opDetail(op, args);
          setLines((p) => [...p, { id: nextId(), role: "op", text: "", op: { label, detail } }]);
        } else if (eventType === "continuation_request") {
          // SPEC_glassbox_continuation: agent paused at turn budget, emit a
          // quick-pick card so user can extend / take over / stop.
          const cont: ContinuationData = {
            session_id: data.session_id as string,
            turns_used: (data.turns_used as number) ?? 0,
            ops_count: (data.ops_count as number) ?? 0,
            completed: (data.completed as string[]) ?? [],
            remaining: (data.remaining as string[]) ?? [],
            estimate: (data.estimate as number) ?? 10,
            options: (data.options as ContinuationOption[]) ?? [],
            resolved: false,
          };
          setLines((p) => [...p, { id: nextId(), role: "continuation", text: "", continuation: cont }]);
        } else if (eventType === "advisor_answer") {
          // Builder Mode Block Advisor (2026-05-02) — Q&A path emits a
          // markdown card instead of canvas operations. Don't apply
          // anything to the canvas; just render the answer in the chat
          // column. No auto-layout on done — canvas wasn't touched.
          const kind = (data.kind as string) || "answer";
          const md = (data.markdown as string) || "";
          setLines((p) => [...p, {
            id: nextId(),
            role: "advisor",
            text: "",
            advisor: { kind, markdown: md, meta: data },
          }]);
        } else if (eventType === "error") {
          const msg = (data.message as string) || "(unknown error)";
          setLines((p) => [...p, { id: nextId(), role: "error", text: msg }]);
        } else if (eventType === "done") {
          // Advisor path didn't touch the canvas — skip the "✓ done" summary
          // line and the auto-layout pass. The advisor_answer card is
          // already in the chat column.
          if (data.status === "advisor_done") {
            // no-op
          } else {
            const summary = (data.summary as string) || "(done)";
            setLines((p) => [...p, { id: nextId(), role: "agent", text: `✓ ${summary}` }]);
            // Phase 5-UX-6 (race-fix): defer auto-layout until React commits
            // every queued add_node / connect / rename action.
            const edgesNow = stateRef.current.pipeline.edges;
            requestAnimationFrame(() => {
              const laidOut = autoLayoutPipeline(
                currentNodesRef.current,
                stateRef.current.pipeline.edges,
              );
              if (laidOut.length > 0) {
                actions.setNodesAndEdges(laidOut, stateRef.current.pipeline.edges);
              } else {
                void edgesNow;
              }
            });
          }
        }
      }
    }
  }, [actions, applyOperation]);

  const sendMessage = useCallback(async (raw: string) => {
    if (!raw.trim() || running) return;
    const prompt = focusedNodeId
      ? `[Focused on ${focusedNodeLabel ?? focusedNodeId} (${focusedNodeId})]\n${raw}`
      : raw;
    setInput("");
    setLines((p) => [...p, { id: nextId(), role: "user", text: raw }]);
    setPlanItems([]);
    setRunning(true);

    try {
      // Send snapshot whenever the canvas has *anything* the agent should
      // know about — nodes OR pipeline-level inputs. The wizard hands off
      // with empty nodes but declared inputs (e.g. tool_id), and without
      // those the orchestrator's "Pipeline 已宣告的 inputs" preamble is
      // empty → agent falls back to its prompt-example reference name
      // ($equipment_id) instead of using the actual declared name.
      const hasExistingNodes  = (state.pipeline.nodes?.length ?? 0) > 0;
      const hasDeclaredInputs = (state.pipeline.inputs?.length ?? 0) > 0;
      const sendSnapshot = hasExistingNodes || hasDeclaredInputs;
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      const streamRes = await fetch("/api/agent/build", {
        method: "POST",
        signal: abortRef.current.signal,
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          instruction: prompt,
          pipelineId: basePipelineId ?? null,
          pipelineSnapshot: sendSnapshot ? state.pipeline : null,
        }),
      });
      await consumeBuildStream(streamRes);
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setLines((p) => [...p, { id: nextId(), role: "error", text: `連線失敗：${(e as Error).message}` }]);
      }
    } finally {
      setRunning(false);
    }
  }, [running, focusedNodeId, focusedNodeLabel, basePipelineId, state.pipeline, consumeBuildStream]);

  const handleContinuationPick = useCallback(async (lineId: number, opt: ContinuationOption) => {
    // Mark the card resolved so its buttons disable.
    setLines((p) => p.map((l) =>
      l.id === lineId && l.continuation
        ? { ...l, continuation: { ...l.continuation, resolved: true } }
        : l,
    ));
    // Find the card data so we know which session_id to act on.
    const card = lines.find((l) => l.id === lineId)?.continuation;
    if (!card) return;

    if (opt.id === "takeover") {
      // v1: tell user to keep working in the current builder; partial canvas is
      // already mounted in the hosting page, no navigation needed.
      setLines((p) => [...p, { id: nextId(), role: "agent", text: "你接手吧 — partial canvas 已在此頁面，可直接編輯。" }]);
      return;
    }
    // opt.id === "continue"
    setRunning(true);
    try {
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      const streamRes = await fetch("/api/agent/build/continue", {
        method: "POST",
        signal: abortRef.current.signal,
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          session_id: card.session_id,
          additional_turns: opt.additional_turns ?? card.estimate ?? 20,
        }),
      });
      await consumeBuildStream(streamRes);
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setLines((p) => [...p, { id: nextId(), role: "error", text: `Continue 失敗：${(e as Error).message}` }]);
      }
    } finally {
      setRunning(false);
    }
  }, [lines, consumeBuildStream]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#fff" }}>
      {/* v1.4 — Plan Panel above messages */}
      <PlanRenderer items={planItems} />
      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px 12px 0", display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>
        {lines.length === 0 && (
          <div style={{ color: "#94a3b8", fontSize: 12, textAlign: "center", padding: "24px 16px" }}>
            告訴 Agent 你要建什麼，它會一邊思考一邊把 node 拖到 canvas 上。
            <br />
            例如：「EQP-07 最近 100 次 xbar 趨勢」、「加一個 Rolling Window 檢查連續 3 次 OOC」
          </div>
        )}
        {lines.map((l) => (
          l.role === "continuation" && l.continuation ? (
            <ContinuationCard
              key={l.id}
              data={l.continuation}
              onPick={(opt) => handleContinuationPick(l.id, opt)}
            />
          ) : (
            <MessageRow key={l.id} line={l} />
          )
        ))}
        {running && (
          <div style={{ fontSize: 11, color: "#94a3b8", padding: "4px 8px" }}>● ● ● 工作中…</div>
        )}
        <div ref={chatEndRef} />
      </div>

      {/* Focus chip */}
      {focusedNodeId && (
        <div style={{ padding: "4px 12px 0" }}>
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
              style={{ border: "none", background: "transparent", color: "#6b46c1", cursor: "pointer", fontSize: 12, padding: "0 4px" }}
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* Input */}
      <div style={{ padding: "8px 12px 12px", flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input); }
            }}
            placeholder="告訴 Agent 要建什麼..."
            disabled={running}
            rows={2}
            style={{
              flex: 1,
              background: "#f7f8fc",
              border: "1px solid #e2e8f0",
              borderRadius: 8,
              color: "#1a202c",
              padding: "8px 10px",
              fontSize: 13,
              resize: "none",
              outline: "none",
              fontFamily: "inherit",
            }}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={running || !input.trim()}
            style={{
              background: running || !input.trim() ? "#e2e8f0" : "#2b6cb0",
              color: running || !input.trim() ? "#a0aec0" : "#fff",
              border: "none",
              borderRadius: 8,
              padding: "8px 16px",
              fontSize: 13,
              fontWeight: 600,
              cursor: running || !input.trim() ? "not-allowed" : "pointer",
              height: 52,
            }}
          >
            {running ? "…" : "送出"}
          </button>
        </div>
      </div>
    </div>
  );
}

function MessageRow({ line }: { line: ChatLine }) {
  if (line.role === "user") {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <div style={{ maxWidth: "90%", padding: "8px 12px", borderRadius: "12px 12px 2px 12px", fontSize: 13, background: "#2b6cb0", color: "#fff", whiteSpace: "pre-wrap" }}>
          {line.text}
        </div>
      </div>
    );
  }
  if (line.role === "op" && line.op) {
    return (
      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        <div style={{ maxWidth: "90%", padding: "6px 10px", borderRadius: 6, fontSize: 11, background: "#f0f9ff", color: "#0c4a6e", border: "1px solid #bae6fd", display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 12 }}>🛠</span>
          <span style={{ fontWeight: 600 }}>{line.op.label}</span>
          <span style={{ color: "#475569" }}>{line.op.detail}</span>
        </div>
      </div>
    );
  }
  if (line.role === "error") {
    return (
      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        <div style={{ maxWidth: "90%", padding: "8px 12px", borderRadius: 6, fontSize: 12, background: "#fef2f2", color: "#b91c1c", border: "1px solid #fecaca" }}>
          ⚠ {line.text}
        </div>
      </div>
    );
  }
  if (line.role === "advisor" && line.advisor) {
    // Block Advisor card — markdown body for EXPLAIN / COMPARE / RECOMMEND
    // / AMBIGUOUS responses. Distinct background so users can tell at a
    // glance this is "Q&A about blocks", not "I'm building something on the
    // canvas".
    const kindLabel: Record<string, string> = {
      explain: "📖 Block 說明",
      compare: "⚖️ Block 對比",
      recommend: "💡 Block 推薦",
      ambiguous: "🤔 請再說明",
      compare_failed: "⚠ 對比失敗",
    };
    const label = kindLabel[line.advisor.kind] ?? "Advisor";
    return (
      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        <div style={{
          maxWidth: "95%",
          padding: "10px 14px",
          borderRadius: "12px 12px 12px 2px",
          fontSize: 13,
          background: "#fefce8",
          color: "#1a202c",
          border: "1px solid #fde68a",
          lineHeight: 1.6,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#92400e", marginBottom: 6 }}>
            {label}
          </div>
          <div className="advisor-md">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {line.advisor.markdown}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    );
  }
  // agent default
  return (
    <div style={{ display: "flex", justifyContent: "flex-start" }}>
      <div style={{ maxWidth: "90%", padding: "9px 12px", borderRadius: "12px 12px 12px 2px", fontSize: 13, background: "#f7f8fc", color: "#1a202c", border: "1px solid #e2e8f0", whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
        {line.text}
      </div>
    </div>
  );
}

// OP_LABELS + opDetail moved to @/lib/pipeline-builder/glass-ops
