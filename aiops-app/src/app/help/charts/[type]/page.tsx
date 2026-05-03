"use client";

/**
 * Chart Catalog — single-chart detail page (/help/charts/{id}).
 *
 * Layout 65/35:
 *   ┌─ canvas (65%) ──┐ ┌─ info panel (35%) ──┐
 *   │  big chart     │  │  說明 / params       │
 *   │  +example sw    │  │  LLM prompts        │
 *   └────────────────┘  │  Style: Simple/Adv  │
 *                       │  儲存為預設           │
 *                       └─────────────────────┘
 */

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  SvgChartRenderer,
  StyleAdjuster,
  themeStyle,
  type ChartCardTheme,
} from "@/components/pipeline-builder/charts";
import { CHART_CATALOG, getChartById } from "@/lib/charts/catalog";
import { useUserChartTheme } from "@/lib/charts/useUserChartTheme";
import "@/styles/chart-tokens.css";

const TYPOGRAPHY = "Inter Tight, -apple-system, system-ui, sans-serif";

interface BlockMeta {
  name: string;
  description?: string;
  param_schema?: Record<string, unknown>;
}

export default function ChartDetailPage() {
  const params = useParams();
  const router = useRouter();
  const idStr = Array.isArray(params.type) ? params.type[0] : params.type;
  const entry = idStr ? getChartById(String(idStr)) : undefined;

  const [exampleIdx, setExampleIdx] = React.useState(0);

  // User-preference theme. Initial value = user's saved chart theme (or default).
  const { theme: userTheme, saveAsDefault } = useUserChartTheme();
  const [theme, setTheme] = React.useState<ChartCardTheme>(userTheme);
  const themeInitRef = React.useRef(false);
  React.useEffect(() => {
    if (themeInitRef.current) return;
    setTheme(userTheme);
    themeInitRef.current = true;
  }, [userTheme]);

  // Spec patch state — Advanced controls write here. Cleared on example switch.
  const baseSpec = React.useMemo(
    () => entry?.examples[exampleIdx].spec() ?? null,
    [entry, exampleIdx]
  );
  const [patch, setPatch] = React.useState<Record<string, unknown>>({});
  React.useEffect(() => { setPatch({}); }, [exampleIdx, idStr]);

  const liveSpec = React.useMemo(() => {
    if (!baseSpec) return null;
    return { ...baseSpec, ...patch };
  }, [baseSpec, patch]);

  const [blockMeta, setBlockMeta] = React.useState<BlockMeta | null>(null);
  const [metaLoading, setMetaLoading] = React.useState(true);

  React.useEffect(() => {
    if (!entry) return;
    setMetaLoading(true);
    fetch("/api/pipeline-builder/blocks")
      .then((r) => r.json())
      .then((data) => {
        const arr = Array.isArray(data) ? data : data?.data ?? [];
        const m = (arr as BlockMeta[]).find((b) => b.name === entry.blockId);
        setBlockMeta(m ?? null);
      })
      .catch(() => setBlockMeta(null))
      .finally(() => setMetaLoading(false));
  }, [entry]);

  if (!entry || !liveSpec) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "#75736d", fontFamily: TYPOGRAPHY }}>
        找不到 chart id「{idStr}」 ·{" "}
        <Link href="/help/charts" style={{ color: "#2563eb" }}>← 回 catalog</Link>
      </div>
    );
  }

  return (
    <div style={{
      display: "flex",
      height: "100vh",
      background: "#fafaf8",
      fontFamily: TYPOGRAPHY,
      color: "#1a1a17",
      overflow: "hidden",
    }}>
      {/* ── Left: chart canvas (65%) ─────────────────────────────── */}
      <div style={{
        flex: "0 0 65%",
        display: "flex",
        flexDirection: "column",
        borderRight: "1px solid #e8e8e4",
        overflow: "hidden",
      }}>
        {/* Top bar */}
        <div style={{
          padding: "14px 22px 10px",
          borderBottom: "1px solid #e8e8e4",
          background: "#fff",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <button
              onClick={() => router.push("/help/charts")}
              style={{
                fontSize: 11,
                color: "#75736d",
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: 0,
                fontFamily: "inherit",
              }}
            >
              ← Catalog
            </button>
            <span style={{ color: "#d4d4cf", fontSize: 11 }}>/</span>
            <span style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 10,
              padding: "2px 6px",
              borderRadius: 8,
              background: "#1a1a17",
              color: "#fff",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}>{entry.group}</span>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
            <h1 style={{ fontSize: 22, margin: 0, fontWeight: 700 }}>{entry.title}</h1>
            <code style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 11,
              color: "#75736d",
              background: "#f0eee8",
              padding: "2px 8px",
              borderRadius: 4,
            }}>
              {entry.blockId}
            </code>
          </div>
          <div style={{ fontSize: 12, color: "#4a4a45", marginTop: 4 }}>{entry.hint}</div>
        </div>

        {/* Canvas — fills remaining height */}
        <div style={{
          flex: 1,
          padding: "20px 22px",
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
          gap: 12,
          overflow: "auto",
          ...themeStyle(theme),
        }}>
          <div style={{ flex: 1, minHeight: 460, position: "relative" }}>
            {/* noStyleAdjuster — right panel hosts the dedicated StyleAdjuster
                so we don't double up. The chart re-renders when patch changes. */}
            <SvgChartRenderer spec={liveSpec} height={Math.max(460, 600)} noStyleAdjuster />
          </div>

          {/* Example switcher */}
          {entry.examples.length > 1 && (
            <div style={{
              padding: "10px 14px",
              background: "#fff",
              border: "1px solid #e8e8e4",
              borderRadius: 6,
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}>
              <span style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 10,
                color: "#75736d",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}>範例</span>
              <select
                value={exampleIdx}
                onChange={(e) => setExampleIdx(Number(e.target.value))}
                style={{
                  flex: 1,
                  padding: "5px 8px",
                  fontSize: 12,
                  border: "1px solid #d8d6d0",
                  borderRadius: 4,
                  outline: "none",
                  fontFamily: "inherit",
                }}
              >
                {entry.examples.map((ex, i) => (
                  <option key={i} value={i}>{ex.label}</option>
                ))}
              </select>
              {Object.keys(patch).length > 0 && (
                <button
                  onClick={() => setPatch({})}
                  style={{
                    padding: "4px 10px",
                    fontSize: 11,
                    border: "1px solid #d8d6d0",
                    borderRadius: 4,
                    background: "#fff",
                    cursor: "pointer",
                    color: "#75736d",
                  }}
                  title="把 Advanced 改的設定重置"
                >
                  Reset advanced
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Right: info panel (35%) ──────────────────────────────── */}
      <aside style={{
        flex: 1,
        minWidth: 360,
        display: "flex",
        flexDirection: "column",
        background: "#fff",
        overflow: "hidden",
      }}>
        <div style={{ flex: 1, overflowY: "auto", padding: "20px 22px" }}>
          {/* Style settings — top of panel. Saving as default sets the
              initial theme for ALL future chart renders for this user
              (Pipeline Builder results / Alarm Detail / Dashboard / Chat). */}
          <Section title="樣式設定">
            <div style={{ fontSize: 11, color: "#75736d", marginBottom: 8, lineHeight: 1.6 }}>
              {entry.hasAdvanced
                ? "Simple = 11 項跨 chart 通用控制（顏色 / 線粗 / 字級）；Advanced = 此 chart 獨有的設定（如 SPC WECO 規則顏色、Wafer notch 位置等）。"
                : "此 chart 的 Simple 11 項控制已涵蓋全部可調設定，無 Advanced 選項。"}
            </div>
            <div style={{
              fontSize: 11,
              color: "#1d4ed8",
              background: "#eff6ff",
              border: "1px solid #bfdbfe",
              borderRadius: 4,
              padding: "8px 10px",
              marginBottom: 10,
              lineHeight: 1.55,
            }}>
              💾 點 ✦ 面板底的「儲存為我的預設樣式」後，
              <strong>新建 pipeline 時所有 chart 的初始樣式都會套用這組設定</strong>
              （Pipeline Builder Results / Alarm Center / Dashboard 也跟著生效）。
              個別 chart 卡仍可即時用 ✦ 暫時微調（不影響預設）。
            </div>
            <div style={{
              padding: 12,
              border: "1px solid #e8e8e4",
              borderRadius: 6,
              background: "#fafaf8",
              minHeight: 56,
              position: "relative",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              ...themeStyle(theme),
            }}>
              <div style={{ fontSize: 11, color: "#75736d" }}>
                點右上 ✦ 開啟設定面板
              </div>
              <StyleAdjuster
                theme={theme}
                setTheme={setTheme}
                chartType={entry.chartType}
                advancedProps={{ baseSpec: baseSpec as Record<string, unknown>, patch, setPatch }}
                onSaveAsDefault={() => saveAsDefault(theme)}
              />
            </div>
          </Section>

          <Section title="說明">
            {metaLoading ? (
              <div style={{ fontSize: 11, color: "#a4a4a8", fontFamily: "JetBrains Mono, monospace" }}>載入 block metadata...</div>
            ) : blockMeta?.description ? (
              <pre style={{
                margin: 0,
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 11,
                lineHeight: 1.7,
                color: "#4a4a45",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}>{blockMeta.description}</pre>
            ) : (
              <div style={{ fontSize: 11, color: "#a4a4a8" }}>(無 block 描述)</div>
            )}
          </Section>

          <Section title="跟 LLM 怎麼下 prompt">
            <div style={{ fontSize: 11, color: "#75736d", marginBottom: 8 }}>
              下面 prompt 直接複製到 Pipeline Builder 的 AI Agent panel — advisor classifier 會分桶 → build_pipeline_live 把 chart 建出來。
            </div>
            {entry.llmPrompts.map((p, i) => (
              <div key={i} style={{
                padding: "10px 12px",
                background: "#f8f7f3",
                border: "1px solid #e8e8e4",
                borderRadius: 6,
                fontSize: 12,
                lineHeight: 1.6,
                marginBottom: 8,
                position: "relative",
              }}>
                <button
                  onClick={() => navigator.clipboard?.writeText(p)}
                  style={{
                    position: "absolute",
                    top: 6,
                    right: 6,
                    padding: "2px 8px",
                    fontSize: 10,
                    border: "1px solid #d8d6d0",
                    borderRadius: 3,
                    background: "#fff",
                    cursor: "pointer",
                    fontFamily: "inherit",
                  }}
                  title="複製"
                >
                  📋
                </button>
                <span style={{ paddingRight: 36, color: "#1a1a17" }}>「{p}」</span>
              </div>
            ))}
          </Section>

          {/* CTA at bottom — natural conclusion after user has read 用途/
              prompt/style. Goes to /new with ?block=... prefill. */}
          <Link
            href={`/admin/pipeline-builder/new?from=catalog&block=${entry.blockId}`}
            style={{
              display: "block",
              padding: "12px 14px",
              background: "#2563eb",
              color: "#fff",
              textDecoration: "none",
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 600,
              textAlign: "center",
              marginTop: 8,
            }}
          >
            📋 用此 block 建 pipeline →
          </Link>
        </div>
      </aside>
    </div>
  );
}

// ── Section helper ─────────────────────────────────────────────────────
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 22 }}>
      <h2 style={{
        fontSize: 11,
        fontFamily: "JetBrains Mono, monospace",
        color: "#75736d",
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        margin: "0 0 8px 0",
        fontWeight: 600,
      }}>{title}</h2>
      {children}
    </div>
  );
}
