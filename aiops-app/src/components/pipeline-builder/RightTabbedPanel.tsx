"use client";

/**
 * Phase 5-UX-5: right-side tabbed panel for BuilderLayout.
 *
 * RightTabs: Agent | Parameters | Runs
 *   - Agent      — AIAgentPanel (session / copilot mode, picked by parent)
 *   - Parameters — NodeInspector or EdgeInspector (depending on selection)
 *   - Runs       — execution history (pipeline_runs table; lightweight list)
 */

import { useCallback, useEffect, useState } from "react";
import NodeInspector from "./NodeInspector";
import EdgeInspector from "./EdgeInspector";
import type { BlockSpec, ExecuteResponse } from "@/lib/pipeline-builder/types";
import { useBuilder } from "@/context/pipeline-builder/BuilderContext";
import { listPipelineRuns, type PipelineRunSummary } from "@/lib/pipeline-builder/api";

export type RightTab = "agent" | "parameters" | "runs";

interface Props {
  /** Rendered inside the Agent tab — parent controls session/copilot wiring. */
  agentPanel: React.ReactNode;
  blockCatalog: BlockSpec[];
  readOnly: boolean;
  /** Optional — enables Jump-to-NodeInspector on Inspector focus column events. */
  onAskAgent?: (nodeId: string, text?: string) => void;
  /** Latest run result for the Runs tab. */
  runResult: ExecuteResponse | null;
  /** When a param expects a column from upstream, parent may wire this up. */
  focusedColumnTarget?: string | null;
  /** Phase A — pipelineId for fetching historical pb_pipeline_runs in the
   *  Runs tab. null/undefined for un-saved pipelines (history hidden). */
  pipelineId?: number | null;
  /** Phase 5-UX-5 fix: tab state lifted so parent (BuilderLayout top-bar Ask-
   *  Agent button, NodeInspector "Ask about this") can programmatically
   *  switch to the Agent tab. */
  tab: RightTab;
  setRightTab: (tab: RightTab) => void;
}

export default function RightTabbedPanel({
  agentPanel,
  blockCatalog,
  readOnly,
  onAskAgent,
  runResult,
  pipelineId,
  tab,
  setRightTab,
}: Props) {
  const { selectedNode, selectedEdge } = useBuilder();

  // UX: when user selects a node/edge, auto-switch to Parameters tab (only if
  // user is currently on Agent; never override their own Runs choice).
  // This mirrors the previous inline inspector behavior.
  // Intentionally skip effect-based auto-switch to avoid fighting user intent.

  return (
    <aside
      style={{
        width: 380,
        minWidth: 320,
        maxWidth: "40vw",
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        background: "#fff",
        borderLeft: "1px solid var(--pb-panel-border)",
        overflow: "hidden",
      }}
    >
      <RightTabsBar tab={tab} setRightTab={setRightTab} />
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {tab === "agent" && agentPanel}
        {tab === "parameters" && (
          <div style={{ flex: 1, overflow: "auto", background: "#fff" }}>
            {selectedEdge ? (
              <EdgeInspector blockCatalog={blockCatalog} readOnly={readOnly} />
            ) : selectedNode ? (
              <NodeInspector
                blockCatalog={blockCatalog}
                readOnly={readOnly}
                onAskAgent={onAskAgent}
              />
            ) : (
              <div style={{ padding: 20, fontSize: 12, color: "#94a3b8", textAlign: "center", marginTop: 40 }}>
                先點選 canvas 上的 node / edge 以檢視參數
              </div>
            )}
          </div>
        )}
        {tab === "runs" && <RunsRightTab runResult={runResult} pipelineId={pipelineId ?? null} />}
      </div>
    </aside>
  );
}

function RightTabsBar({ tab, setRightTab }: { tab: RightTab; setRightTab: (t: RightTab) => void }) {
  const items: Array<{ id: RightTab; icon: string; label: string }> = [
    { id: "agent", icon: "✦", label: "Agent" },
    { id: "parameters", icon: "⚙", label: "Parameters" },
    { id: "runs", icon: "⏱", label: "Runs" },
  ];
  return (
    <div
      style={{
        display: "flex",
        borderBottom: "1px solid #e2e8f0",
        background: "#f8fafc",
        flexShrink: 0,
      }}
    >
      {items.map((it) => (
        <button
          key={it.id}
          onClick={() => setRightTab(it.id)}
          style={{
            flex: 1,
            padding: "8px 10px",
            fontSize: 12,
            fontWeight: tab === it.id ? 600 : 400,
            color: tab === it.id ? "#2b6cb0" : "#64748b",
            background: tab === it.id ? "#fff" : "transparent",
            border: "none",
            borderBottom: tab === it.id ? "2px solid #2b6cb0" : "2px solid transparent",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
          }}
        >
          <span style={{ fontSize: 11 }}>{it.icon}</span>
          <span>{it.label}</span>
        </button>
      ))}
    </div>
  );
}

