/**
 * UI themes (design_handoff_operation_platform_v2). Slugs must match both
 * src/styles/themes.css [data-theme=…] blocks and Java's SUPPORTED_THEMES.
 * `swatch` = the theme's primary (--p), used for the picker dots.
 */
export const DEFAULT_THEME = "pine";

export const THEMES: ReadonlyArray<{ slug: string; label: string; swatch: string }> = [
  { slug: "pine",      label: "松砂 Pine",       swatch: "#1E5A44" },
  { slug: "oxblood",   label: "暗紅 Oxblood",    swatch: "#8C2F39" },
  { slug: "aubergine", label: "茄紫 Aubergine",  swatch: "#8A2C6B" },
  { slug: "petrol",    label: "石油藍綠 Petrol", swatch: "#0C6473" },
  { slug: "olive",     label: "橄欖 Olive",      swatch: "#5F7137" },
  { slug: "slate",     label: "鋼灰藍 Slate",    swatch: "#3E5C76" },
  { slug: "raspberry", label: "覆盆莓 Raspberry", swatch: "#B4326A" },
  { slug: "lime",      label: "石墨萊姆 Lime",   swatch: "#5E6E12" },
  { slug: "cocoa",     label: "可可 Cocoa",      swatch: "#6B4A2E" },
  { slug: "violet",    label: "墨紫 Violet",     swatch: "#6A3EA1" },
];

/** Apply a theme now (CSS vars flip live) + cache for pre-paint. */
export function applyTheme(slug: string): void {
  document.documentElement.dataset.theme = slug;
  try {
    localStorage.setItem("ui_theme", slug);
  } catch {
    /* private mode etc. — DB still persists */
  }
}
