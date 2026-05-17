"use client";

/**
 * Alarm Center (beta) — mounts the standalone React prototype from
 * Downloads/alarm center via static iframe.
 *
 * Source: public/alarm-center-beta/  (entire prototype copied as-is,
 * Alarm Center.html renamed to index.html for clean URL).
 *
 * The prototype is self-contained:
 *  - CDN React 18 + Babel standalone (runtime JSX transpile)
 *  - All data from in-page window.MOCK (data.js / shared-data.js)
 *  - No backend calls (1 file fetches local dc-state.json with try/catch fallback)
 *
 * For demo only — when promoted out of beta, port pieces into native
 * Next.js components for proper SSR + auth + style isolation.
 */
export default function AlarmCenterBetaPage() {
  return (
    <iframe
      src="/alarm-center-beta/index.html"
      title="Alarm Center (beta)"
      style={{
        width: "100%",
        height: "100vh",
        border: "none",
        display: "block",
      }}
    />
  );
}
