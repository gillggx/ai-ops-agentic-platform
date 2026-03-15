"use client";
/**
 * OOCWatchlist — 2.2.3 Global OOC Watchlist (Left Fixed Panel)
 *
 * Calls GET /api/v2/ontology/indices/SPC?status=OOC&limit=50
 * Light-theme card list, newest-first.
 * Each card shows: Lot ID, OOC badge, Tool ID, timestamp, anomaly hint.
 */
import { useState, useEffect, useCallback } from "react";
import { RefreshCw, Settings } from "lucide-react";

function getApiBase() {
  if (typeof window === "undefined") return "http://localhost:8001";
  const isLocal =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";
  return isLocal
    ? `http://${window.location.hostname}:8001`
    : `${window.location.origin}/simulator-api`;
}

export interface OOCAlert {
  index_id:   string;
  lot_id:     string | null;
  tool_id:    string | null;
  step:       string | null;
  event_time: string | null;
  payload:    Record<string, unknown>;
}

interface Props {
  onSelect:   (alert: OOCAlert) => void;
  selectedId: string | null;
}

/** Derive a short human-readable anomaly hint from the SPC charts payload */
function getAnomalyHint(payload: Record<string, unknown>): string | null {
  const charts = payload?.charts as Record<string, unknown> | undefined;
  if (!charts) return null;
  const oocCharts = Object.entries(charts)
    .filter(([, c]) => (c as Record<string, unknown>)?.status === "OOC")
    .map(([key]) => key.replace("_chart", "").replace(/_/g, " ").toUpperCase());
  if (oocCharts.length === 0) return null;
  // Map chart names to readable anomaly descriptions
  const labels: Record<string, string> = {
    "XBAR": "CD Too Small",
    "XBAR CHART": "CD Too Small",
    "RANGE": "Range Excursion",
    "RANGE CHART": "Range Excursion",
    "PRESSURE": "Pressure Outlier",
    "PRESSURE CHART": "Pressure Outlier",
    "RF POWER": "RF Power Drift",
    "RF POWER CHART": "RF Power Drift",
    "BIAS": "Bias Voltage Spike",
    "BIAS CHART": "Bias Voltage Spike",
  };
  const first = oocCharts[0];
  return labels[first] ?? `${first} Excursion`;
}

export default function OOCWatchlist({ onSelect, selectedId }: Props) {
  const [alerts, setAlerts]   = useState<OOCAlert[]>([]);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  const fetchAlerts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${getApiBase()}/api/v2/ontology/indices/SPC?status=OOC&limit=50`
      );
      if (!res.ok) {
        const msg = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(msg.detail ?? res.statusText);
      }
      const data = await res.json();
      setAlerts(data.records ?? []);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAlerts(); }, [fetchAlerts]);

  const fmtTime = (iso: string | null) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}:${String(d.getSeconds()).padStart(2,"0")}`;
  };

  return (
    <div className="h-full flex flex-col overflow-hidden bg-white border-r border-slate-200">

      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-slate-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-slate-500" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <line x1="2" y1="4" x2="14" y2="4"/><line x1="2" y1="8" x2="14" y2="8"/><line x1="2" y1="12" x2="14" y2="12"/>
          </svg>
          <span className="text-[11px] font-bold text-slate-700 uppercase tracking-widest">
            OOC Watchlist
          </span>
        </div>
        <button
          onClick={fetchAlerts}
          disabled={loading}
          className="text-slate-400 hover:text-slate-700 disabled:opacity-40 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">

        {loading && (
          <div className="flex items-center justify-center py-10">
            <p className="text-[11px] text-slate-400 animate-pulse">Loading…</p>
          </div>
        )}

        {error && (
          <div className="px-2 py-1.5 text-[10px] text-red-500 bg-red-50 rounded border border-red-100">
            {error}
          </div>
        )}

        {!loading && !error && alerts.length === 0 && (
          <div className="flex items-center justify-center py-10">
            <p className="text-[11px] text-slate-400">No OOC alerts found</p>
          </div>
        )}

        {!loading && alerts.map((a) => {
          const isSelected = selectedId === a.index_id;
          const hint       = getAnomalyHint(a.payload);

          return (
            <div
              key={a.index_id}
              onClick={() => onSelect(a)}
              className={[
                "rounded-lg border cursor-pointer transition-all p-3",
                isSelected
                  ? "bg-red-50 border-red-300 shadow-sm"
                  : "bg-white border-slate-200 hover:border-red-200 hover:bg-red-50/30",
              ].join(" ")}
            >
              {/* Row 1: Lot ID + OOC badge */}
              <div className="flex items-center justify-between mb-1.5">
                <span className={[
                  "text-[13px] font-bold font-mono",
                  isSelected ? "text-red-700" : "text-slate-800",
                ].join(" ")}>
                  {a.lot_id ?? "—"}
                </span>
                <span className="text-[9px] font-bold bg-red-100 text-red-600 border border-red-200 px-1.5 py-0.5 rounded">
                  OOC
                </span>
              </div>

              {/* Row 2: Tool + timestamp */}
              <div className="flex items-center gap-2 text-[10px] text-slate-500">
                <Settings size={9} className="text-slate-400 shrink-0" />
                <span className="font-mono">{a.tool_id ?? "—"}</span>
                <span className="ml-auto font-mono tabular-nums">{fmtTime(a.event_time)}</span>
              </div>

              {/* Row 3: Anomaly hint */}
              {hint && (
                <div className="mt-1.5 flex items-center gap-1.5">
                  <svg className="w-3 h-3 text-red-400 shrink-0" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M8 2L14 13H2L8 2Z"/><line x1="8" y1="7" x2="8" y2="10"/><circle cx="8" cy="12" r="0.5" fill="currentColor"/>
                  </svg>
                  <span className={[
                    "text-[10px] font-mono",
                    isSelected ? "text-red-600" : "text-red-500",
                  ].join(" ")}>
                    {hint}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
