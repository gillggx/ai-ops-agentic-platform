"use client";

/**
 * TourRoot — wraps TourProvider + registers default cross-surface palette
 * sources (pipelines / alarms / equipment) once at app shell mount.
 *
 * Surfaces still register context-aware sources of their own (e.g.
 * Pipeline Builder canvas nodes) via useTour().registerPaletteSource().
 */

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { TourProvider, useTour } from "./TourProvider";
import {
  makeAlarmsSource,
  makeEquipmentSource,
  makePipelinesSource,
} from "./sources";

function DefaultSources({ children }: { children: ReactNode }) {
  const { registerPaletteSource } = useTour();
  const router = useRouter();

  useEffect(() => {
    const u1 = registerPaletteSource(makePipelinesSource(router));
    const u2 = registerPaletteSource(makeAlarmsSource(router));
    const u3 = registerPaletteSource(makeEquipmentSource(router));
    return () => {
      u1();
      u2();
      u3();
    };
  }, [registerPaletteSource, router]);

  return <>{children}</>;
}

export function TourRoot({ children }: { children: ReactNode }) {
  return (
    <TourProvider>
      <DefaultSources>{children}</DefaultSources>
    </TourProvider>
  );
}
