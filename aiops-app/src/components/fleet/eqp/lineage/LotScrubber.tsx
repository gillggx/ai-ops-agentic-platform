"use client";

import { SEV_COLOR } from "../../primitives";
import type { LotSummary } from "../../eqp-types";

const SEV_BY_STATUS: Record<LotSummary["status"], string> = {
  ooc: SEV_COLOR.crit,
  warn: SEV_COLOR.warn,
  ok: SEV_COLOR.ok,
};

/** Top scrubber from handoff eqp-lineage.jsx — one card per recent LOT,
 *  status stripe at the bottom edge, click selects the LOT to inspect. */
export function LotScrubber({ lots, selectedLotId, onSelect }: {
  lots: LotSummary[];
  selectedLotId: string | null;
  onSelect: (lotId: string) => void;
}) {
  if (!lots || lots.length === 0) {
    return <div className="micro" style={{ color: "var(--c-ink-3)", padding: 12 }}>(無 LOT 資料)</div>;
  }
  return (
    <div className="surface" style={{ padding: "12px 16px" }}>
      <div className="label" style={{ marginBottom: 8 }}>近期 LOT — 點擊以檢視該 LOT 的完整溯源</div>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${lots.length}, minmax(0, 1fr))`, gap: 4 }}>
        {lots.map(l => {
          const sev = SEV_BY_STATUS[l.status] ?? SEV_COLOR.neutral;
          const selected = l.lot_id === selectedLotId;
          return (
            <div
              key={l.lot_id}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(l.lot_id)}
              onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(l.lot_id); } }}
              style={{
                padding: "8px 6px",
                borderRadius: 4,
                border: selected ? "1.5px solid var(--c-ink-1)" : "1px solid var(--c-line)",
                background: selected ? "var(--c-bg-sunken)" : "var(--c-bg)",
                cursor: "pointer",
                boxShadow: `inset 0 -3px 0 ${sev}`,
              }}
            >
              <div className="mono" style={{ fontSize: 11, fontWeight: 500 }}>{l.lot_id}</div>
              <div className="micro" style={{ color: "var(--c-ink-3)" }}>
                {l.recipe || "—"} · {l.events} ev
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
