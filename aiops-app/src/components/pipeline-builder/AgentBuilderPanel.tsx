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
import { applyGlassOp, OP_LABELS, opDetail } from "@/lib/pipeline-builder/glass-ops";
import { PlanRenderer, type PlanItem } from "@/components/copilot/PlanRenderer";
type ChatRole = "user" | "agent" | "op" | "error" | "advisor" | "confirm";
interface ConfirmData {
  session_id: string;
  plan_summary: string;
  /** Phase 10-D: user-facing artifact preview, e.g. ["📈 CUSUM trend", "📦 Box-plot"]. */
  expected_outputs: string[];
  plan_ops: string[];
  n_ops: number;
  resolved: boolean;
}
interface ChatLine {
  id: number;
  role: ChatRole;
  text: string;
  op?: { label: string; detail: string };
  /** Phase 10 (graph_build) — confirm_pending card. */
  confirm?: ConfirmData;
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
  // Synchronous lock so rapid Enter / double-click can't fire a second
  // /api/agent/build before the React `running` state update lands.
  // 2026-05-04: prod logs showed 11 build calls (status=422 + a few 200) in
  // a single second from the same session_id when user mashed Enter; the
  // useState-based guard misses because state updates are async.
  const runningLockRef = useRef(false);
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

  // Shared SSE consumer for /api/agent/build and /api/agent/build/confirm.
  // Both endpoints emit the same v2 graph_build event types; only the
  // request body differs.
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

