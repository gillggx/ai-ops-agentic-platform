"use client";

/**
 * ChatOpsAgentRail (v2, 2026-07-10 per design mockup + user feedback).
 *
 * Left rail = what the agent is DOING, not a chat log:
 *   1. + 新對話
 *   2. Console card — LIVE step feed of the current run (dark, mono,
 *      timestamped lines from the glass-event stream), agent-activity link
 *   3. 最近運作 — the platform agent's recent episodes
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

interface RailGlassEvent {
  kind: "start" | "op" | "chat" | "error" | "done" | "user";
  ts?: string;
  goal?: string;
  op?: string;
  args?: Record<string, unknown>;
  message?: string;
  status?: string;
}

interface EpisodeRow {
  episode_key: string;
  instruction: string | null;
  status: string | null;
  step_count: number;
  started_at: string | null;
}

function timeLabel(iso: string | null): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 90) return "剛剛";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分鐘前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小時前`;
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

/** One compact console line per meaningful glass event. */
function lineFor(e: RailGlassEvent): { text: string; tone: "ok" | "err" | "info" } | null {
  if (e.kind === "start") {
    return { text: `▶ ${String(e.goal ?? "build").slice(0, 34)}`, tone: "info" };
  }
  if (e.kind === "op") {
    const a = e.args ?? {};
    const target = (a.block_name ?? a.node_id ?? a.to_node ?? "") as string;
    return { text: `${e.op ?? "op"} ${String(target).slice(0, 26)} ✓`, tone: "ok" };
  }
  if (e.kind === "error") {
    return { text: `✗ ${String(e.message ?? "error").slice(0, 40)}`, tone: "err" };
  }
  if (e.kind === "done") {
    const ok = e.status === "finished" || e.status === "success";
    return { text: ok ? "OK — 建構完成" : `結束：${e.status ?? "?"}`, tone: ok ? "ok" : "err" };
  }
  return null;
}

export function ChatOpsAgentRail({ runPhase, goal, events, onNew }: {
  runPhase: string;
  goal: string | null;
  events: RailGlassEvent[];
  onNew: () => void;
}) {
  const [rows, setRows] = useState<EpisodeRow[]>([]);
  const consoleEndRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    fetch("/api/agent-activity/episodes?limit=15", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((env) => {
        const list = (env?.data ?? env) as EpisodeRow[];
        setRows(Array.isArray(list) ? list : []);
      })
      .catch(() => { /* rail is ambient — fail silent */ });
  }, []);
  useEffect(() => { load(); const id = setInterval(load, 15_000); return () => clearInterval(id); }, [load]);

  const lines = useMemo(() => {
    const out: Array<{ ts?: string; text: string; tone: "ok" | "err" | "info" }> = [];
    for (const e of events) {
      const l = lineFor(e);
      if (l) out.push({ ts: e.ts, ...l });
    }
    return out.slice(-40);
  }, [events]);

  useEffect(() => {
    consoleEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [lines.length]);

  const live = runPhase === "building" || runPhase === "running";
  const TONE: Record<string, string> = { ok: "#7ee2b8", err: "#ff9d9d", info: "#e6eaee" };

  return (
    <div style={{
      width: 264, minWidth: 264, flexShrink: 0,
      background: "var(--pn, #F8F6F0)", borderRight: "1px solid #e2e8f0",
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <div style={{ padding: "12px 12px 8px", flexShrink: 0 }}>
        <button onClick={onNew} style={{
          width: "100%", padding: "9px 0", borderRadius: 9, border: "none",
          background: "var(--p, #1E5A44)", color: "#fff",
          fontSize: 13, fontWeight: 700, cursor: "pointer",
        }}>
          + 新對話
        </button>
      </div>

      {/* Console — live step feed (design mockup: dark card, mono lines) */}
      <div style={{
        margin: "4px 10px 0", borderRadius: 12, overflow: "hidden",
        background: "var(--nav, #14211C)", flexShrink: 0,
        display: "flex", flexDirection: "column", maxHeight: 300,
      }}>
        <div style={{
          padding: "9px 12px", display: "flex", alignItems: "center", gap: 7,
          borderBottom: "1px solid rgba(255,255,255,0.08)",
        }}>
          <span style={{
            width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
            background: live ? "#39d98a" : "#5b6673",
          }} />
          <span style={{ fontSize: 12.5, fontWeight: 700, color: "#f0f2f5" }}>Console</span>
          {live && <span style={{
            fontSize: 9.5, fontWeight: 700, color: "#39d98a", letterSpacing: "0.4px",
            border: "1px solid rgba(57,217,138,0.4)", borderRadius: 8, padding: "0 6px",
          }}>live</span>}
          <span style={{ flex: 1 }} />
          <a href="/agent-activity" target="_blank" rel="noreferrer" style={{
            fontSize: 10, color: "#9aa1b5", textDecoration: "none",
            fontFamily: "ui-monospace, Menlo, monospace",
          }}>agent-activity ↗</a>
        </div>
        <div style={{
          padding: "8px 12px 10px", overflowY: "auto",
          font: "10.5px/1.75 ui-monospace, Menlo, monospace",
        }}>
          {lines.length === 0 && (
            <div style={{ color: "#6d7386" }}>待命 — 送出需求後這裡會即時顯示 agent 的每一步。</div>
          )}
          {lines.map((l, i) => (
            <div key={i} style={{ color: TONE[l.tone], whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {l.ts && <span style={{ color: "#6d7386", marginRight: 6 }}>{l.ts}</span>}
              {l.text}
            </div>
          ))}
          <div ref={consoleEndRef} />
        </div>
      </div>
      {goal && live && (
        <div style={{ margin: "6px 14px 0", fontSize: 11, color: "#64748b", lineHeight: 1.5 }}>
          {goal.slice(0, 60)}
        </div>
      )}

      {/* 最近運作 — platform agent episodes */}
      <div style={{ padding: "14px 12px 4px", fontSize: 10.5, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.5px" }}>
        最近運作
        <a href="/agent-activity" target="_blank" rel="noreferrer"
           style={{ float: "right", fontWeight: 600, color: "var(--p, #1E5A44)", textDecoration: "none" }}>
          全部 →
        </a>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "0 8px 16px" }}>
        {rows.map((r) => {
          const ok = (r.status ?? "").includes("finish") || r.status === "success";
          const fail = (r.status ?? "").includes("fail") || (r.status ?? "").includes("error");
          return (
            <a key={r.episode_key} href={`/agent-activity`} target="_blank" rel="noreferrer" style={{
              display: "block", padding: "8px 10px", marginBottom: 2, borderRadius: 8,
              textDecoration: "none",
            }}>
              <div style={{
                fontSize: 12, fontWeight: 500, color: "#334155",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>
                {r.instruction || "(未記錄指令)"}
              </div>
              <div style={{ fontSize: 10.5, color: "#94a3b8", marginTop: 2, display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{
                  width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                  background: fail ? "#e5484d" : ok ? "#0f9d6a" : "#f5b942",
                }} />
                {timeLabel(r.started_at)} · {r.step_count} steps · {r.status ?? "?"}
              </div>
            </a>
          );
        })}
        {rows.length === 0 && (
          <div style={{ padding: "10px 10px", fontSize: 12, color: "#94a3b8" }}>還沒有運作紀錄</div>
        )}
      </div>
    </div>
  );
}
