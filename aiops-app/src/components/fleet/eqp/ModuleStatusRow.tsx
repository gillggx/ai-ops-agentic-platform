"use client";

import type { ModuleStatus } from "../eqp-types";

const STATE_VALUE_COLOR: Record<string, string> = {
  crit: "var(--c-crit)",
  warn: "var(--c-warn)",
  ok:   "var(--c-ink-1)",
};

export function ModuleStatusRow({ modules }: { modules: ModuleStatus[] }) {
  if (!modules || modules.length === 0) {
    return <div className="micro" style={{ color: "var(--c-ink-3)" }}>(無模組狀態)</div>;
  }
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8 }}>
      {modules.map(m => (
        <div key={m.key} className={`surface stripe-${m.state}`} style={{ padding: "10px 12px" }}>
          <div className="label">{m.key}</div>
          <div className="h2 mono" style={{ marginTop: 4, color: STATE_VALUE_COLOR[m.state] ?? "var(--c-ink-1)" }}>
            {m.value}
          </div>
          <div className="micro" style={{ color: "var(--c-ink-3)", marginTop: 2 }}>{m.sub}</div>
        </div>
      ))}
    </div>
  );
}
