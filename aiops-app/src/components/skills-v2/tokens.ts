/**
 * Skills v2 design tokens — direct from the spec §5.
 *
 * Font stack uses IBM Plex Sans / Mono per spec §0.  The fonts are loaded
 * via a <link> tag injected at page mount (avoids a hard dependency on
 * a global tailwind/font-loader change).  Falls back to system-ui if the
 * Plex stylesheet is blocked.
 */

export const TK = {
  // Identity colors
  patrol:           "#b06d00",
  patrolDeep:       "#8a5500",
  patrolTint:       "#fbf2e0",
  patrolBorder:     "#ecdcb6",

  datacheck:        "#2f49b0",
  datacheckTint:    "#e9ecfd",
  datacheckBorder:  "#cdd5f7",

  tool:             "#73777f",
  toolTint:         "#eef0f3",
  toolBorder:       "#e1e4e8",

  // Indigo (compile / pipeline emphasis)
  indigo:           "#4a41c0",
  indigoTint:       "#ecebfb",

  // Strip dots
  stripTrigger:     "#d9534f",
  stripChecklist:   "#d9a441",
  stripAlarmGate:   "#5b51d8",
  stripOutcome:     "#4a72d0",

  // Schedule pill
  pillBlue:         "#3f51c5",
  pillBlueBg:       "#f3f4fe",
  pillBlueBorder:   "#cdd1f5",

  // Neutrals
  page:             "#eef0f2",
  card:             "#fff",
  ink:              "#1a1c1f",
  body:             "#6b7078",
  faint:            "#9aa0a8",
  divider:          "#eef0f2",
  divider2:         "#ececec",

  // Black primary
  black:            "#1a1c1f",
} as const;

export const FONT = {
  sans: "'IBM Plex Sans', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  mono: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace",
} as const;

/** Inject Plex stylesheet exactly once. Called from each v2 page's mount. */
export function ensurePlexFont(): void {
  if (typeof document === "undefined") return;
  if (document.getElementById("v2-plex-font")) return;
  const link = document.createElement("link");
  link.id = "v2-plex-font";
  link.rel = "stylesheet";
  link.href =
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap";
  document.head.appendChild(link);
}

export const ROLE_COLORS = {
  patrol:    { color: TK.patrol,    tint: TK.patrolTint,    border: TK.patrolBorder },
  datacheck: { color: TK.datacheck, tint: TK.datacheckTint, border: TK.datacheckBorder },
  tool:      { color: TK.tool,      tint: TK.toolTint,      border: TK.toolBorder },
} as const;
