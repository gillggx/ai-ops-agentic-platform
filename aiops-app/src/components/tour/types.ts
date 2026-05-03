/**
 * Shared types for the tour + cross-surface command palette system.
 *
 * Surface = the page / area that owns a tour (e.g. "pipeline-builder",
 * "alarm-center", "fleet"). Each surface registers:
 *   - a steps list (for Tour)
 *   - optionally a PaletteSource (for the cross-surface Cmd+K palette)
 */

export interface TourStep {
  /** Short uppercase label shown above the title (e.g. "STEP 1 / 8"). */
  /** Heading shown in bold inside the bubble. */
  title: string;
  /** Body markdown / plain text — single paragraph recommended. */
  body: string;
  /** CSS selector for the spotlight target. `null` → centered modal style. */
  target: string | null;
  /** Where the bubble sits relative to the target. */
  placement: "left" | "right" | "top" | "bottom" | "center";
  /** Custom rect computer (overrides target selector). Useful for sub-areas
   *  inside a larger element (e.g. "this 600x200 area inside the canvas"). */
  selectorRect?: () => { left: number; top: number; width: number; height: number } | null;
}

export type SurfaceId = "pipeline-builder" | "alarm-center" | "fleet" | "fleet-eqp";

export interface PaletteItem {
  /** Stable id used for keyboard nav + selection callback. */
  id: string;
  /** Visible primary text. */
  label: string;
  /** Optional small text on the right (e.g. status, updated time, kind). */
  meta?: string;
  /** 1-2 char visual prefix. Emoji OK. */
  icon?: string;
  /** Group label — items with the same group cluster under one header. */
  group: string;
  /** Click / Enter handler. Receives no args; capture context via closure. */
  onSelect: () => void;
}

/**
 * A PaletteSource feeds items into the global Cmd+K palette. Sources can be
 * "always-on" (registered at app shell mount, e.g. Pipelines / Alarms /
 * Equipment via API) or "context-aware" (registered when a specific surface
 * mounts, e.g. Canvas Nodes when Pipeline Builder is open).
 */
export interface PaletteSource {
  /** Stable identifier so a remount of the same surface replaces, not stacks. */
  sourceId: string;
  /** Group label shown above this source's items in the palette. */
  group: string;
  /**
   * Returns items matching the query. Async so sources can hit APIs.
   * Returning [] means "no matches"; throwing or rejecting is treated as
   * "source unavailable" and the palette quietly omits the group.
   */
  fetch: (query: string) => Promise<PaletteItem[]>;
  /** Items per source cap to keep panel scrollable. Default 8. */
  limit?: number;
}
