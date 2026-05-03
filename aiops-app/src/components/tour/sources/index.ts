/**
 * Default palette sources for the cross-surface ⌘K command palette.
 *
 * Each `make<X>Source(router)` returns a PaletteSource that:
 *   - hits the existing API
 *   - performs naive client-side substring filter on the result
 *   - emits PaletteItems whose onSelect navigates via Next.js router.
 *
 * Why fetch then client-filter (rather than server-side search): catalogs
 * are small (≤ 200 alarms / pipelines / equipment), the API already
 * returns full lists for the standard list pages, and reusing those
 * endpoints saves us writing 3 new search endpoints in Java. Upgrade to
 * server-side fuzzy search if catalog sizes grow > 500.
 */

import type { PaletteItem, PaletteSource } from "../types";

type Router = { push: (url: string) => void };

interface PipelineRow {
  id: number;
  name: string;
  status?: string;
}

interface AlarmRow {
  id: number;
  alarm_id?: string;
  equipment_id?: string;
  step?: string;
  severity?: string;
  alarm_type?: string;
  status?: string;
}

interface EquipmentRow {
  equipment_id: string;
  name?: string;
  status?: string;
}

function lc(v: unknown): string {
  return typeof v === "string" ? v.toLowerCase() : "";
}

function matches(query: string, ...fields: unknown[]): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return fields.some((f) => lc(f).includes(q));
}

// ── Pipelines ────────────────────────────────────────────────────────

export function makePipelinesSource(router: Router): PaletteSource {
  let cache: PipelineRow[] | null = null;
  let cacheTs = 0;
  const TTL_MS = 30_000;

  return {
    sourceId: "pipelines",
    group: "Pipelines",
    limit: 8,
    fetch: async (query: string) => {
      const now = Date.now();
      if (!cache || now - cacheTs > TTL_MS) {
        const res = await fetch("/api/pipeline-builder/pipelines");
        if (!res.ok) throw new Error(`pipelines HTTP ${res.status}`);
        const data = await res.json();
        cache = (Array.isArray(data) ? data : []) as PipelineRow[];
        cacheTs = now;
      }
      return cache
        .filter((p) => matches(query, p.name, p.status))
        .slice(0, 12)
        .map<PaletteItem>((p) => ({
          id: `pipeline-${p.id}`,
          group: "Pipelines",
          label: p.name,
          meta: p.status ?? "",
          icon: "🔧",
          onSelect: () => router.push(`/admin/skills/pipeline-builder?id=${p.id}`),
        }));
    },
  };
}

// ── Alarms ───────────────────────────────────────────────────────────

export function makeAlarmsSource(router: Router): PaletteSource {
  let cache: AlarmRow[] | null = null;
  let cacheTs = 0;
  const TTL_MS = 15_000;

  return {
    sourceId: "alarms",
    group: "Alarms",
    limit: 8,
    fetch: async (query: string) => {
      const now = Date.now();
      if (!cache || now - cacheTs > TTL_MS) {
        const res = await fetch("/api/admin/alarms?status=open&limit=200");
        if (!res.ok) throw new Error(`alarms HTTP ${res.status}`);
        const data = await res.json();
        const arr = Array.isArray(data) ? data : data.items ?? data.data ?? [];
        cache = arr as AlarmRow[];
        cacheTs = now;
      }
      return cache
        .filter((a) => matches(query, a.alarm_id, a.equipment_id, a.step, a.alarm_type, a.severity))
        .slice(0, 12)
        .map<PaletteItem>((a) => ({
          id: `alarm-${a.id}`,
          group: "Alarms",
          label: `${a.equipment_id ?? "?"} · ${a.alarm_type ?? a.alarm_id ?? "alarm"}`,
          meta: (a.severity ?? "") + (a.step ? ` · ${a.step}` : ""),
          icon: a.severity?.toUpperCase() === "CRITICAL" ? "🚨" : "⚠",
          onSelect: () => router.push(`/admin/alarms?focus=${a.id}`),
        }));
    },
  };
}

// ── Equipment ────────────────────────────────────────────────────────

export function makeEquipmentSource(router: Router): PaletteSource {
  let cache: EquipmentRow[] | null = null;
  let cacheTs = 0;
  const TTL_MS = 60_000;

  return {
    sourceId: "equipment",
    group: "Equipment",
    limit: 8,
    fetch: async (query: string) => {
      const now = Date.now();
      if (!cache || now - cacheTs > TTL_MS) {
        const res = await fetch("/api/admin/fleet/equipment");
        if (!res.ok) throw new Error(`equipment HTTP ${res.status}`);
        const data = await res.json();
        const arr = Array.isArray(data) ? data : data.items ?? data.data ?? [];
        cache = arr as EquipmentRow[];
        cacheTs = now;
      }
      return cache
        .filter((e) => matches(query, e.equipment_id, e.name, e.status))
        .slice(0, 12)
        .map<PaletteItem>((e) => ({
          id: `eqp-${e.equipment_id}`,
          group: "Equipment",
          label: e.equipment_id + (e.name ? ` · ${e.name}` : ""),
          meta: e.status ?? "",
          icon: "🏭",
          onSelect: () => router.push(`/dashboard?toolId=${encodeURIComponent(e.equipment_id)}`),
        }));
    },
  };
}
