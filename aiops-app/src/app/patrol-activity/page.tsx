"use client";

/**
 * Patrol Activity page — operational view of "event → skill_run → alarm" funnel.
 *
 * Sits beside /alarms in OPS_ITEMS. While Alarm Center shows only emitted
 * alarms (the tail of the funnel), this page surfaces every skill_run
 * triggered by the scheduler — including ones that legitimately produce no
 * alarm (stage=diagnose, no step passed, dedup-suppressed).
 *
 * Backend contract: GET /api/v1/patrol-activity → { funnel, items, next_cursor }.
 * The proxy strips the ApiResponse envelope so the page receives data directly.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { PatrolFunnelSummary } from "@/components/patrol/PatrolFunnelSummary";
import { PatrolFilters, type PatrolFilterState } from "@/components/patrol/PatrolFilters";
import { PatrolList } from "@/components/patrol/PatrolList";
import { PatrolDetailPanel } from "@/components/patrol/PatrolDetailPanel";
import type { PatrolFunnel, PatrolItem } from "@/components/patrol/types";

const POLL_INTERVAL_MS = 5_000;
const DEFAULT_LIMIT = 100;

interface PatrolActivityResponse {
  funnel: PatrolFunnel;
  items: PatrolItem[];
  next_cursor: number | null;
}

export default function PatrolActivityPage() {
  const t = useTranslations("patrol");
  const [funnel, setFunnel] = useState<PatrolFunnel | null>(null);
  const [items, setItems] = useState<PatrolItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<PatrolItem | null>(null);

  const [filters, setFilters] = useState<PatrolFilterState>({
    range: "1h",
    eventType: null,
    skillStage: null,
    outcome: "any",
  });

  // Use a ref so the polling interval always uses the latest filters
  // without restarting the timer on every change.
  const filtersRef = useRef(filters);
  filtersRef.current = filters;

  const buildSince = useCallback((range: PatrolFilterState["range"]): string => {
    const now = new Date();
    const subHours = range === "24h" ? 24 : range === "6h" ? 6 : 1;
    return new Date(now.getTime() - subHours * 3600_000).toISOString();
  }, []);

  const fetchPage = useCallback(async () => {
    const f = filtersRef.current;
    const params = new URLSearchParams();
    params.set("since", buildSince(f.range));
    params.set("limit", String(DEFAULT_LIMIT));
    if (f.eventType) params.set("event_type", f.eventType);
    if (f.skillStage) params.set("skill_stage", f.skillStage);
    if (f.outcome && f.outcome !== "any") params.set("outcome", f.outcome);

    try {
      const res = await fetch(`/api/admin/patrol-activity?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as PatrolActivityResponse;
      setFunnel(body.funnel);
      setItems(body.items);
      setError(null);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }, [buildSince]);

  // Initial load + filter changes → immediate re-fetch.
  useEffect(() => {
    setLoading(true);
    fetchPage();
  }, [filters, fetchPage]);

  // Background polling — doesn't show a spinner so the table doesn't flash.
  useEffect(() => {
    const tick = setInterval(() => {
      fetchPage();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(tick);
  }, [fetchPage]);

  // Keep the right-pane selection fresh when the underlying row updates.
  const selectedRefreshed = useMemo(() => {
    if (!selected) return null;
    return items.find((i) => i.skill_run_id === selected.skill_run_id) ?? selected;
  }, [items, selected]);

  return (
    <div style={{ padding: "20px 24px", minHeight: "100vh", background: "#f7f8fc" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 18 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: "#1a202c" }}>{t("title")}</h1>
          <p style={{ fontSize: 12, color: "#718096", margin: "4px 0 0" }}>
            {t("subtitle")}
          </p>
        </div>
        {loading && <span style={{ fontSize: 11, color: "#a0aec0" }}>{t("loading")}</span>}
        {error && <span style={{ fontSize: 11, color: "#e53e3e" }}>{t("errorLabel", { message: error })}</span>}
      </div>

      <PatrolFunnelSummary funnel={funnel} />

      <div style={{ marginTop: 14, marginBottom: 12 }}>
        <PatrolFilters value={filters} onChange={setFilters} />
      </div>

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <PatrolList items={items} selected={selectedRefreshed} onSelect={setSelected} />
        </div>
        {selectedRefreshed && (
          <PatrolDetailPanel item={selectedRefreshed} onClose={() => setSelected(null)} />
        )}
      </div>
    </div>
  );
}
