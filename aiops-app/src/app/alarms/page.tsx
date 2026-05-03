"use client";

/**
 * Alarm Center v2 — cluster-first cockpit.
 * Layout, behavior, and tokens specified in
 * docs/SPEC_alarm_center_redesign_v1.md (Approved 2026-05-01).
 * Per-alarm detail UI lives in components/alarms/AlarmDetailLegacy.tsx
 * (extracted unchanged from this file's previous version).
 */

import "@/styles/alarm-center.css";
import { useEffect } from "react";
import { AlarmCenterShell } from "@/components/alarms/AlarmCenterShell";
import SurfaceTour from "@/components/tour/SurfaceTour";
import { ALARM_CENTER_STEPS } from "@/components/tour/steps/alarm-center";

const FONT_LINK = "https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap";

export default function AlarmCenterPage() {
  // Lazy-load the cockpit fonts only on this route, so the rest of the
  // app keeps using the global system stack.
  useEffect(() => {
    const id = "alarm-center-fonts";
    if (document.getElementById(id)) return;
    const link = document.createElement("link");
    link.id = id;
    link.rel = "stylesheet";
    link.href = FONT_LINK;
    document.head.appendChild(link);
  }, []);

  return (
    <>
      <AlarmCenterShell />
      <SurfaceTour surfaceId="alarm-center" steps={ALARM_CENTER_STEPS} />
    </>
  );
}
