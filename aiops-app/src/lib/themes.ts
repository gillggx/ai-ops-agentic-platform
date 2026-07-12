/**
 * UI themes (design_handoff_aiops_platform R1, 2026-07-12). Slugs must match
 * both src/styles/themes.css [data-theme=…] blocks and Java's SUPPORTED_THEMES.
 * `swatch` = the theme's primary (--p), used for the picker dots.
 */
export const DEFAULT_THEME = "pine";

export const THEMES: ReadonlyArray<{ slug: string; label: string; swatch: string }> = [
  { slug: "pine",     label: "松砂 Pine",     swatch: "#1E5A44" },
  { slug: "indigo",   label: "靛霧 Indigo",   swatch: "#4F46E5" },
  { slug: "terra",    label: "赭陶 Terra",    swatch: "#B4552D" },
  { slug: "navy",     label: "海墨 Navy",     swatch: "#1F4E79" },
  { slug: "teal",     label: "蒼杉 Teal",     swatch: "#0F766E" },
  { slug: "plum",     label: "梅紫 Plum",     swatch: "#8E3A76" },
  { slug: "graphite", label: "石墨 Graphite", swatch: "#374151" },
  { slug: "bordeaux", label: "酒紅 Bordeaux", swatch: "#8C2F39" },
  { slug: "olive",    label: "苔金 Olive",    swatch: "#667032" },
  { slug: "lake",     label: "湖水 Lake",     swatch: "#0E7490" },
];

/** 舊主題 slug（operation_platform_v2 世代）→ 最接近的新主題。 */
const LEGACY_MAP: Record<string, string> = {
  oxblood: "bordeaux", aubergine: "plum", petrol: "teal", slate: "navy",
  raspberry: "plum", lime: "olive", cocoa: "terra", violet: "indigo",
};

export function normalizeTheme(slug: string | null | undefined): string {
  if (!slug) return DEFAULT_THEME;
  if (THEMES.some((t) => t.slug === slug)) return slug;
  return LEGACY_MAP[slug] ?? DEFAULT_THEME;
}

/** Apply a theme now (CSS vars flip live) + cache for pre-paint. */
export function applyTheme(slug: string): void {
  const s = normalizeTheme(slug);
  document.documentElement.dataset.theme = s;
  try {
    localStorage.setItem("ui_theme", s);
  } catch {
    /* private mode etc. — DB still persists */
  }
}
