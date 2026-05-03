"use client";

/**
 * useTourFirstVisit — fires `onFirstVisit` once per (surface, version) tuple,
 * persisted in localStorage. Bumping `version` (e.g. when tour steps change
 * meaningfully) re-triggers for everyone.
 *
 * Storage key: `tour:visited:<surfaceId>:v<version>` = "1" once seen.
 */

import { useEffect } from "react";
import type { SurfaceId } from "./types";

const KEY = (surfaceId: SurfaceId, version: number) =>
  `tour:visited:${surfaceId}:v${version}`;

export function useTourFirstVisit(
  surfaceId: SurfaceId,
  onFirstVisit: () => void,
  version = 1,
) {
  useEffect(() => {
    if (typeof window === "undefined") return;
    const key = KEY(surfaceId, version);
    try {
      if (window.localStorage.getItem(key)) return; // already seen
      window.localStorage.setItem(key, "1");
      // Defer one tick so the surface's DOM has a chance to mount before
      // the tour's selectors look for elements.
      const t = window.setTimeout(() => onFirstVisit(), 250);
      return () => window.clearTimeout(t);
    } catch {
      // localStorage might be disabled (private mode, quota); silently skip.
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [surfaceId, version]);
}

/** Manual reset — for a "Reset all tours" admin action or a debug hook. */
export function resetTourMemory(surfaceId?: SurfaceId): void {
  if (typeof window === "undefined") return;
  try {
    if (surfaceId) {
      // Clear all versions of this surface
      Object.keys(window.localStorage).forEach((k) => {
        if (k.startsWith(`tour:visited:${surfaceId}:`)) {
          window.localStorage.removeItem(k);
        }
      });
    } else {
      Object.keys(window.localStorage).forEach((k) => {
        if (k.startsWith("tour:visited:")) {
          window.localStorage.removeItem(k);
        }
      });
    }
  } catch {
    // ignore
  }
}
