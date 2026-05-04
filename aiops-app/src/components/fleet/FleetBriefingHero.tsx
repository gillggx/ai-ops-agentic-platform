"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { FleetConcern, FleetEquipment, FleetStats } from "./types";

/** Top-of-page hero. Streams an AI-generated narrative from the chat
 *  agent (scope=fleet) on the left; static aggregated metrics on the
 *  right. Falls back to a deterministic one-liner if SSE fails. */
export function FleetBriefingHero({ stats, equipment, concerns }: {
  stats: FleetStats | null;
  equipment: FleetEquipment[];
  concerns: FleetConcern[];
}) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);

  // Fold the data we want the LLM to see into one body. POST endpoint
  // matches the existing /api/admin/briefing proxy → Java → sidecar.
  const fleetData = useMemo(() => ({
    stats,
    equipment: equipment.slice(0, 8).map(e => ({
      id: e.id, health: e.health, score: e.score,
      ooc: e.ooc, oocCount: e.ooc_count, alarms: e.alarms,
      trend: e.trend, note: e.note,
    })),
    concerns: concerns.slice(0, 3).map(c => ({
      severity: c.severity, title: c.title, detail: c.detail,
    })),
  }), [stats, equipment, concerns]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setText("");
    try {
      const res = await fetch("/api/admin/briefing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope: "fleet", fleetData }),
      });
      const reader = res.body?.getReader();
      if (!reader) throw new Error("no body reader");
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).replace(/^\s/, "");
          try {
            const ev = JSON.parse(payload);
            if (ev.type === "chunk") setText(prev => prev + ev.text);
          } catch { /* skip non-JSON */ }
        }
      }
    } catch {
      // Fallback to deterministic narrative — never leave the hero blank.
      const crit = stats?.crit_count ?? 0;
      const warn = stats?.warn_count ?? 0;
      const rate = stats?.fleet_ooc_rate ?? 0;
      setText(`整廠 24h OOC 率 \`${rate.toFixed(1)}%\`，**${crit}** 台需立即介入、**${warn}** 台需持續關注。`);
    } finally { setLoading(false); }
  }, [fleetData, stats]);

  // 2026-05-04 cost cut: removed auto-refresh-on-stats-change. Auto-firing
  // every dashboard tick (default 5min) on every open tab burned ~288 LLM
  // calls/day/tab even when nobody was looking. AI briefing is now
  // explicitly user-triggered via the "↻ 重新生成" button. The deterministic
  // fallback below covers the empty state.

  const fleetOoc = stats ? stats.fleet_ooc_rate.toFixed(2) + "%" : "—";
  const cards: { k: string; v: string; sev?: "crit" | "warn" | "info" }[] = [
    { k: "OOC Rate",      v: fleetOoc, sev: "crit" },
    { k: "OOC events",    v: String(stats?.ooc_events ?? 0), sev: "warn" },
    { k: "Open alarms",   v: String(stats?.open_alarms ?? 0), sev: "info" },
    { k: "受影響 LOT",    v: String(stats?.affected_lots ?? 0), sev: "warn" },
    { k: "FDC 警告",      v: String(stats?.fdc_alerts ?? 0) },
  ];

  return (
    <div className="surface hero" data-tour-id="fleet-briefing">
      <div>
        <div className="hero__head">
          <span className="hero__head__icon">✦</span>
          <span className="label">AI 簡報</span>
          <span className="micro mono" style={{ color: "var(--c-ink-3)" }}>
            · {stats?.as_of ? new Date(stats.as_of).toLocaleString("zh-TW", { hour12: false }) : "—"}
          </span>
          <button
            className="btn btn-ghost"
            style={{ marginLeft: "auto", height: 22, padding: "0 8px", fontSize: 11 }}
            onClick={refresh}
            disabled={loading}
          >
            ↻ 重新生成
          </button>
        </div>
        <div className="h1" style={{ minHeight: 48, lineHeight: 1.4, color: "var(--c-ink-1)" }}>
          {loading && !text && (
            <span style={{ color: "var(--c-ink-3)" }}>
              <span className="cursor-blink" />
              AI 分析整廠狀態中…
            </span>
          )}
          {!loading && !text && (
            <span style={{ color: "var(--c-ink-3)", fontSize: 14, fontWeight: 400 }}>
              點上方「↻ 重新生成」產生 AI 摘要（消耗 LLM token，按需觸發）
            </span>
          )}
          {text && <ReactMarkdown>{text}</ReactMarkdown>}
        </div>
      </div>

      <div className="hero__sidebar">
        <div className="label" style={{ marginBottom: 10 }}>整體指標</div>
        {cards.map(c => (
          <div key={c.k} className="hero__metric-row">
            <span className="small">{c.k}</span>
            <span className={"hero__metric-row__val mono" + (c.sev ? ` hero__metric-row__val--${c.sev}` : "")}>
              {c.v}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
