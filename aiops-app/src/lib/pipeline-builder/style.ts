import type { BlockCategory, PipelineStatus } from "./types";

/** PR-D1: higher-saturation category palette inspired by Pipeline Designer example.
 *  Values stay light-mode friendly; dark theme overrides handled via CSS vars
 *  (see PipelineThemeStyles.tsx).
 */
export const CATEGORY_COLORS: Record<BlockCategory, string> = {
  source:    "#0EA5E9",  // sky-500 — brighter cyan
  transform: "#8B5CF6",  // violet-500 — warmer purple (replaces slate for clarity)
  logic:     "#F59E0B",  // amber-500 — yellow per Claude palette (logic=rules)
  output:    "#EC4899",  // pink-500 — magenta-ish, more distinct from logic
  custom:    "#F97316",  // orange-500
};

/** Sidebar accordion heading (Chinese). */
export const CATEGORY_LABELS: Record<BlockCategory, string> = {
  source:    "資料源",
  transform: "處理",
  logic:     "邏輯與 ML",
  output:    "輸出",
  custom:    "自訂（Custom）",
};

/** Node caption label (uppercase English, shown under block title in canvas nodes). */
export const CATEGORY_CAPTIONS: Record<BlockCategory, string> = {
  source:    "SOURCE",
  transform: "TRANSFORM",
  logic:     "LOGIC",
  output:    "OUTPUT",
  custom:    "CUSTOM",
};

export const CATEGORY_ICONS: Record<BlockCategory, string> = {
  source:    "📥",
  transform: "⚙️",
  logic:     "🧠",
  output:    "🚀",
  custom:    "🔧",
};

/** Chinese human label map for block_id → display (shown only in sidebar tooltip). */
export const BLOCK_DISPLAY_NAMES_ZH: Record<string, string> = {
  block_process_history: "Process 歷史查詢",
  block_filter:          "條件過濾",
  block_join:            "關聯併表",
  block_groupby_agg:     "分組聚合",
  block_shift_lag:       "平移 / Lag",
  block_rolling_window:  "滑動視窗",
  block_threshold:       "閾值檢查",
  block_consecutive_rule:"連續規則",
  block_weco_rules:      "WECO 規則",
  block_chart:           "生成圖表",
  block_alert:           "發送告警",
};

/** Convert block_id to Title Case English for canvas display.
 *  e.g. block_process_history → "Process History"
 */
export function blockDisplayName(blockName: string): string {
  const stripped = blockName.replace(/^block_/, "");
  return stripped
    .split("_")
    .map((w) => w.length > 0 ? w[0].toUpperCase() + w.slice(1).toLowerCase() : w)
    .join(" ");
}

/** PR-D1: higher-saturation status pills with kind-colored tints.
 *  Phase 11 v6 — added "linked" for skill-owned pipelines (their lifecycle
 *  is driven by skill_documents.status; pb_pipelines.status is parked at
 *  this fixed value so they don't pollute the free-standing pipeline list). */
export const STATUS_COLORS: Record<PipelineStatus, { bg: string; fg: string; label: string }> = {
  draft:       { bg: "#F1F5F9", fg: "#475569", label: "● Draft" },
  validating:  { bg: "#FEF3C7", fg: "#92400E", label: "🟡 Validating" },
  locked:      { bg: "#FFEDD5", fg: "#9A3412", label: "🟠 Locked" },
  active:      { bg: "#DCFCE7", fg: "#15803D", label: "🔵 Active" },
  archived:    { bg: "#F1F5F9", fg: "#64748B", label: "⚪ Archived" },
  linked:      { bg: "#EDE9FE", fg: "#5B21B6", label: "🔗 Linked to Skill" },
};

/** Block status — orthogonal from pipeline status (blocks still use old enum). */
export const BLOCK_STATUS_COLORS: Record<
  "draft" | "pi_run" | "production" | "deprecated",
  { bg: string; fg: string; label: string }
> = {
  draft:       { bg: "#F1F5F9", fg: "#475569", label: "Draft" },
  pi_run:      { bg: "#FEF3C7", fg: "#B45309", label: "Pi-run" },
  production:  { bg: "#DCFCE7", fg: "#166534", label: "Production" },
  deprecated:  { bg: "#F1F5F9", fg: "#94A3B8", label: "Deprecated" },
};

/** PR-D1 canvas/node colors — driven by CSS vars so dark theme can override.
 *  Constants below are the LIGHT theme defaults; the browser reads from
 *  `:root` / `[data-theme="dark"]` CSS (see PipelineThemeStyles component).
 */
export const CANVAS_BG       = "var(--pb-canvas-bg)";
export const CANVAS_DOT      = "var(--pb-canvas-dot)";
export const NODE_BG         = "var(--pb-node-bg)";
export const NODE_BORDER     = "var(--pb-node-border)";
export const NODE_BORDER_HOVER = "var(--pb-node-border-hover)";
export const NODE_BORDER_SELECTED = "var(--pb-accent)";
export const NODE_TITLE_FG   = "var(--pb-text)";
export const NODE_CAPTION_FG = "var(--pb-text-3)";
export const EDGE_COLOR      = "var(--pb-edge)";
export const EDGE_COLOR_SELECTED = "var(--pb-accent)";

/** Mono font stack for technical fields (param values, row counts, ids, block names). */
export const MONO_FONT = "ui-monospace, 'JetBrains Mono', 'SF Mono', Menlo, monospace";
