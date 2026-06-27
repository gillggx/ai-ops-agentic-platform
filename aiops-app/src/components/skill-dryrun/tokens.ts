/**
 * Design tokens for the Dry-run / Editor separation surface.
 *
 * Mirrors README §"Design Tokens" in /Users/gill/Downloads/design_handoff_dryrun_separation.
 * Source of truth for colors / radii / shadows. Components should import from
 * here rather than inlining hex codes so the design system can evolve.
 */

export const TK = {
  // Surfaces
  page: "#f3f4f6",
  card: "#fff",

  // Ink
  ink: "#23252b",
  title: "#1c1d22",
  body: "#6b6f78",
  faint: "#8a8e97",
  faint2: "#9398a1",
  monoLabel: "#a4a8b0",
  monoLabel2: "#9b9fa7",
  monoLabel3: "#b6bac1",

  // Accent — pipeline / edit primary
  accent: "#5b51d8",
  accentBg: "#ecebfb",
  accentLink: "#3f6bd6",

  // Sandbox tint
  sandbox: "#5b6bd6",
  sandboxBg: "#eef1ff",

  // Pass (green)
  pass: "#1a7d4a",
  passBadgeBg: "#e3f4ea",
  passBadgeBorder: "#c4e8d2",
  passBoxBg: "#f4fbf6",
  passBoxBorder: "#cfe9d8",

  // Fail (red)
  fail: "#c1382c",
  failBadgeBg: "#fbe2de",
  failBadgeBorder: "#f2cdc7",
  failBoxBg: "#fdf3f1",
  failBoxBorder: "#ec9e96",
  failDetailBorder: "#f1d9d5",

  // Misc
  amberDot: "#e0a32e",
  blackPrimary: "#1c1d22",
  border: "#eef0f2",
  divider: "#f1f2f4",
  pillBorder: "#e4e6ea",

  // Edit-this-step highlight
  highlightBorder: "#c7c8ea",
  highlightBg: "#fbfbff",
  editPanelBg: "#f6f7fd",
  editPanelBorder: "#dcdcf3",
  editInputBorder: "#c7c8ea",

  // Scrims
  scrimMid: "rgba(24,25,30,.42)",
  scrimHeavy: "rgba(24,25,30,.46)",
} as const;

// Shadows — keep as strings for direct use in CSSProperties
export const SHADOW = {
  card: "0 1px 3px rgba(15,18,30,.08), 0 12px 40px rgba(15,18,30,.06)",
  dialog: "0 24px 70px rgba(15,18,30,.4)",
  report: "0 26px 70px rgba(15,18,30,.4)",
  running: "0 20px 60px rgba(15,18,30,.34)",
} as const;

// Type stacks
export const FONT = {
  ui: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  mono: "ui-monospace, 'SF Mono', Menlo, monospace",
} as const;

// Common style fragments
export const MONO_EYEBROW: React.CSSProperties = {
  fontFamily: FONT.mono,
  fontWeight: 600,
  fontSize: 11,
  letterSpacing: "0.13em",
  textTransform: "uppercase",
  color: TK.monoLabel,
};

export const SANDBOX_PILL: React.CSSProperties = {
  display: "inline-block",
  fontFamily: FONT.mono,
  fontWeight: 600,
  fontSize: 10.5,
  letterSpacing: "0.04em",
  padding: "4px 9px",
  borderRadius: 6,
  color: TK.sandbox,
  background: TK.sandboxBg,
};
