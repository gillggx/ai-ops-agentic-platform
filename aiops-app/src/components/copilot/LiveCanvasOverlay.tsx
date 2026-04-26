"use client";

/**
 * Phase 5-UX-6: Live Glass Box canvas overlay.
 *
 * Mounted by AppShell when the chat agent calls `build_pipeline_live`. Renders a
 * full-viewport BuilderLayout in session mode + a narration strip on top. As
 * `pb_glass_op` events arrive from the parent, they are applied to the embedded
 * BuilderContext via the shared glass-ops util, so the user watches the DAG
 * build node-by-node.
 *
 * When the sub-agent emits `done`, overlay stays open (user can inspect / edit
 * the DAG) but header shows ✓. ESC or × closes.
 */

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { BuilderProvider, useBuilder } from "@/context/pipeline-builder/BuilderContext";
import { listBlocks } from "@/lib/pipeline-builder/api";
import { applyGlassOp, OP_LABELS, opDetail, autoLayoutPipeline } from "@/lib/pipeline-builder/glass-ops";
import { PlanRenderer, type PlanItem } from "./PlanRenderer";
import type { BlockSpec } from "@/lib/pipeline-builder/types";

// Phase 5-UX-6: use the no-provider variant so operations applied via
// useBuilder() target the SAME BuilderContext the canvas renders from.
const BuilderLayoutNoProvider = dynamic(
  () => import("@/components/pipeline-builder/BuilderLayout").then((m) => m.BuilderLayoutNoProvider),
  { ssr: false },
);

export interface GlassEvent {
  kind: "start" | "op" | "chat" | "error" | "done" | "user";
  sessionId?: string;
  goal?: string;
  op?: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  content?: string;
  message?: string;
  status?: string;
  summary?: string;
  pipeline_json?: unknown;
}

interface Props {
  sessionId: string;
  goal?: string;
  active: boolean;
  events: GlassEvent[];
  onClose: () => void;
  /** Phase 5-UX-6: send a follow-up message to the same chat session —
   *  parent wires this to AIAgentPanel so overlay can continue the
   *  conversation in-place (user's next "add histogram" etc.). */
  onSendMessage?: (text: string) => void;
  /** v1.4: live Plan Panel items relayed from AIAgentPanel (chat agent's
   *  update_plan tool emits plan / plan_update SSE events; AppShell wires
   *  them through to here so users see the checklist while the overlay
   *  covers the rest of the AI Agent panel). */
  planItems?: PlanItem[];
}

export default function LiveCanvasOverlay(props: Props) {
  return (
    <BuilderProvider>
      <LiveCanvasInner {...props} />
    </BuilderProvider>
  );
}

