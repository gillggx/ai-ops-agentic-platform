/** Public API for the tour + cross-surface command palette system. */

export { TourProvider, useTour } from "./TourProvider";
export { TourRoot } from "./TourRoot";
export { default as Tour } from "./Tour";
export { default as HelpButton } from "./HelpButton";
export { default as SurfaceTour } from "./SurfaceTour";
export { default as CommandPalette } from "./CommandPalette";
export { useTourFirstVisit, resetTourMemory } from "./useTourFirstVisit";

export type { TourStep, SurfaceId, PaletteItem, PaletteSource } from "./types";

export { PIPELINE_BUILDER_STEPS } from "./steps/pipeline-builder";
export { ALARM_CENTER_STEPS } from "./steps/alarm-center";
export { FLEET_STEPS, EQP_DETAIL_STEPS } from "./steps/fleet";

export {
  makePipelinesSource,
  makeAlarmsSource,
  makeEquipmentSource,
} from "./sources";
