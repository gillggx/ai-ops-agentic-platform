"use client";

/**
 * SurfaceTour — 1-line drop-in for any page that has a tour.
 *
 * Mounts the floating ? HelpButton + auto-fires the tour on first visit
 * (per-surface, persisted in localStorage). Re-clicks of ? always re-open.
 *
 * Usage:
 *   <SurfaceTour surfaceId="pipeline-builder" steps={PIPELINE_BUILDER_STEPS} />
 *
 * Place once near the root of the surface's main page/layout. Provider
 * (TourRoot) lives in app/layout.tsx and is always available.
 */

import { useCallback } from "react";
import HelpButton from "./HelpButton";
import { useTour } from "./TourProvider";
import { useTourFirstVisit } from "./useTourFirstVisit";
import type { SurfaceId, TourStep } from "./types";

interface Props {
  surfaceId: SurfaceId;
  steps: TourStep[];
  /** Bump when tour content changes meaningfully so users see the new tour. */
  version?: number;
}

export default function SurfaceTour({ surfaceId, steps, version = 1 }: Props) {
  const { openTour } = useTour();

  const open = useCallback(() => {
    openTour(surfaceId, steps);
  }, [openTour, surfaceId, steps]);

  useTourFirstVisit(surfaceId, open, version);

  return <HelpButton onClick={open} />;
}
