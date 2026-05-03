/**
 * Chart Catalog — grid index. Each card → /help/charts/{id} detail.
 *
 * Replaces the dev-only /dev/charts (still works as redirect; see
 * src/app/dev/charts/page.tsx). Auth-gated for any logged-in user;
 * available to PE / IT_ADMIN / ON_DUTY alike.
 */

"use client";

import * as React from "react";
import Link from "next/link";
import { CHART_CATALOG, CHART_GROUPS, type ChartGroup } from "@/lib/charts/catalog";
import { SvgChartRenderer } from "@/components/pipeline-builder/charts";
import "@/styles/chart-tokens.css";

const TYPOGRAPHY = "Inter Tight, -apple-system, system-ui, sans-serif";

export default function ChartCatalogGridPage() {
  const [filter, setFilter] = React.useState<ChartGroup | "All">("All");
  const [query, setQuery] = React.useState("");

  const visible = React.useMemo(() => {
    return CHART_CATALOG.filter((c) => {
      if (filter !== "All" && c.group !== filter) return false;
      if (query) {
        const q = query.toLowerCase();
        return (
          c.title.toLowerCase().includes(q) ||
          c.hint.toLowerCase().includes(q) ||
          c.blockId.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [filter, query]);

  const groupCounts = React.useMemo(() => {
    const out: Record<string, number> = { All: CHART_CATALOG.length };
    for (const g of CHART_GROUPS) {
      out[g] = CHART_CATALOG.filter((c) => c.group === g).length;
    }
    return out;
  }, []);

  return (
    <div style={{
      padding: "24px 32px",
      background: "#fafaf8",
      minHeight: "100vh",
      fontFamily: TYPOGRAPHY,
      color: "#1a1a17",
    }}>
      {/* Header */}
      <div style={{ marginBottom: 18 }}>
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: "#75736d", letterSpacing: "0.5px", textTransform: "uppercase" }}>
          📚 Chart Catalog · {CHART_CATALOG.length} charts
        </div>
        <h1 style={{ fontSize: 26, margin: "4px 0 6px 0", fontWeight: 700 }}>
          Chart 元件目錄
        </h1>
        <p style={{ fontSize: 13, color: "#4a4a45", margin: 0, maxWidth: 760 }}>
          系統內建 18 種 chart components 的完整 catalog。點任一張進入詳情頁看：
          <strong> 用途、何時用、參數、LLM prompt 範例、Style 設定</strong>。
          每張可以 ✦ 即時試樣式、儲存為你的個人預設。
        </p>
      </div>

      {/* Filter chips + search */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        marginBottom: 16,
        flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", gap: 6 }}>
          {(["All", ...CHART_GROUPS] as const).map((g) => (
            <button
              key={g}
              onClick={() => setFilter(g)}
              style={{
                padding: "6px 12px",
                fontSize: 12,
                borderRadius: 14,
                border: "1px solid",
                borderColor: filter === g ? "#1a1a17" : "#d8d6d0",
                background: filter === g ? "#1a1a17" : "#fff",
                color: filter === g ? "#fff" : "#4a4a45",
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              {g} <span style={{ opacity: 0.6, marginLeft: 3, fontFamily: "JetBrains Mono, monospace" }}>{groupCounts[g] ?? 0}</span>
            </button>
          ))}
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜尋 chart 名稱 / 用途 / block name..."
          style={{
            flex: 1,
            minWidth: 220,
            padding: "7px 12px",
            fontSize: 12,
            border: "1px solid #d8d6d0",
            borderRadius: 6,
            outline: "none",
            fontFamily: "inherit",
          }}
        />
      </div>

      {/* Grid */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
        gap: 14,
      }}>
        {visible.map((c) => (
          <Link
            key={c.id}
            href={`/help/charts/${c.id}`}
            style={{
              textDecoration: "none",
              color: "inherit",
              border: "1px solid #d8d6d0",
              borderRadius: 8,
              background: "#fff",
              padding: "12px 14px 14px",
              display: "flex",
              flexDirection: "column",
              gap: 4,
              transition: "border-color 120ms, box-shadow 120ms, transform 120ms",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = "#2563eb";
              e.currentTarget.style.boxShadow = "0 4px 12px rgba(37,99,235,0.08)";
              e.currentTarget.style.transform = "translateY(-1px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = "#d8d6d0";
              e.currentTarget.style.boxShadow = "none";
              e.currentTarget.style.transform = "translateY(0)";
            }}
          >
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
              <span style={{ fontWeight: 600, fontSize: 13 }}>{c.title}</span>
              <span style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 9,
                padding: "2px 6px",
                borderRadius: 8,
                background: GROUP_COLOR[c.group],
                color: "#fff",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                flexShrink: 0,
              }}>{c.group}</span>
            </div>
            <div style={{ fontSize: 11, color: "#75736d", lineHeight: 1.5, minHeight: 32 }}>
              {c.hint}
            </div>
            <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: "#a4a4a8", marginTop: 2 }}>
              {c.blockId}
            </div>
            <div style={{
              marginTop: 8,
              paddingTop: 8,
              borderTop: "1px solid #f0eee8",
              minHeight: 140,
              display: "flex",
              alignItems: "stretch",
            }}>
              <div style={{ flex: 1 }}>
                <SvgChartRenderer spec={c.examples[0].spec()} height={140} noStyleAdjuster />
              </div>
            </div>
          </Link>
        ))}
        {visible.length === 0 && (
          <div style={{ gridColumn: "1 / -1", padding: 40, textAlign: "center", color: "#75736d" }}>
            無符合的 chart
          </div>
        )}
      </div>
    </div>
  );
}

const GROUP_COLOR: Record<ChartGroup, string> = {
  Primitive: "#475569",
  EDA: "#0d9488",
  SPC: "#dc2626",
  Diagnostic: "#7c3aed",
  Wafer: "#2563eb",
};