        if (eventType === "plan_proposed") {
          // Phase 10 (graph_build v2): plan came back from plan_node.
          // Just log a chat note; the visible confirm card is emitted on
          // confirm_pending (only fires for FROM_SCRATCH builds).
          const summary = (data.summary as string) || "";
          const fromScratch = data.from_scratch as boolean;
          if (summary) {
            setLines((p) => [...p, {
              id: nextId(), role: "agent",
              text: fromScratch ? `📋 plan: ${summary}` : `📋 ${summary}`,
            }]);
          }
        } else if (eventType === "plan_validating") {
          // Pure-progress event; usually silent unless errors are present.
          const errors = (data.errors as string[]) ?? [];
          if (errors.length > 0) {
            setLines((p) => [...p, {
              id: nextId(), role: "agent",
              text: `🔧 plan 有 ${errors.length} 個問題，正在修...`,
            }]);
          }
        } else if (eventType === "plan_repaired") {
          const ok = data.ok as boolean;
          const attempt = data.attempt as number;
          const fix = (data.fix_summary as string) || "";
          setLines((p) => [...p, {
            id: nextId(), role: ok ? "agent" : "error",
            text: `${ok ? "🔧" : "✗"} plan repair attempt ${attempt}: ${fix}`,
          }]);
        } else if (eventType === "confirm_pending") {
          // Phase 10: render confirm card with Apply / Cancel buttons.
          const cd: ConfirmData = {
            session_id: (data.session_id as string) || "",
            plan_summary: (data.plan_summary as string) || "(no summary)",
            expected_outputs: (data.expected_outputs as string[]) ?? [],
            plan_ops: (data.plan_ops as string[]) ?? [],
            n_ops: (data.n_ops as number) ?? 0,
            resolved: false,
          };
          setLines((p) => [...p, { id: nextId(), role: "confirm", text: "", confirm: cd }]);
          // Stream pauses here — waiting on user POST to /confirm.
        } else if (eventType === "confirm_received") {
          // Just an ACK; UI already toggled card.resolved.
        } else if (eventType === "op_dispatched") {
          // Could show "running op #N" but it's noisy; defer to op_completed.
        } else if (eventType === "op_completed") {
          // Translate v2 op shape into v1 glass-ops shape so applyGlassOp works.
          const op = (data.op as Record<string, unknown>) || {};
          const result = (data.result as Record<string, unknown>) || {};
          const opType = op.type as string;
          // Build v1-style args dict from v2 op fields.
          const v1Args: Record<string, unknown> = {};
          if (opType === "add_node") {
            v1Args.block_name = op.block_id;
            v1Args.block_version = op.block_version ?? "1.0.0";
            v1Args.params = op.params ?? {};
          } else if (opType === "connect") {
            v1Args.from_node = op.src_id;
            v1Args.from_port = op.src_port;
            v1Args.to_node = op.dst_id;
            v1Args.to_port = op.dst_port;
          } else if (opType === "set_param") {
            const p = (op.params as Record<string, unknown>) || {};
            v1Args.node_id = op.node_id;
            v1Args.key = p.key;
            v1Args.value = p.value;
          } else if (opType === "remove_node") {
            v1Args.node_id = op.node_id;
          }
          applyOperation(opType, v1Args, result);
          const label = OP_LABELS[opType] ?? opType;
          const detail = opDetail(opType, v1Args);
          setLines((p) => [...p, { id: nextId(), role: "op", text: "", op: { label, detail } }]);
        } else if (eventType === "op_error") {
          const op = (data.op as Record<string, unknown>) || {};
          const cursor = data.cursor as number;
          const msg = (op.error_message as string) || "(no msg)";
          setLines((p) => [...p, { id: nextId(), role: "error", text: `op #${cursor} (${op.type}) failed: ${msg}` }]);
        } else if (eventType === "op_repaired") {
          const ok = data.ok as boolean;
          const cursor = data.cursor as number;
          const attempt = data.attempt as number;
          setLines((p) => [...p, {
            id: nextId(), role: ok ? "agent" : "error",
            text: `${ok ? "🔧" : "✗"} op#${cursor} repair attempt ${attempt}`,
          }]);
        } else if (eventType === "build_finalized") {
          const ok = data.ok as boolean;
          const summary = (data.summary as string) || "";
          setLines((p) => [...p, {
            id: nextId(), role: ok ? "agent" : "error",
            text: `${ok ? "✓" : "⚠"} ${summary}`,
          }]);
          // 2026-05-10: surface structural errors prominently. Without this,
          // a build that produced orphan/source-less nodes silently rendered
          // a broken canvas (white-screen risk). Now user sees an explicit
          // error with each issue so they know to retry.
          const structuralErrors = (data.structural_errors as Array<{ rule?: string; message?: string; node_id?: string }>) || [];
          if (structuralErrors.length > 0) {
            const lines = structuralErrors.slice(0, 5).map((e) => {
              const rule = e.rule || "?";
              const node = e.node_id ? ` [${e.node_id}]` : "";
              return `  • ${rule}${node}: ${e.message || "(no message)"}`;
            }).join("\n");
            setLines((p) => [...p, {
              id: nextId(), role: "error",
              text: `❌ Pipeline 結構問題（${structuralErrors.length} 項）— 請重試一次：\n${lines}`,
            }]);
          }
        } else if (eventType === "runtime_check_ok") {
          const n = (data.node_count as number) ?? 0;
          setLines((p) => [...p, { id: nextId(), role: "agent",
            text: `✅ Runtime check：pipeline 跑通（${n} nodes 都 ok）` }]);
        } else if (eventType === "runtime_check_failed") {
          const failures = (data.failures as Array<{ node_id?: string; error?: string }>) ?? [];
          const first = failures[0] || {};
          const nid = first.node_id ?? "?";
          const errMsg = first.error ?? (data.error as string) ?? "(unknown)";
          setLines((p) => [...p, { id: nextId(), role: "error",
            text: `Runtime check 發現問題：node ${nid} — ${String(errMsg).slice(0, 200)}` }]);
        } else if (eventType === "runtime_check_timeout") {
          setLines((p) => [...p, { id: nextId(), role: "agent",
            text: `⏱ Runtime check 超時（>${data.timeout_sec ?? 10}s）— 已建好 pipeline 但無法在 build 階段先驗一遍。` }]);
        } else if (eventType === "runtime_check_skipped") {
          const reason = (data.reason as string) || "unknown";
          setLines((p) => [...p, { id: nextId(), role: "agent",
            text: `⏭ Runtime check 跳過（${reason}）` }]);
        } else if (eventType === "runtime_check_no_data") {
          const msg = (data.message as string) || "pipeline 跑通但沒回任何資料";
          setLines((p) => [...p, { id: nextId(), role: "agent",
            text: `ℹ ${msg}` }]);
        } else if (eventType === "plan") {
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
          // Advisor path didn't touch the canvas — skip the "✓ done" summary.
          // The advisor_answer card is already in the chat column.
          if (data.status === "advisor_done") {
            // no-op
          } else {
            const status = (data.status as string) || "finished";
            const summary = (data.summary as string) || "(done)";
            const finalPj = data.pipeline_json as { nodes?: Array<{ id: string; position?: { x: number; y: number } }> } | null;
            const finalNodeCount = Array.isArray(finalPj?.nodes) ? finalPj!.nodes!.length : 0;

            // 2026-05-12 — earlier the handler always rendered "✓ <summary>" even
            // when build_finalized.ok was false (skill 48 plan_unfixable case →
            // user thought build succeeded but canvas had 0 nodes). Branch on
            // status + node count so failed/empty builds get an explicit ❌.
            const isFailed = status !== "finished" || finalNodeCount === 0;
            if (isFailed) {
              setLines((p) => [...p, {
                id: nextId(), role: "error",
                text: `❌ Build 失敗（${status}）：${summary}．重試一次或調整 instruction。`,
              }]);
              // Don't touch canvas — leave whatever was there before this build.
            } else {
              setLines((p) => [...p, { id: nextId(), role: "agent", text: `✓ ${summary}` }]);
              // Phase 10-D: backend layout_node now ships canvas with positions
              // already laid out, so the frontend dagre pass is gone. If the
              // backend pipeline_json arrived in `done.data.pipeline_json` we
              // can trust those coordinates; the live add_node ops have already
              // applied raw positions which the layout_node-driven final pass
              // overrides via state.pipeline.nodes (BuilderContext keeps the
              // latest write).
              if (finalPj && Array.isArray(finalPj.nodes) && finalPj.nodes.length > 0) {
                const laidOut = currentNodesRef.current.map((n) => {
                  const pj = finalPj.nodes!.find((m) => m.id === n.id);
                  return pj?.position ? { ...n, position: { x: pj.position.x, y: pj.position.y } } : n;
                });
                actions.setNodesAndEdges(laidOut, stateRef.current.pipeline.edges);
              }
            }
          }
        }
      }
    }
  }, [actions, applyOperation]);

  const sendMessage = useCallback(async (raw: string) => {
    // Synchronous lock first — prevents rapid Enter from firing a second
    // request before setRunning(true) commits. See runningLockRef comment.
    if (!raw.trim() || runningLockRef.current) return;
    runningLockRef.current = true;
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
      runningLockRef.current = false;
    }
  }, [focusedNodeId, focusedNodeLabel, basePipelineId, state.pipeline, consumeBuildStream]);

  const handleConfirmPick = useCallback(async (lineId: number, confirmed: boolean) => {
    // Phase 10 (graph_build v2): user replied to plan_proposal at confirm_gate.
    setLines((p) => p.map((l) =>
      l.id === lineId && l.confirm
        ? { ...l, confirm: { ...l.confirm, resolved: true } }
        : l,
    ));
    const card = lines.find((l) => l.id === lineId)?.confirm;
    if (!card) return;
    if (runningLockRef.current && !confirmed) {
      // user just cancels; don't fire request
      setLines((p) => [...p, { id: nextId(), role: "agent", text: "已取消這次 build。" }]);
      return;
    }
    runningLockRef.current = true;
    setRunning(true);
    try {
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      const streamRes = await fetch("/api/agent/build/confirm", {
        method: "POST",
        signal: abortRef.current.signal,
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ sessionId: card.session_id, confirmed }),
      });
      await consumeBuildStream(streamRes);
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setLines((p) => [...p, { id: nextId(), role: "error", text: `Confirm 失敗：${(e as Error).message}` }]);
      }
    } finally {
      setRunning(false);
      runningLockRef.current = false;
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
          l.role === "confirm" && l.confirm ? (
            <ConfirmCard
              key={l.id}
              data={l.confirm}
              onPick={(confirmed) => handleConfirmPick(l.id, confirmed)}
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


/**
 * Phase 10 (graph_build v2) — confirm card. Rendered when sidecar emits
 * confirm_pending after plan_node finishes for a FROM_SCRATCH build.
 *
 * User picks Apply → POST /api/agent/build/confirm {confirmed: true} → graph
 * resumes from interrupt(); UI consumes the resumed SSE stream (op_dispatched,
 * op_completed, build_finalized, done).
 */
function ConfirmCard({
  data,
  onPick,
}: {
  data: ConfirmData;
  onPick: (confirmed: boolean) => void;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-start" }}>
      <div style={{
        maxWidth: "95%",
        padding: "12px 14px",
        borderRadius: "12px 12px 12px 2px",
        fontSize: 13,
        background: "#fef9c3",
        color: "#1a202c",
        border: "1.5px dashed #ca8a04",
        lineHeight: 1.55,
      }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: "#854d0e", marginBottom: 6 }}>
          🛑 等你確認 — 即將建 {data.n_ops} 個 op
        </div>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>{data.plan_summary}</div>
        {data.expected_outputs.length > 0 && (
          <div style={{ marginBottom: 10, padding: "8px 10px", background: "#fef3c7",
                        borderRadius: 6, border: "1px solid #fcd34d" }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#78350f", marginBottom: 4 }}>
              📊 跑完會看到
            </div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "#3f3f46" }}>
              {data.expected_outputs.map((s, i) => <li key={i}>{s}</li>)}
            </ul>
          </div>
        )}
        <details style={{ marginBottom: 10 }}>
          <summary style={{ fontSize: 11, fontWeight: 600, color: "#52525b", cursor: "pointer" }}>
            ▶ 建構 ops（{data.n_ops} 個）
          </summary>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 12, color: "#3f3f46" }}>
            {data.plan_ops.slice(0, 12).map((s, i) => <li key={i}>{s}</li>)}
            {data.plan_ops.length > 12 && (
              <li style={{ color: "#71717a" }}>… +{data.plan_ops.length - 12} more</li>
            )}
          </ul>
        </details>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => onPick(true)}
            disabled={data.resolved}
            style={{
              background: data.resolved ? "#e5e7eb" : "#16a34a",
              color: data.resolved ? "#9ca3af" : "#fff",
              border: "none",
              borderRadius: 6,
              padding: "6px 14px",
              fontSize: 12,
              fontWeight: 600,
              cursor: data.resolved ? "not-allowed" : "pointer",
            }}
          >
            {data.resolved ? "已決定" : "Apply"}
          </button>
          <button
            onClick={() => onPick(false)}
            disabled={data.resolved}
            style={{
              background: "transparent",
              color: data.resolved ? "#9ca3af" : "#b91c1c",
              border: `1px solid ${data.resolved ? "#e5e7eb" : "#fca5a5"}`,
              borderRadius: 6,
              padding: "6px 14px",
              fontSize: 12,
              fontWeight: 500,
              cursor: data.resolved ? "not-allowed" : "pointer",
            }}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
