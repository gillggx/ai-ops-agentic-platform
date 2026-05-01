"use client";

import { useState } from "react";
import { Spark, StatusDot } from "../../primitives";
import type { ParameterRow } from "../../eqp-types";

/** Abnormal-first sortable parameter table.
 *  Each row: dot + name (mono), group, value (colored if abnormal),
 *  baseline, delta, sparkline of last N samples. */
export function ParameterInspector({ params }: { params: ParameterRow[] }) {
  const [filter, setFilter] = useState<"abnormal" | "all">("abnormal");
  const visible = filter === "abnormal" ? params.filter(p => p.state !== "ok") : params;

  return (
    <div className="surface" style={{ padding: "12px 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
        <div className="h2">參數檢視</div>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            className={`btn ${filter === "abnormal" ? "btn-primary" : "btn-ghost"}`}
            style={{ height: 24, padding: "0 8px", fontSize: 11 }}
            onClick={() => setFilter("abnormal")}
          >
            異常優先
          </button>
          <button
            className={`btn ${filter === "all" ? "btn-primary" : "btn-ghost"}`}
            style={{ height: 24, padding: "0 8px", fontSize: 11 }}
            onClick={() => setFilter("all")}
          >
            全部
          </button>
        </div>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "1.5fr 0.7fr 1fr 1fr 0.8fr 1.5fr",
        gap: 8, padding: "6px 0", borderBottom: "1px solid var(--c-line)",
      }}>
        <div className="label">Parameter</div>
        <div className="label">Group</div>
        <div className="label">Value</div>
        <div className="label">Baseline</div>
        <div className="label">Δ</div>
        <div className="label">歷史 (10 samples)</div>
      </div>

      {visible.length === 0 && (
        <div className="micro" style={{ color: "var(--c-ink-3)", padding: "16px 0", textAlign: "center" }}>
          {filter === "abnormal" ? "全部參數正常 ✅" : "(無參數資料)"}
        </div>
      )}

      {visible.map(p => {
        const sparkColor = p.state === "crit" ? "#b8392f" : p.state === "warn" ? "#b87a1f" : "#76767a";
        const valColor = p.state === "crit" ? "var(--c-crit)" : p.state === "warn" ? "var(--c-warn)" : "var(--c-ink-1)";
        const deltaColor = p.state === "crit" ? "var(--c-crit)" : p.state === "warn" ? "var(--c-warn)" : "var(--c-ink-3)";
        return (
          <div
            key={p.name}
            style={{
              display: "grid",
              gridTemplateColumns: "1.5fr 0.7fr 1fr 1fr 0.8fr 1.5fr",
              gap: 8, padding: "8px 0",
              borderBottom: "1px solid var(--c-line)", alignItems: "center",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <StatusDot status={p.state} size={6} />
              <span className="mono small">{p.name}</span>
            </div>
            <span className="mono micro" style={{ color: "var(--c-ink-3)" }}>{p.group}</span>
            <span className="mono small" style={{ fontWeight: p.state !== "ok" ? 600 : 400, color: valColor }}>
              {p.value != null ? formatNumber(p.value) : "—"}
            </span>
            <span className="mono small" style={{ color: "var(--c-ink-3)" }}>
              {formatNumber(p.baseline)}
            </span>
            <span className="mono small" style={{ color: deltaColor }}>{p.delta}</span>
            <Spark
              values={p.history.length > 0 ? p.history : [p.baseline, p.value ?? p.baseline]}
              w={140} h={20}
              color={sparkColor}
            />
          </div>
        );
      })}
    </div>
  );
}

function formatNumber(v: number): string {
  if (Math.abs(v) >= 1000) return v.toFixed(0);
  if (Math.abs(v) >= 10) return v.toFixed(2);
  return v.toFixed(4);
}
