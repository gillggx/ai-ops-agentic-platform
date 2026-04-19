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
import { applyGlassOp, OP_LABELS, opDetail } from "@/lib/pipeline-builder/glass-ops";
import type { BlockSpec } from "@/lib/pipeline-builder/types";

// Phase 5-UX-6: use the no-provider variant so operations applied via
// useBuilder() target the SAME BuilderContext the canvas renders from.
const BuilderLayoutNoProvider = dynamic(
  () => import("@/components/pipeline-builder/BuilderLayout").then((m) => m.BuilderLayoutNoProvider),
  { ssr: false },
);

export interface GlassEvent {
  kind: "start" | "op" | "chat" | "error" | "done";
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
}

export default function LiveCanvasOverlay(props: Props) {
  return (
    <BuilderProvider>
      <LiveCanvasInner {...props} />
    </BuilderProvider>
  );
}

function LiveCanvasInner({ sessionId, goal, active, events, onClose }: Props) {
  const { actions } = useBuilder();
  const [catalog, setCatalog] = useState<BlockSpec[]>([]);
  const [narration, setNarration] = useState<string>(goal ?? "");
  const processedCountRef = useRef(0);

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
        position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
        zIndex: 1000, background: "#0f172acc",
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
          agentTabContent={<EventLogPanel events={events} active={active} />}
        />
      </div>
    </div>
  );
}

/** Phase 5-UX-6: scrollable Glass Box event log — shows every chat narration +
 *  operation as it streams in, so users can follow the agent's reasoning. */
function EventLogPanel({
  events,
  active,
}: {
  events: GlassEvent[];
  active: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [events]);

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        background: "#0f172a",
        color: "#e2e8f0",
        overflow: "hidden",
        minHeight: 0,
      }}
    >
      {active && (
        <div
          style={{
            padding: "6px 14px",
            borderBottom: "1px solid #334155",
            fontSize: 10,
            color: "#94a3b8",
            display: "flex",
            alignItems: "center",
            gap: 6,
            flexShrink: 0,
          }}
        >
          <span
            style={{
              width: 6, height: 6, borderRadius: "50%", background: "#38bdf8",
              boxShadow: "0 0 8px #38bdf8",
              animation: "pulse 1.2s ease-in-out infinite",
            }}
          />
          <span>AI Agent 工作中</span>
        </div>
      )}
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "10px 12px", display: "flex", flexDirection: "column", gap: 6, fontSize: 12 }}>
        {events.length === 0 && (
          <div style={{ color: "#64748b", textAlign: "center", marginTop: 20 }}>
            等待 Agent 開始…
          </div>
        )}
        {events.map((e, i) => (
          <EventLine key={i} event={e} />
        ))}
      </div>
      <style>{`@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }`}</style>
    </div>
  );
}

function EventLine({ event }: { event: GlassEvent }) {
  if (event.kind === "start") {
    return (
      <div style={{ padding: "6px 10px", background: "#1e293b", borderRadius: 4, color: "#7dd3fc", lineHeight: 1.5 }}>
        <div style={{ fontSize: 10, fontWeight: 600, marginBottom: 2 }}>🎯 目標</div>
        <div>{event.goal || "—"}</div>
      </div>
    );
  }
  if (event.kind === "chat" && event.content) {
    return (
      <div style={{ padding: "6px 10px", background: "#1e293b", borderRadius: 4, color: "#cbd5e1", lineHeight: 1.6 }}>
        <span style={{ color: "#38bdf8", marginRight: 4 }}>💬</span>
        {event.content}
      </div>
    );
  }
  if (event.kind === "op" && event.op) {
    const meta = OP_LABELS[event.op] ?? event.op;
    const detail = opDetail(event.op, event.args ?? {});
    return (
      <div
        style={{
          padding: "5px 10px",
          background: "#0c1729",
          borderLeft: "2px solid #38bdf8",
          borderRadius: 2,
          fontFamily: "ui-monospace, monospace",
          color: "#94a3b8",
        }}
      >
        <div style={{ color: "#f1f5f9", fontWeight: 600, fontSize: 11 }}>
          🛠 {meta}
        </div>
        {detail && (
          <div style={{ fontSize: 10, marginTop: 2, wordBreak: "break-all" }}>{detail}</div>
        )}
      </div>
    );
  }
  if (event.kind === "error") {
    return (
      <div style={{ padding: "6px 10px", background: "#7f1d1d", borderRadius: 4, color: "#fecaca" }}>
        ⚠ {event.message}
      </div>
    );
  }
  if (event.kind === "done") {
    return (
      <div style={{ padding: "8px 10px", background: "#166534", borderRadius: 4, color: "#dcfce7", fontWeight: 500 }}>
        ✓ {event.summary || "完成"}
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