function LiveCanvasInner({ sessionId, goal, active, events, onClose, onSendMessage, planItems }: Props) {
  const { state, actions } = useBuilder();
  const [catalog, setCatalog] = useState<BlockSpec[]>([]);
  const [narration, setNarration] = useState<string>(goal ?? "");
  const processedCountRef = useRef(0);
  // Live state ref so event-processing effect can read latest nodes/edges when
  // triggering auto-layout on pb_glass_done (avoids stale closures).
  const stateRef = useRef(state);
  useEffect(() => { stateRef.current = state; }, [state]);

  // Load block catalog once (needed by applyGlassOp)
  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        const b = await listBlocks();
        if (!cancel) setCatalog(b);
      } catch {
        // ignored — applyGlassOp will surface unknown-block errors
      }
    })();
    return () => { cancel = true; };
  }, []);

  // Initialise canvas empty on first mount so BuilderLayout has a valid state.
  useEffect(() => {
    actions.init({
      pipeline: { version: "1.0", name: goal || "Glass Box Session", nodes: [], edges: [], metadata: {} },
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Drain incoming events into canvas + narration. We apply only events we
  // haven't processed yet (tracked via ref) so re-renders don't double-apply.
  useEffect(() => {
    if (!catalog.length) return;  // wait for catalog
    const fresh = events.slice(processedCountRef.current);
    if (fresh.length === 0) return;
    for (const e of fresh) {
      if (e.kind === "op" && e.op) {
        applyGlassOp(e.op, e.args ?? {}, e.result ?? {}, actions, catalog);
      } else if (e.kind === "chat" && e.content) {
        setNarration(e.content);
      } else if (e.kind === "done") {
        setNarration(e.summary ? `✓ ${e.summary}` : "✓ 完成");
        // Phase 5-UX-6: auto-layout the DAG once agent finishes — nodes were
        // added at arbitrary positions via add_node; LR-layout tidies them.
        const cur = stateRef.current.pipeline;
        if (cur.nodes.length >= 2) {
          const laidOut = autoLayoutPipeline(cur.nodes, cur.edges);
          if (laidOut.length > 0) {
            actions.setNodesAndEdges(laidOut, cur.edges);
          }
        }
      } else if (e.kind === "error" && e.message) {
        setNarration(`⚠ ${e.message}`);
      } else if (e.kind === "start" && e.goal) {
        setNarration(e.goal);
      }
    }
    processedCountRef.current = events.length;
  }, [events, catalog, actions]);

  // ESC closes
  useEffect(() => {
    const h = (ev: KeyboardEvent) => { if (ev.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        // v1.5: absolute (not fixed) so the parent in AppShell can confine
        // the overlay to sidebar+main; right AI Agent rail stays visible.
        position: "absolute", inset: 0,
        zIndex: 50, background: "#0f172acc",
        display: "flex", flexDirection: "column",
      }}
    >
      {/* Narration strip — always visible at top */}
      <NarrationStrip active={active} text={narration} sessionId={sessionId} onClose={onClose} />
      {/* Phase 5-UX-6: single consolidated body — BuilderLayout fills the area
          and the event log lives inside the Agent tab (via agentTabContent
          override) so there's only one right-side panel, not two. */}
      <div style={{ flex: 1, background: "#fff", overflow: "hidden", minHeight: 0 }}>
        <BuilderLayoutNoProvider
          mode="session"
          sessionId={sessionId}
          fillViewport={false}
          agentTabContent={
            <GlassChatPanel events={events} active={active} onSendMessage={onSendMessage} planItems={planItems} />
          }
        />
      </div>
    </div>
  );
}

/** Phase 5-UX-6: chat-style Glass Box panel — mirrors AgentBuilderPanel's
 *  look (user blue bubbles, agent light bubbles, op chips) + input at bottom
 *  so the conversation stays continuous inside the overlay. */
function GlassChatPanel({
  events,
  active,
  onSendMessage,
  planItems,
}: {
  events: GlassEvent[];
  active: boolean;
  onSendMessage?: (text: string) => void;
  planItems?: PlanItem[];
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState("");
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [events]);

  const handleSend = () => {
    const t = input.trim();
    if (!t || !onSendMessage || active) return;
    onSendMessage(t);
    setInput("");
  };

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        background: "#fff",
        overflow: "hidden",
        minHeight: 0,
      }}
    >
      {/* v1.4 Plan Panel — relayed from outer chat agent */}
      <PlanRenderer items={planItems ?? []} />
      <div
        ref={scrollRef}
        style={{
          flex: 1, overflowY: "auto", padding: "12px 12px 0",
          display: "flex", flexDirection: "column", gap: 8, minHeight: 0,
        }}
      >
        {events.length === 0 && (
          <div style={{ color: "#94a3b8", fontSize: 12, textAlign: "center", paddingTop: 24 }}>
            等待 Agent 開始…
          </div>
        )}
        {events.map((e, i) => (
          <ChatLine key={i} event={e} />
        ))}
        {active && (
          <div style={{ fontSize: 11, color: "#94a3b8", padding: "4px 8px" }}>
            ● ● ● 工作中…
          </div>
        )}
      </div>

      {/* Follow-up input — user can keep iterating in the same session */}
      <div style={{ padding: "8px 12px 12px", flexShrink: 0, borderTop: "1px solid #e2e8f0" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
            }}
            placeholder={active ? "Agent 還在工作中…" : "告訴 Agent 繼續改進 pipeline…"}
            disabled={!onSendMessage || active}
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
              opacity: !onSendMessage || active ? 0.6 : 1,
            }}
          />
          <button
            onClick={handleSend}
            disabled={!onSendMessage || active || !input.trim()}
            style={{
              background: !onSendMessage || active || !input.trim() ? "#e2e8f0" : "#2b6cb0",
              color: !onSendMessage || active || !input.trim() ? "#a0aec0" : "#fff",
              border: "none",
              borderRadius: 8,
              padding: "8px 16px",
              fontSize: 13,
              fontWeight: 600,
              cursor: !onSendMessage || active || !input.trim() ? "not-allowed" : "pointer",
              height: 52,
            }}
          >
            送出
          </button>
        </div>
      </div>
    </div>
  );
}

