"use client";

/**
 * v1.6 Lite Canvas Overlay.
 *
 * Replaces the full-screen LiveCanvasOverlay (which embedded the entire
 * BuilderLayout — block library, parameters inspector, toolbar). The
 * lite version shows just the DAG (read-only), driven by the same
 * BuilderProvider + applyGlassOp pipeline so canvas updates are
 * exactly what the real Pipeline Builder would draw. Two tabs:
 *
 *   📐 Canvas — DagCanvas, agent paints into it live
 *   📊 結果 — ResultsBody (alert + evidence + charts), driven by
 *             the auto-run summary the parent forwards in
 *
 * Auto-switch rule: pb_run_done / pb_run_error → flip to Results.
 * Header has a permanent "🛠 開啟編輯" button that hands the current
 * pipeline_json over to /admin/pipeline-builder/new?from=agent via
 * sessionStorage, plus "× 關閉" which collapses the overlay.
 *
 * Sits as position:absolute inside AppShell's sidebar+main wrapper so
 * the right AI Agent rail stays visible and chat keeps working.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { BuilderProvider, useBuilder } from "@/context/pipeline-builder/BuilderContext";
import { listBlocks } from "@/lib/pipeline-builder/api";
import { applyGlassOp, autoLayoutPipeline } from "@/lib/pipeline-builder/glass-ops";
import { type PlanItem } from "./PlanRenderer";
import ResultsBody from "../pipeline-builder/ResultsBody";
// PipelineThemeStyles defines the CSS custom properties (--pb-edge, --pb-ok,
// --pb-accent, …) that DagCanvas + DeletableEdge consume. Without it the edge
// strokes resolve to `unset` → no visible lines.
import PipelineThemeStyles from "../pipeline-builder/PipelineThemeStyles";
import type {
  BlockSpec,
  PipelineResultSummary,
  NodeResult,
} from "@/lib/pipeline-builder/types";

const DagCanvas = dynamic(() => import("@/components/pipeline-builder/DagCanvas"), {
  ssr: false,
});

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

// idle         — overlay not in use
// building     — Glass Box agent is drawing onto the canvas
// build_failed — build hit MAX_TURNS or otherwise stopped without a usable
//                pipeline (no auto-run will fire)
// running      — build done, auto-run in progress
// done         — auto-run completed successfully
// error        — auto-run completed with an error
export type RunPhase = "idle" | "building" | "build_failed" | "running" | "done" | "error";

interface Props {
  sessionId: string;
  goal?: string;
  active: boolean;
  events: GlassEvent[];
  /** Plan items relayed from AIAgentPanel (optional — we don't render them
   *  inside the overlay since the right rail already shows the same list). */
  planItems?: PlanItem[];
  /** Auto-run lifecycle. Drives the pill + auto tab switch. */
  runPhase: RunPhase;
  runError?: string | null;
  durationMs?: number | null;
  /** Auto-run summary + node results — populated when runPhase === "done". */
  summary: PipelineResultSummary | null;
  nodeResults: Record<string, NodeResult>;
  onClose: () => void;
}

export default function LiteCanvasOverlay(props: Props) {
  return (
    <BuilderProvider>
      <Inner {...props} />
    </BuilderProvider>
  );
}

type ActiveTab = "canvas" | "results";

