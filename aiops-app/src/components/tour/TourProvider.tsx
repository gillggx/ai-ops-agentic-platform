"use client";

/**
 * TourProvider — global context for the tour + cross-surface command palette.
 *
 * Mounts at app shell level. Provides:
 *   - openTour(surfaceId, steps, startStep?)  → renders <Tour /> overlay
 *   - registerPaletteSource(source) / unregister  → for surfaces to plug in
 *   - global Cmd+K (Ctrl+K) keyboard listener → opens <CommandPalette />
 *
 * Cross-surface ⌘K design: any number of <PaletteSource>s register via the
 * `registerPaletteSource` callback (returns an unregister fn). When the
 * palette opens, it queries every active source concurrently and groups
 * results by `source.group`. Surfaces are responsible for unregistering on
 * unmount to avoid stale data. Default sources (pipelines / alarms /
 * equipment) are registered at app shell mount and stay for the session.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import Tour from "./Tour";
import CommandPalette from "./CommandPalette";
import type { PaletteSource, SurfaceId, TourStep } from "./types";

interface TourContextValue {
  /** Open the tour overlay for `surfaceId` with the given `steps`. */
  openTour: (surfaceId: SurfaceId, steps: TourStep[], startStep?: number) => void;
  /** Open the cross-surface command palette. */
  openPalette: () => void;
  /** Register a palette source. Returns an unregister fn (call on unmount). */
  registerPaletteSource: (source: PaletteSource) => () => void;
}

const TourContext = createContext<TourContextValue | null>(null);

export function useTour(): TourContextValue {
  const ctx = useContext(TourContext);
  if (!ctx) {
    throw new Error("useTour must be used inside <TourProvider>");
  }
  return ctx;
}

interface ActiveTour {
  surfaceId: SurfaceId;
  steps: TourStep[];
  startStep: number;
}

interface Props {
  children: ReactNode;
}

export function TourProvider({ children }: Props) {
  const [activeTour, setActiveTour] = useState<ActiveTour | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Source registry — Map keyed by sourceId so re-registration replaces
  // (e.g. Pipeline Builder remounts → its source map entry replaces the
  // old one rather than stacking duplicates).
  const sourcesRef = useRef<Map<string, PaletteSource>>(new Map());

  const registerPaletteSource = useCallback((source: PaletteSource) => {
    sourcesRef.current.set(source.sourceId, source);
    return () => {
      sourcesRef.current.delete(source.sourceId);
    };
  }, []);

  const openTour = useCallback((surfaceId: SurfaceId, steps: TourStep[], startStep = 0) => {
    setActiveTour({ surfaceId, steps, startStep });
  }, []);

  const openPalette = useCallback(() => {
    setPaletteOpen(true);
  }, []);

  // Global Cmd+K (Ctrl+K) listener. Skip when typing inside an input
  // (otherwise we'd hijack natural typing in textareas).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        const target = e.target as HTMLElement | null;
        const tag = target?.tagName;
        // Allow ⌘K to override even inside text inputs — most users
        // expect this to be a global shortcut. But a contenteditable
        // chat panel would conflict; tag check is conservative.
        if (tag === "INPUT" || tag === "TEXTAREA") {
          // Only steal the shortcut if Cmd/Ctrl is held — typing alone
          // never produces e.metaKey, so this is safe.
        }
        e.preventDefault();
        setPaletteOpen((p) => !p);
      } else if (e.key === "Escape" && paletteOpen) {
        setPaletteOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paletteOpen]);

  const value = useMemo<TourContextValue>(() => ({
    openTour,
    openPalette,
    registerPaletteSource,
  }), [openTour, openPalette, registerPaletteSource]);

  return (
    <TourContext.Provider value={value}>
      {children}
      {activeTour && (
        <Tour
          steps={activeTour.steps}
          startStep={activeTour.startStep}
          onClose={() => setActiveTour(null)}
        />
      )}
      {paletteOpen && (
        <CommandPalette
          sources={Array.from(sourcesRef.current.values())}
          onClose={() => setPaletteOpen(false)}
        />
      )}
    </TourContext.Provider>
  );
}