function RunsRightTab({
  runResult,
  pipelineId,
}: {
  runResult: ExecuteResponse | null;
  pipelineId: number | null;
}) {
  const [history, setHistory] = useState<PipelineRunSummary[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (pipelineId == null) return;
    setLoadingHistory(true);
    setHistoryError(null);
    try {
      const rows = await listPipelineRuns(pipelineId, 20);
      setHistory(rows);
    } catch (e) {
      setHistoryError((e as Error).message);
    } finally {
      setLoadingHistory(false);
    }
  }, [pipelineId]);

  // Fetch on mount and whenever pipelineId changes (e.g. user opens a
  // different pipeline). Re-runs after manual Run Full / Run Now would
  // need an explicit refresh — call refresh() from those code paths.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div style={{ padding: 12, overflowY: "auto", flex: 1 }}>
      {/* Latest in-memory run (manual Run Full button result) */}
      {runResult && <InMemoryRunCard runResult={runResult} />}

      {/* Historical runs from pb_pipeline_runs */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: runResult ? 18 : 0, marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "#475569" }}>執行歷史</div>
        <button
          onClick={() => void refresh()}
          disabled={loadingHistory || pipelineId == null}
          style={{
            padding: "3px 8px", fontSize: 10, borderRadius: 4,
            background: "#fff", border: "1px solid #cbd5e0",
            color: "#475569", cursor: loadingHistory ? "wait" : "pointer",
          }}
          title="重新整理"
        >
          {loadingHistory ? "..." : "↻"}
        </button>
      </div>

      {pipelineId == null ? (
        <div style={{ fontSize: 11, color: "#94a3b8", padding: "8px 0" }}>
          先儲存 pipeline 才會有歷史紀錄
        </div>
      ) : historyError ? (
        <div style={{ fontSize: 11, color: "#dc2626", padding: "8px 0" }}>
          載入失敗：{historyError}
        </div>
      ) : history.length === 0 ? (
        <div style={{ fontSize: 11, color: "#94a3b8", padding: "8px 0" }}>
          尚無紀錄 — 按 ▶️ Run Now 或等 cron 觸發
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {history.map((r) => (
            <RunHistoryRow key={r.id} run={r} />
          ))}
        </div>
      )}
    </div>
  );
}

function InMemoryRunCard({ runResult }: { runResult: ExecuteResponse }) {
  const nodeResults = runResult.node_results ?? {};
  const entries = Object.entries(nodeResults);
  const successCount = entries.filter(([, v]) => v.status === "success").length;
  const failedCount = entries.filter(([, v]) => v.status === "failed").length;

  return (
    <div style={{ borderBottom: "1px dashed #e2e8f0", paddingBottom: 12, marginBottom: 4 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "#475569", marginBottom: 6 }}>本地最近一次 Run Full</div>
      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>
        Run #{runResult.run_id ?? "?"} · status: <strong style={{ color: runResult.status === "success" ? "#16a34a" : "#dc2626" }}>{runResult.status}</strong>
        {" · "}{successCount} success · {failedCount} failed
        {runResult.duration_ms ? ` · ${Math.round(runResult.duration_ms)}ms` : ""}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {entries.map(([nodeId, res]) => (
          <div
            key={nodeId}
            style={{
              border: "1px solid #e2e8f0",
              borderRadius: 4,
              padding: "4px 8px",
              fontSize: 10,
              background: res.status === "success" ? "#f0fdf4" : res.status === "failed" ? "#fef2f2" : "#f8fafc",
            }}
          >
            <span style={{ fontWeight: 600, color: "#0f172a" }}>{nodeId}</span>
            {" · "}
            <span style={{ color: res.status === "success" ? "#16a34a" : res.status === "failed" ? "#dc2626" : "#64748b" }}>
              {res.status}
            </span>
            {" · rows: "}{res.rows ?? "—"}
            {res.duration_ms ? ` · ${Math.round(res.duration_ms)}ms` : ""}
            {res.error && (
              <div style={{ color: "#dc2626", fontFamily: "monospace", marginTop: 2 }}>{res.error.slice(0, 160)}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function RunHistoryRow({ run }: { run: PipelineRunSummary }) {
  // Surface fanout / triggered counts for auto_patrol runs (node_results
  // carries them under a synthetic shape — see AutoPatrolExecutor).
  let fanout: number | null = null;
  let triggered: number | null = null;
  if (run.node_results) {
    try {
      const parsed = JSON.parse(run.node_results) as Record<string, unknown>;
      if (typeof parsed.fanout_count === "number") fanout = parsed.fanout_count;
      if (typeof parsed.triggered_count === "number") triggered = parsed.triggered_count;
    } catch {
      /* malformed JSON — ignore, just show status + timestamp */
    }
  }
  const startedAt = new Date(run.started_at);
  const startedLabel = isNaN(startedAt.getTime())
    ? run.started_at
    : startedAt.toLocaleString("zh-TW", { hour12: false });
  const statusColor =
    run.status === "success" ? "#16a34a"
    : run.status === "failed" ? "#dc2626"
    : run.status === "skipped" ? "#a16207"
    : "#64748b";
  const bg =
    run.status === "success" ? "#f0fdf4"
    : run.status === "failed" ? "#fef2f2"
    : run.status === "skipped" ? "#fefce8"
    : "#f8fafc";
  return (
    <div
      style={{
        border: "1px solid #e2e8f0",
        borderRadius: 6,
        padding: "6px 10px",
        fontSize: 11,
        background: bg,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 2 }}>
        <span style={{ color: "#0f172a", fontWeight: 600 }}>#{run.id}</span>
        <span style={{ fontSize: 10, color: statusColor, fontWeight: 600 }}>{run.status}</span>
      </div>
      <div style={{ color: "#64748b", fontSize: 10 }}>
        {run.triggered_by} · {startedLabel}
        {fanout != null && (
          <>
            {" · "}fanout {fanout}
            {triggered != null && (
              <>
                {" · "}<strong style={{ color: triggered > 0 ? "#dc2626" : "#16a34a" }}>{triggered} triggered</strong>
              </>
            )}
          </>
        )}
      </div>
      {run.error_message && (
        <div style={{ marginTop: 4, color: "#dc2626", fontFamily: "monospace", fontSize: 10 }}>
          {run.error_message.slice(0, 180)}
        </div>
      )}
    </div>
  );
}