function Inner({
  goal,
  active,
  events,
  runPhase,
  runError,
  durationMs,
  summary,
  nodeResults,
  onClose,
}: Props) {
  const router = useRouter();
  const { state, actions } = useBuilder();
  const [catalog, setCatalog] = useState<BlockSpec[]>([]);
  const [activeTab, setActiveTab] = useState<ActiveTab>("canvas");
  // Track whether the user has manually picked a tab — once they do, we stop
  // auto-switching (so the overlay doesn't yank them away from canvas after
  // they intentionally went back to inspect the DAG).
  const userPickedTabRef = useRef(false);
  const [resultsBadge, setResultsBadge] = useState<"none" | "new">("none");
  const processedCountRef = useRef(0);
  const stateRef = useRef(state);
  useEffect(() => { stateRef.current = state; }, [state]);

  // Load block catalog once (applyGlassOp needs it for port-type validation).
  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        const b = await listBlocks();
        if (!cancel) setCatalog(b);
      } catch {
        /* ignored — applyGlassOp will surface unknown-block errors */
      }
    })();
    return () => { cancel = true; };
  }, []);

  // Initialise canvas empty so DagCanvas has a valid pipeline state.
  useEffect(() => {
    actions.init({
      pipeline: {
        version: "1.0",
        name: goal || "Lite Canvas Session",
        nodes: [],
        edges: [],
        metadata: {},
      },
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Drain glass events into the canvas.
  useEffect(() => {
    if (!catalog.length) return;
    // Stream was reset (parent called resetGlassStream on new build) — start
    // over, otherwise processedCountRef points past the new events forever.
    if (events.length < processedCountRef.current) {
      processedCountRef.current = 0;
    }
    const fresh = events.slice(processedCountRef.current);
    if (fresh.length === 0) return;
    for (const e of fresh) {
      if (e.kind === "start") {
        // New build session — clear the canvas so nodes from a previous
        // build don't leak in alongside the new ones.
        actions.init({
          pipeline: {
            version: "1.0",
            name: e.goal || "Lite Canvas Session",
            nodes: [], edges: [], metadata: {},
          },
        });
      } else if (e.kind === "op" && e.op) {
        applyGlassOp(e.op, e.args ?? {}, e.result ?? {}, actions, catalog);
      } else if (e.kind === "done") {
        const cur = stateRef.current.pipeline;
        if (cur.nodes.length >= 2) {
          const laidOut = autoLayoutPipeline(cur.nodes, cur.edges);
          if (laidOut.length > 0) {
            actions.setNodesAndEdges(laidOut, cur.edges);
          }
        }
      }
    }
    processedCountRef.current = events.length;
  }, [events, catalog, actions]);

  // Auto-switch to Results tab on first transition into a terminal phase.
  // build_failed counts because the user needs to see the failure summary.
  useEffect(() => {
    if (runPhase === "done" || runPhase === "error" || runPhase === "build_failed") {
      setResultsBadge("new");
      if (!userPickedTabRef.current) {
        setActiveTab("results");
      }
    }
  }, [runPhase]);

  // ESC closes
  useEffect(() => {
    const h = (ev: KeyboardEvent) => { if (ev.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const onTabChange = (t: ActiveTab) => {
    userPickedTabRef.current = true;
    setActiveTab(t);
    if (t === "results") setResultsBadge("none");
  };

  const onAutoLayout = () => {
    const cur = stateRef.current.pipeline;
    if (cur.nodes.length < 2) return;
    const laidOut = autoLayoutPipeline(cur.nodes, cur.edges);
    if (laidOut.length > 0) actions.setNodesAndEdges(laidOut, cur.edges);
  };

  const onOpenInBuilder = () => {
    const pipeline_json = stateRef.current.pipeline;
    const nNodes = pipeline_json?.nodes?.length ?? 0;
    const nEdges = pipeline_json?.edges?.length ?? 0;
    // Diagnostic: surface in console so user can paste back what they see.
    console.log("[LiteCanvas] 開啟編輯 clicked", { nNodes, nEdges });
    try {
      sessionStorage.setItem(
        "pb:ephemeral_pipeline",
        JSON.stringify({ pipeline_json, ts: Date.now() }),
      );
      console.log("[LiteCanvas] sessionStorage saved");
    } catch (e) {
      console.warn("[LiteCanvas] sessionStorage failed", e);
      /* fall through to navigation, builder will run wizard */
    }
    console.log("[LiteCanvas] navigating to /admin/pipeline-builder/new?from=agent");
    try {
      router.push("/admin/pipeline-builder/new?from=agent");
    } catch (e) {
      console.error("[LiteCanvas] router.push failed, falling back to location.href", e);
      window.location.href = "/admin/pipeline-builder/new?from=agent";
    }
  };

  const pill = pillFor(runPhase, durationMs);
  // Results tab only available once there's something to show — auto-run
  // result, an explicit error, or a build that gave up part-way.
  const resultsTabDisabled = !(
    runPhase === "done" || runPhase === "error" || runPhase === "build_failed"
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Lite Canvas"
      style={{
        position: "absolute", inset: 0, zIndex: 50,
        background: "rgba(15, 23, 42, 0.30)",
        display: "flex", flexDirection: "column",
      }}
    >
      <div
        style={{
          margin: 12, flex: 1, minHeight: 0,
          background: "#fff", borderRadius: 10,
          boxShadow: "0 8px 24px rgba(15,23,42,0.18)",
          display: "flex", flexDirection: "column", overflow: "hidden",
        }}
      >
        <Header
          goal={goal}
          pill={pill}
          activeTab={activeTab}
          onTabChange={onTabChange}
          resultsTabDisabled={resultsTabDisabled}
          resultsBadge={resultsBadge}
          onOpenInBuilder={onOpenInBuilder}
          onClose={onClose}
        />

        <div style={{ flex: 1, position: "relative", overflow: "hidden", minHeight: 0 }}>
          {/* Canvas tab — render conditionally so DagCanvas only mounts once */}
          <div
            style={{
              position: "absolute", inset: 0,
              display: activeTab === "canvas" ? "block" : "none",
            }}
          >
            <CanvasPane
              blockCatalog={catalog}
              onAutoLayout={onAutoLayout}
              narration={
                runPhase === "running"
                  ? "⏱ 執行中…"
                  : runPhase === "done"
                  ? "✓ Pipeline 已完成 — 可切到「結果」tab 看圖表"
                  : runPhase === "error"
                  ? "✕ 執行失敗 — 切到「結果」tab 看錯誤詳情"
                  : runPhase === "build_failed"
                  ? "✕ 建構未完成 — 切到「結果」tab 看為什麼"
                  : runPhase === "building"
                  ? goal ?? "Agent 正在繪製 pipeline…"
                  : "等待輸入…"
              }
            />
          </div>

          <div
            style={{
              position: "absolute", inset: 0, overflowY: "auto",
              background: "#F8FAFC", padding: 18,
              display: activeTab === "results" ? "block" : "none",
            }}
          >
            {runPhase === "build_failed" ? (
              <FailureView
                message={runError ?? "Agent 沒能完成 pipeline 建構（可能達到最大步數或缺資料）。可在 Pipeline Builder 自己接手。"}
                onOpenInBuilder={onOpenInBuilder}
              />
            ) : runPhase === "error" && runError ? (
              <FailureView
                message={runError}
                onOpenInBuilder={onOpenInBuilder}
              />
            ) : summary ? (
              <>
                <ResultsBody summary={summary} nodeResults={nodeResults} />
                <TakeoverFooter onOpenInBuilder={onOpenInBuilder} />
              </>
            ) : (
              <div style={{ padding: 24, color: "#94A3B8", fontSize: 13, textAlign: "center" }}>
                等待 auto-run 結果…
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Header ─────────────────────────────────────────────────────────────

interface HeaderProps {
  goal?: string;
  pill: { text: string; bg: string; color: string; border: string };
  activeTab: ActiveTab;
  onTabChange: (t: ActiveTab) => void;
  resultsTabDisabled: boolean;
  resultsBadge: "none" | "new";
  onOpenInBuilder: () => void;
  onClose: () => void;
}

function Header({
  goal, pill, activeTab, onTabChange, resultsTabDisabled, resultsBadge,
  onOpenInBuilder, onClose,
}: HeaderProps) {
  return (
    <div
      style={{
        padding: "8px 12px", borderBottom: "1px solid #E5E7EB",
        background: "#F8FAFC",
        display: "flex", alignItems: "center", gap: 12,
      }}
    >
      <div
        style={{
          fontSize: 13, fontWeight: 600, color: "#111827",
          display: "flex", alignItems: "center", gap: 8,
          flexShrink: 0, maxWidth: 280,
        }}
        title={goal}
      >
        📐 Lite Canvas
      </div>
      <span
        style={{
          fontSize: 11, padding: "2px 8px", borderRadius: 12,
          background: pill.bg, color: pill.color, border: `1px solid ${pill.border}`,
          flexShrink: 0,
        }}
      >
        {pill.text}
      </span>

      <div style={{ display: "flex", gap: 4, flex: 1 }}>
        <TabBtn
          active={activeTab === "canvas"}
          onClick={() => onTabChange("canvas")}
          label="📐 Canvas"
        />
        <TabBtn
          active={activeTab === "results"}
          onClick={() => !resultsTabDisabled && onTabChange("results")}
          label="📊 結果"
          disabled={resultsTabDisabled}
          badge={resultsBadge === "new" && activeTab !== "results" ? "NEW" : undefined}
        />
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={onOpenInBuilder}
          style={{
            background: "#fff", color: "#374151",
            border: "1px solid #D1D5DB", padding: "5px 12px",
            fontSize: 11, borderRadius: 5, cursor: "pointer", fontWeight: 500,
          }}
        >
          🛠 開啟編輯
        </button>
        <button
          onClick={onClose}
          style={{
            background: "#fff", color: "#B91C1C",
            border: "1px solid #FECACA", padding: "5px 12px",
            fontSize: 11, borderRadius: 5, cursor: "pointer", fontWeight: 500,
          }}
        >
          × 關閉
        </button>
      </div>
    </div>
  );
}

function TabBtn({
  active, onClick, label, disabled, badge,
}: {
  active: boolean; onClick: () => void; label: string;
  disabled?: boolean; badge?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: "5px 14px", borderRadius: 6, fontSize: 12, fontWeight: 600,
        color: disabled ? "#CBD5E1" : active ? "#1D4ED8" : "#64748B",
        background: active ? "#EFF6FF" : "transparent",
        border: `1px solid ${active ? "#BFDBFE" : "transparent"}`,
        cursor: disabled ? "default" : "pointer",
        display: "inline-flex", alignItems: "center", gap: 6,
      }}
    >
      {label}
      {badge && (
        <span
          style={{
            background: "#FEE2E2", color: "#B91C1C",
            borderRadius: 10, padding: "0 6px", fontSize: 10, fontWeight: 700,
          }}
        >
          {badge}
        </span>
      )}
    </button>
  );
}

// ── Canvas pane ────────────────────────────────────────────────────────

function CanvasPane({
  blockCatalog, onAutoLayout, narration,
}: {
  blockCatalog: BlockSpec[];
  onAutoLayout: () => void;
  narration: string;
}) {
  return (
    <div
      data-pb-theme="light"
      style={{ position: "relative", width: "100%", height: "100%", background: "#FAFAFA" }}
    >
      <PipelineThemeStyles />
      <DagCanvas blockCatalog={blockCatalog} readOnly />
      <button
        onClick={onAutoLayout}
        style={{
          position: "absolute", top: 14, right: 14,
          background: "#fff", border: "1px solid #E5E7EB",
          borderRadius: 5, padding: "5px 12px",
          fontSize: 11, color: "#475569", cursor: "pointer", zIndex: 10,
          boxShadow: "0 1px 2px rgba(15,23,42,0.06)",
        }}
      >
        ⊞ Auto Layout
      </button>
      <div
        style={{
          position: "absolute", bottom: 14, left: 14,
          background: "#fff", border: "1px solid #E5E7EB",
          borderRadius: 6, padding: "6px 10px",
          fontSize: 11, color: "#475569",
          maxWidth: 360,
          boxShadow: "0 1px 2px rgba(15,23,42,0.06)",
        }}
      >
        {narration}
      </div>
    </div>
  );
}

// ── Results pane helpers ───────────────────────────────────────────────

function FailureView({
  message, onOpenInBuilder,
}: {
  message: string; onOpenInBuilder: () => void;
}) {
  return (
    <>
      <div
        style={{
          padding: "12px 14px", borderRadius: 8,
          background: "#FED7D7", color: "#9B2C2C",
          display: "flex", alignItems: "center", gap: 12, marginBottom: 12,
        }}
      >
        <span style={{ fontSize: 24 }}>🚨</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 13, letterSpacing: "0.04em", textTransform: "uppercase" }}>
            EXECUTION FAILED
          </div>
          <div style={{ fontSize: 12, marginTop: 2, opacity: 0.9, lineHeight: 1.5 }}>
            {message}
          </div>
        </div>
      </div>

      <div
        style={{
          background: "#FEF2F2", border: "1px solid #FECACA",
          borderRadius: 8, padding: "12px 14px",
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
        }}
      >
        <div style={{ fontSize: 13, color: "#7F1D1D" }}>
          🛠 <b style={{ color: "#991B1B" }}>不想等 Agent 自動修補？</b>
          <div style={{ fontSize: 12, marginTop: 2 }}>
            在 Pipeline Builder 直接打開這條 pipeline 自己改。
          </div>
        </div>
        <button
          onClick={onOpenInBuilder}
          style={{
            background: "transparent", border: "none",
            color: "#B91C1C", fontWeight: 600, fontSize: 13,
            cursor: "pointer", whiteSpace: "nowrap",
          }}
        >
          在 Pipeline Builder 自己改 →
        </button>
      </div>
    </>
  );
}

function TakeoverFooter({ onOpenInBuilder }: { onOpenInBuilder: () => void }) {
  return (
    <div
      style={{
        marginTop: 14,
        background: "#FFF7ED", border: "1px solid #FDBA74",
        borderRadius: 8, padding: "12px 14px",
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
      }}
    >
      <div style={{ fontSize: 13, color: "#9A3412" }}>
        📝 <b>需要調整這條 pipeline？</b>
        <div style={{ fontSize: 12, marginTop: 2 }}>
          改 chart 樣式、加 filter、換時間範圍…
        </div>
      </div>
      <button
        onClick={onOpenInBuilder}
        style={{
          background: "transparent", border: "none",
          color: "#C2410C", fontWeight: 600, fontSize: 13,
          cursor: "pointer", whiteSpace: "nowrap",
        }}
      >
        在 Pipeline Builder 開啟編輯 →
      </button>
    </div>
  );
}

function pillFor(phase: RunPhase, durationMs: number | null | undefined) {
  switch (phase) {
    case "idle":
      return { text: "尚未開始", bg: "#F9FAFB", color: "#6B7280", border: "#E5E7EB" };
    case "building":
      return { text: "⏱ 建構中…", bg: "#EFF6FF", color: "#1D4ED8", border: "#BFDBFE" };
    case "build_failed":
      return { text: "✕ 建構未完成", bg: "#FEF2F2", color: "#B91C1C", border: "#FECACA" };
    case "running":
      return { text: "⏱ 執行中…", bg: "#EFF6FF", color: "#1D4ED8", border: "#BFDBFE" };
    case "done": {
      const sec = durationMs != null ? `（${(durationMs / 1000).toFixed(1)}s）` : "";
      return { text: `✓ 完成${sec}`, bg: "#ECFDF5", color: "#047857", border: "#A7F3D0" };
    }
    case "error":
      return { text: "✕ 執行失敗", bg: "#FEF2F2", color: "#B91C1C", border: "#FECACA" };
  }
}

