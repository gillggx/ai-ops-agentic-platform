"use client";

import { Pill } from "../../primitives";
import type { LineageFlow as LineageFlowType, LineageNode, LotSummary } from "../../eqp-types";

/** 3-column lineage flow with handoff-style nodes (Inputs → Process → Outcomes).
 *  Mirrors eqp-lineage.jsx's grid + LineageNode + Connector. */
export function LineageFlow({ lot, flow }: {
  lot: LotSummary;
  flow: LineageFlowType;
}) {
  const sevPill = lot.status === "ooc" ? "crit" : lot.status === "warn" ? "warn" : "ok";
  const labelTag = lot.status === "ooc" ? "OOC" : lot.status === "warn" ? "WARN" : "OK";

  return (
    <div className="surface" style={{ padding: "16px 20px" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <div className="h2 mono">{lot.lot_id}</div>
          <div className="micro mono" style={{ color: "var(--c-ink-3)" }}>
            {lot.started ? new Date(lot.started).toLocaleString("zh-TW", { hour12: false }) : "—"}
            {" · recipe "}{lot.recipe || "—"}
            {" · "}{lot.duration_min} min
          </div>
        </div>
        <Pill kind={sevPill}>{labelTag} · {lot.events} events</Pill>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 16px 1fr 16px 1fr", gap: 0, alignItems: "start" }}>
        <Column label="上線設定" nodes={flow.inputs} />
        <Connector />
        <Column label="處理" nodes={flow.process} />
        <Connector />
        <Column label="結果" nodes={flow.outcomes} />
      </div>
    </div>
  );
}

function Column({ label, nodes }: { label: string; nodes: LineageNode[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="label">{label}</div>
      {nodes.map((n, i) => <Node key={n.title + i} node={n} />)}
    </div>
  );
}

function Node({ node }: { node: LineageNode }) {
  return (
    <div
      className={`stripe-${node.state === "neutral" ? "ok" : node.state}`}
      style={{
        border: node.highlight ? "1.5px solid var(--c-ink-1)" : "1px solid var(--c-line)",
        borderRadius: 4,
        padding: "8px 10px",
        background: "var(--c-bg)",
      }}
    >
      <div className="label" style={{ color: "var(--c-ink-3)", marginBottom: 2 }}>{node.title}</div>
      <div className="h3 mono" style={{ marginBottom: 2 }}>{node.value}</div>
      <div className="micro" style={{ color: "var(--c-ink-2)" }}>{node.sub}</div>
    </div>
  );
}

function Connector() {
  return (
    <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", paddingTop: 32 }}>
      <svg width={16} height={100} style={{ display: "block" }}>
        <line x1={0} x2={16} y1={20} y2={20} stroke="#d4d4cf" strokeWidth={1} />
        <line x1={0} x2={16} y1={60} y2={60} stroke="#d4d4cf" strokeWidth={1} />
        <line x1={0} x2={16} y1={100} y2={100} stroke="#d4d4cf" strokeWidth={1} />
        <polygon points="12,17 16,20 12,23" fill="#d4d4cf" />
        <polygon points="12,57 16,60 12,63" fill="#d4d4cf" />
        <polygon points="12,97 16,100 12,103" fill="#d4d4cf" />
      </svg>
    </div>
  );
}
