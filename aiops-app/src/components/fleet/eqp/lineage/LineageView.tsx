"use client";

import { useCallback, useEffect, useState } from "react";
import { LotScrubber } from "./LotScrubber";
import { LineageFlow } from "./LineageFlow";
import { ParameterInspector } from "./ParameterInspector";
import type { LineageResponse } from "../../eqp-types";

/** "流程溯源" / "參數檢視" sub-tab. Same data fetch, different sections
 *  rendered. mode="flow" shows scrubber + lineage diagram; mode="params"
 *  shows scrubber + parameter inspector. Defaults to "flow". */
export function LineageView({ toolId, mode = "flow" }: {
  toolId: string;
  mode?: "flow" | "params";
}) {
  const [data, setData] = useState<LineageResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedLot, setSelectedLot] = useState<string | null>(null);

  const refresh = useCallback(async (lotId?: string | null) => {
    setLoading(true);
    try {
      const qs = lotId ? `?lot_id=${encodeURIComponent(lotId)}` : "";
      const res = await fetch(`/api/admin/fleet/equipment/${toolId}/lineage${qs}`);
      if (!res.ok) return;
      const j: LineageResponse = await res.json();
      setData(j);
      if (j.selected) setSelectedLot(j.selected.lot.lot_id);
    } finally { setLoading(false); }
  }, [toolId]);

  useEffect(() => { refresh(); }, [refresh]);

  const onSelect = (lotId: string) => {
    setSelectedLot(lotId);
    refresh(lotId);
  };

  if (!data) {
    return (
      <div className="micro" style={{ color: "var(--c-ink-3)", padding: 24, textAlign: "center" }}>
        {loading ? "載入溯源中…" : "(無溯源資料)"}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <LotScrubber lots={data.lots} selectedLotId={selectedLot} onSelect={onSelect} />
      {data.selected ? (
        mode === "params" ? (
          <ParameterInspector params={data.selected.parameters} />
        ) : (
          <LineageFlow lot={data.selected.lot} flow={data.selected.lineage} />
        )
      ) : (
        <div className="micro" style={{ color: "var(--c-ink-3)", padding: 24, textAlign: "center" }}>
          (此 LOT 無資料 — 點選其他 LOT)
        </div>
      )}
    </div>
  );
}
