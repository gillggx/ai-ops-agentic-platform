"use client";

import { Pill } from "./primitives";
import type { FleetConcern } from "./types";

export function TopConcernsRow({ concerns, onDrill }: {
  concerns: FleetConcern[];
  onDrill: (concern: FleetConcern) => void;
}) {
  if (!concerns || concerns.length === 0) return null;
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 8 }}>
        <div className="h2">AI 摘要 — 最該關心的 3 件事</div>
        <span className="micro" style={{ color: "var(--c-ink-3)" }}>
          AI 排序 · 點任一卡片下鑽至證據
        </span>
      </div>
      <div className="concerns-grid">
        {concerns.map((c, i) => (
          <div
            key={c.id}
            className={`surface concern stripe-${c.severity}`}
            role="button"
            tabIndex={0}
            onClick={() => onDrill(c)}
            onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onDrill(c); } }}
            style={{ cursor: "pointer" }}
          >
            <div className="concern__head">
              <span className="concern__index">{String(i + 1).padStart(2, "0")}</span>
              <Pill kind={c.severity}>
                {c.severity === "crit" ? "需介入" : "關注"}
              </Pill>
              <span className="micro mono" style={{ marginLeft: "auto", color: "var(--c-ink-3)" }}>
                {Math.round(c.confidence * 100)}%
              </span>
            </div>
            <div className="concern__title">{c.title}</div>
            <div className="concern__detail">{c.detail}</div>
            <div className="concern__chips">
              {c.tools.map(t => <span key={t} className="pill pill-neutral">{t}</span>)}
              {c.steps.map(s => <span key={s} className="pill pill-neutral">{s}</span>)}
              {c.evidence > 0 && (
                <span className="pill pill-info">{c.evidence} 證據</span>
              )}
            </div>
            {c.actions.length > 0 && (
              <>
                <div className="label" style={{ marginBottom: 4 }}>建議行動</div>
                <ul className="concern__actions">
                  {c.actions.slice(0, 2).map((a, j) => <li key={j}>{a}</li>)}
                </ul>
              </>
            )}
            <div className="concern__buttons">
              <button className="btn" style={{ height: 24, padding: "0 8px", fontSize: 11 }}>下鑽 →</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