function ChatLine({ event }: { event: GlassEvent }) {
  // User message — blue bubble right-aligned
  if (event.kind === "user" && event.content) {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <div
          style={{
            maxWidth: "90%", padding: "8px 12px",
            borderRadius: "12px 12px 2px 12px",
            fontSize: 13, background: "#2b6cb0", color: "#fff",
            whiteSpace: "pre-wrap",
          }}
        >
          {event.content}
        </div>
      </div>
    );
  }

  // Agent narration — gray bubble left
  if (event.kind === "chat" && event.content) {
    return (
      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        <div
          style={{
            maxWidth: "90%", padding: "9px 12px",
            borderRadius: "12px 12px 12px 2px",
            fontSize: 13, background: "#f7f8fc", color: "#1a202c",
            border: "1px solid #e2e8f0", whiteSpace: "pre-wrap", lineHeight: 1.6,
          }}
        >
          {event.content}
        </div>
      </div>
    );
  }

  // Goal (from pb_glass_start) — first-line, slightly highlighted
  if (event.kind === "start" && event.goal) {
    return (
      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        <div
          style={{
            maxWidth: "90%", padding: "6px 10px",
            fontSize: 11, background: "#eef2ff", color: "#4338ca",
            border: "1px solid #c7d2fe", borderRadius: 6,
          }}
        >
          <span style={{ fontWeight: 600, marginRight: 4 }}>🎯 目標</span>
          {event.goal}
        </div>
      </div>
    );
  }

  // Operation — compact blue chip
  if (event.kind === "op" && event.op) {
    const meta = OP_LABELS[event.op] ?? event.op;
    const detail = opDetail(event.op, event.args ?? {});
    return (
      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        <div
          style={{
            maxWidth: "90%", padding: "6px 10px",
            borderRadius: 6, fontSize: 11,
            background: "#f0f9ff", color: "#0c4a6e",
            border: "1px solid #bae6fd",
            display: "flex", alignItems: "center", gap: 6,
          }}
        >
          <span style={{ fontSize: 12 }}>🛠</span>
          <span style={{ fontWeight: 600 }}>{meta}</span>
          {detail && <span style={{ color: "#475569" }}>{detail}</span>}
        </div>
      </div>
    );
  }

  // Error — red bubble
  if (event.kind === "error") {
    return (
      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        <div
          style={{
            maxWidth: "90%", padding: "8px 12px",
            borderRadius: 6, fontSize: 12,
            background: "#fef2f2", color: "#b91c1c",
            border: "1px solid #fecaca",
          }}
        >
          ⚠ {event.message}
        </div>
      </div>
    );
  }

  // Done — green bubble with summary
  if (event.kind === "done") {
    return (
      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        <div
          style={{
            maxWidth: "90%", padding: "8px 12px",
            borderRadius: 6, fontSize: 12,
            background: "#f0fdf4", color: "#166534",
            border: "1px solid #bbf7d0", fontWeight: 500,
          }}
        >
          ✓ {event.summary || "完成"}
        </div>
      </div>
    );
  }

  return null;
}

function NarrationStrip({ active, text, sessionId, onClose }: {
  active: boolean;
  text: string;
  sessionId: string;
  onClose: () => void;
}) {
  return (
    <div
      style={{
        flexShrink: 0,
        height: 44,
        background: active ? "#0c4a6e" : "#1e293b",
        color: "#e0f2fe",
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "0 16px",
        borderBottom: "1px solid #0369a1",
        transition: "background 200ms",
      }}
    >
      <span style={{ fontSize: 14 }}>{active ? "🛠" : "✓"}</span>
      <div style={{ flex: 1, fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {active ? (
          <span>
            <strong>AI Agent 工作中</strong> · <span style={{ opacity: 0.8 }}>{text}</span>
          </span>
        ) : (
          <span>
            <strong>完成</strong> · <span style={{ opacity: 0.8 }}>{text}</span>
          </span>
        )}
      </div>
      <span style={{ fontSize: 10, color: "#7dd3fc", fontFamily: "monospace" }}>
        session {sessionId.slice(0, 8)}
      </span>
      <button
        onClick={onClose}
        title="關閉 canvas (ESC)"
        style={{
          width: 28, height: 28, borderRadius: "50%",
          background: "#fff", border: "none",
          fontSize: 15, cursor: "pointer", color: "#334155",
        }}
      >
        ×
      </button>
    </div>
  );
}
