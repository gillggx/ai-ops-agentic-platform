"use client";

/**
 * ChatOpsConsolePanel (2026-07-13 design mockup) — ChatOps 右側深色 Console。
 *
 * 顯示當前 run 的每一步（glass-event 流）：✓ 完成步驟（含相鄰事件時間差當
 * 耗時）、► 進行中（最後一個 op）、✗ 錯誤。跑完 8 秒自動收合成窄條，
 * 「釘選常駐」可停用自動收合；新 run 開始自動展開。
 * 只在桌機 ChatOps 出現（AppShell 控制），手機/dock 不掛。
 */
import { useEffect, useMemo, useRef, useState } from "react";

export interface ConsoleGlassEvent {
  kind: "start" | "op" | "chat" | "error" | "done" | "user";
  ts?: string;
  goal?: string;
  op?: string;
  args?: Record<string, unknown>;
  message?: string;
  status?: string;
}

interface Line { text: string; sub?: string; tone: "ok" | "err" | "info" | "run"; }

function secDiff(a?: string, b?: string): string {
  if (!a || !b) return "";
  const ms = new Date(b).getTime() - new Date(a).getTime();
  if (!Number.isFinite(ms) || ms <= 0 || ms > 30 * 60 * 1000) return "";
  return `${(ms / 1000).toFixed(1)}s`;
}

const AUTO_COLLAPSE_MS = 8000;

