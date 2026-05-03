"use client";

/**
 * /topology — standalone Topology Workbench page.
 *
 * Replaced the old TopologyCanvas + sidebar layout with the new workbench
 * (multi-lane trace + 9 view kinds + 28-day timeline scrubber + fullscreen).
 *
 * URL param compatibility (kept so old deep-links still work):
 *   ?type=lot|tool|recipe|apc|step|fdc|spc&id=<obj_id>
 *     → translated to initialFocus={ kind, id }
 *   Legacy types (DC / SPC / EC / FDC / OCAP) collapse to their nearest
 *   equivalent kind. OCAP isn't a topology kind — open as plain trace.
 */

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import type { FocusRef, Kind } from "@/components/ontology/topology-v2/lib/types";

const TopologyWorkbench = dynamic(
  () => import("@/components/ontology/topology-v2/TopologyWorkbench"),
  {
    ssr: false,
    loading: () => (
      <div style={{
        height: "100%", background: "#f7f8fc",
        display: "flex", alignItems: "center", justifyContent: "center", color: "#a0aec0",
      }}>載入...</div>
    ),
  },
);

const LEGACY_KIND_MAP: Record<string, Kind> = {
  // Direct
  lot:    "lot",
  tool:   "tool",
  recipe: "recipe",
  apc:    "apc",
  step:   "step",
  fdc:    "fdc",
  spc:    "spc",
  // Legacy collapses
  dc:     "lot",      // DC was lot-bound; show as lot
  ec:     "tool",     // EC was tool-bound
  ocap:   "lot",      // OCAP events: collapse to associated lot
};

function parseFocusFromParams(typeRaw: string, idRaw: string): FocusRef | null {
  if (!idRaw) return null;
  const kind = LEGACY_KIND_MAP[typeRaw.toLowerCase()];
  if (!kind) return null;
  // OCAP id format: "LOT-xxx|STEP_yyy" — take the lot portion
  const id = typeRaw.toLowerCase() === "ocap" && idRaw.includes("|") ? idRaw.split("|")[0] : idRaw;
  return { kind, id };
}

function TopologyPageInner() {
  const sp = useSearchParams();
  const focus = parseFocusFromParams(sp.get("type") ?? "", sp.get("id") ?? "");

  return (
    <div style={{ height: "100%", background: "#fff", overflow: "hidden" }}>
      <TopologyWorkbench
        mode="standalone"
        initialFocus={focus}
      />
    </div>
  );
}

export default function TopologyPage() {
  return (
    <Suspense fallback={
      <div style={{
        height: "100vh", background: "#f7f8fc",
        display: "flex", alignItems: "center", justifyContent: "center", color: "#a0aec0",
      }}>載入...</div>
    }>
      <TopologyPageInner />
    </Suspense>
  );
}