export function ChatOpsConsolePanel({ runPhase, goal, events }: {
  runPhase: string;
  goal: string | null;
  events: ConsoleGlassEvent[];
}) {
  const live = runPhase === "building" || runPhase === "running";
  const [collapsed, setCollapsed] = useState(true);   // 待命時預設收合
  const [pinned, setPinned] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const prevLive = useRef(false);

  // 新 run 開始 → 自動展開；run 結束 → 8 秒後自動收合（除非釘選）。
  useEffect(() => {
    if (live && !prevLive.current) { setCollapsed(false); setCountdown(null); }
    if (!live && prevLive.current && !pinned) {
      setCountdown(AUTO_COLLAPSE_MS / 1000);
      const started = Date.now();
      const tick = setInterval(() => {
        const left = Math.ceil((AUTO_COLLAPSE_MS - (Date.now() - started)) / 1000);
        if (left <= 0) { clearInterval(tick); setCollapsed(true); setCountdown(null); }
        else setCountdown(left);
      }, 500);
      prevLive.current = live;
      return () => clearInterval(tick);
    }
    prevLive.current = live;
  }, [live, pinned]);

  const lines = useMemo<Line[]>(() => {
    const out: Line[] = [];
    const evs = events.slice(-60);
    for (let i = 0; i < evs.length; i++) {
      const e = evs[i];
      const dur = secDiff(e.ts, evs[i + 1]?.ts);
      if (e.kind === "start") {
        out.push({ text: `▶ ${String(e.goal ?? "build").slice(0, 42)}`, tone: "info" });
      } else if (e.kind === "op") {
        const a = e.args ?? {};
        const target = String(a.block_name ?? a.node_id ?? a.to_node ?? "").slice(0, 30);
        const isLast = i === evs.length - 1;
        out.push({
          text: `${isLast && live ? "►" : "✓"} ${e.op ?? "op"} ${target}`,
          sub: isLast && live ? "running" : dur || undefined,
          tone: isLast && live ? "run" : "ok",
        });
      } else if (e.kind === "error") {
        out.push({ text: `✗ ${String(e.message ?? "error").slice(0, 48)}`, tone: "err" });
      } else if (e.kind === "done") {
        const ok = e.status === "finished" || e.status === "success";
        out.push({ text: ok ? "OK — 建構完成" : `結束：${e.status ?? "?"}`, tone: ok ? "ok" : "err" });
      }
    }
    return out.slice(-45);
  }, [events, live]);

  useEffect(() => { endRef.current?.scrollIntoView({ block: "nearest" }); }, [lines.length]);

  const TONE: Record<Line["tone"], string> = {
    ok: "#7ee2b8", err: "#ff9d9d", info: "#e6eaee", run: "#ffd479",
  };

  if (collapsed) {
    return (
      <div style={{
        width: 36, minWidth: 36, flexShrink: 0, background: "var(--nav, #14211C)",
        display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 12, gap: 10,
      }}>
        <button onClick={() => setCollapsed(false)} title="展開 Console" style={{
          width: 24, height: 24, borderRadius: 6, border: "none", cursor: "pointer",
          background: "rgba(255,255,255,0.08)", color: "#cfd6dd", fontSize: 12,
        }}>«</button>
        <span style={{
          width: 8, height: 8, borderRadius: "50%",
          background: live ? "#39d98a" : "#5b6673",
        }} />
        <span style={{
          writingMode: "vertical-rl", fontSize: 10.5, letterSpacing: "0.15em",
          color: "#9aa1b5", fontFamily: "ui-monospace, Menlo, monospace",
        }}>CONSOLE</span>
      </div>
    );
  }

  return (
    <div style={{
      width: 320, minWidth: 320, flexShrink: 0, background: "var(--nav, #14211C)",
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <div style={{
        padding: "10px 14px", display: "flex", alignItems: "center", gap: 8,
        borderBottom: "1px solid rgba(255,255,255,0.08)", flexShrink: 0,
      }}>
        <span style={{
          width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
          background: live ? "#39d98a" : "#5b6673",
        }} />
        <span style={{ fontSize: 13, fontWeight: 700, color: "#f0f2f5" }}>Console</span>
        <a href="/agent-activity" target="_blank" rel="noreferrer" style={{
          fontSize: 10, color: "#9aa1b5", textDecoration: "none",
          fontFamily: "ui-monospace, Menlo, monospace",
        }}>agent-activity</a>
        <span style={{ flex: 1 }} />
        <button onClick={() => setCollapsed(true)} style={{
          border: "1px solid rgba(255,255,255,0.18)", background: "transparent",
          color: "#cfd6dd", fontSize: 11, padding: "3px 10px", borderRadius: 8, cursor: "pointer",
        }}>收合 »</button>
      </div>

      {goal && live && (
        <div style={{
          padding: "7px 14px", fontSize: 11, color: "#9aa1b5", lineHeight: 1.5,
          borderBottom: "1px solid rgba(255,255,255,0.06)", flexShrink: 0,
        }}>{goal.slice(0, 70)}</div>
      )}

      <div style={{
        flex: 1, minHeight: 0, overflowY: "auto", padding: "10px 14px",
        font: "11px/1.9 ui-monospace, Menlo, monospace",
      }}>
        {lines.length === 0 && (
          <div style={{ color: "#6d7386" }}>待命 — 送出需求後這裡會即時顯示 agent 的每一步。</div>
        )}
        {lines.map((l, i) => (
          <div key={i}>
            <div style={{ color: TONE[l.tone], whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {l.text}
            </div>
            {l.sub && <div style={{ color: "#6d7386", paddingLeft: 16, marginTop: -3 }}>{l.sub}</div>}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div style={{
        padding: "8px 14px calc(8px + env(safe-area-inset-bottom, 0px))",
        borderTop: "1px solid rgba(255,255,255,0.08)", flexShrink: 0,
        display: "flex", alignItems: "center", fontSize: 10.5, color: "#8b93a5",
      }}>
        <span>{countdown != null ? `跑完 ${countdown} 秒後自動收合` : pinned ? "常駐中" : "跑完 8 秒後自動收合"}</span>
        <span style={{ flex: 1 }} />
        <button onClick={() => { setPinned((p) => !p); setCountdown(null); }} style={{
          border: "none", background: "transparent", cursor: "pointer",
          color: pinned ? "#7ee2b8" : "#8b93a5", fontSize: 10.5, fontWeight: 700,
        }}>{pinned ? "已釘選 ●" : "釘選常駐 ○"}</button>
      </div>
    </div>
  );
}
