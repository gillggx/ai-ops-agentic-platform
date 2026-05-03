"use client";

import { useEffect, useMemo, useState } from "react";
import { listBlocks } from "@/lib/pipeline-builder/api";
import type { BlockCategory, BlockSpec } from "@/lib/pipeline-builder/types";
import {
  BLOCK_DISPLAY_NAMES_ZH,
  CATEGORY_COLORS,
  CATEGORY_LABELS,
  BLOCK_STATUS_COLORS,
  blockDisplayName,
} from "@/lib/pipeline-builder/style";
import { CategoryIcon } from "./CategoryIcon";
import BlockDocsDrawer from "./BlockDocsDrawer";

interface Props {
  onBlockDrag?: (block: BlockSpec) => void;
  readOnly?: boolean;
}

const CATEGORY_ORDER: BlockCategory[] = ["source", "transform", "logic", "output", "custom"];

export default function BlockLibrary({ readOnly }: Props) {
  const [blocks, setBlocks] = useState<BlockSpec[]>([]);
  const [openCats, setOpenCats] = useState<Record<string, boolean>>({
    source: true,
    transform: true,
    logic: true,
    output: true,
    custom: false,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [docsBlock, setDocsBlock] = useState<BlockSpec | null>(null);
  const [hoveredBlock, setHoveredBlock] = useState<string | null>(null);
  /** PR-D2: search input filters by name + display name + description. */
  const [query, setQuery] = useState("");

  useEffect(() => {
    listBlocks()
      .then((rows) => setBlocks(rows))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filteredBlocks = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return blocks;
    return blocks.filter((b) => {
      const zh = BLOCK_DISPLAY_NAMES_ZH[b.name] ?? "";
      return (
        b.name.toLowerCase().includes(q) ||
        blockDisplayName(b.name).toLowerCase().includes(q) ||
        zh.toLowerCase().includes(q) ||
        (b.description || "").toLowerCase().includes(q) ||
        b.category.toLowerCase().includes(q)
      );
    });
  }, [blocks, query]);

  const grouped = useMemo(() => {
    const map: Record<string, BlockSpec[]> = {};
    for (const cat of CATEGORY_ORDER) map[cat] = [];
    for (const b of filteredBlocks) {
      if (map[b.category]) map[b.category].push(b);
    }
    return map;
  }, [filteredBlocks]);

  const handleDragStart = (e: React.DragEvent, block: BlockSpec) => {
    if (readOnly) {
      e.preventDefault();
      return;
    }
    e.dataTransfer.setData("application/x-pb-block", JSON.stringify(block));
    e.dataTransfer.effectAllowed = "copy";
  };

  return (
    <div
      data-tour-id="pb-library"
      style={{
        width: 220,
        minWidth: 220,
        maxWidth: 220,
        background: "var(--pb-panel-bg)",
        borderRight: "1px solid var(--pb-panel-border)",
        color: "var(--pb-text)",
        overflowY: "auto",
        padding: "10px 8px",
        fontSize: 12,
      }}
    >
      <div
        style={{
          fontWeight: 600,
          fontSize: 11,
          color: "var(--pb-text-3)",
          letterSpacing: "0.05em",
          textTransform: "uppercase",
          padding: "4px 8px 8px",
        }}
      >
        Block Library
      </div>

      {/* PR-D2 search input */}
      <div style={{ padding: "0 4px 8px" }}>
        <input
          data-testid="block-library-search"
          type="text"
          placeholder="🔍 搜尋..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{
            width: "100%",
            padding: "5px 8px",
            fontSize: 11,
            background: "var(--pb-node-bg)",
            color: "var(--pb-text)",
            border: "1px solid var(--pb-node-border)",
            borderRadius: 4,
            outline: "none",
            boxSizing: "border-box",
          }}
        />
      </div>

      {loading && <div style={{ color: "#94A3B8", padding: 8 }}>Loading…</div>}
      {error && <div style={{ color: "#DC2626", padding: 8 }}>{error}</div>}

      {!loading &&
        CATEGORY_ORDER.map((cat) => {
          const items = grouped[cat] ?? [];
          const open = openCats[cat];
          if (items.length === 0 && cat !== "custom") return null;
          const catColor = CATEGORY_COLORS[cat];
          return (
            <div key={cat} style={{ marginBottom: 6 }}>
              <button
                onClick={() => setOpenCats((o) => ({ ...o, [cat]: !open }))}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "5px 8px",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  fontSize: 11,
                  color: "#64748B",
                  fontWeight: 600,
                  textAlign: "left",
                  letterSpacing: "0.03em",
                  textTransform: "uppercase",
                }}
              >
                <span style={{ fontSize: 9, color: "#94A3B8" }}>{open ? "▼" : "▶"}</span>
                <span style={{ color: catColor, display: "inline-flex" }}>
                  <CategoryIcon category={cat} size={12} />
                </span>
                <span>{CATEGORY_LABELS[cat]}</span>
                <span style={{ marginLeft: "auto", color: "#CBD5E1", fontWeight: 400 }}>
                  {items.length}
                </span>
              </button>
              {open && (
                <div style={{ marginTop: 2 }}>
                  {items.length === 0 && (
                    <div style={{ color: "#CBD5E1", padding: "4px 10px", fontSize: 11 }}>
                      （尚無積木）
                    </div>
                  )}
                  {items.map((b) => {
                    const statusStyle = BLOCK_STATUS_COLORS[b.status];
                    const zhName = BLOCK_DISPLAY_NAMES_ZH[b.name];
                    const disabled = readOnly;
                    return (
                      <div
                        key={`${b.name}@${b.version}`}
                        data-testid={`block-item-${b.name}`}
                        data-disabled={disabled ? "true" : "false"}
                        draggable={!disabled}
                        onDragStart={(e) => handleDragStart(e, b)}
                        title={zhName ? `${zhName}\n\n${b.description}` : b.description}
                        style={{
                          padding: "6px 8px",
                          margin: "2px 2px",
                          borderRadius: 4,
                          border: "1px solid transparent",
                          borderLeft: `3px solid ${catColor}`,
                          background: disabled ? "var(--pb-node-bg-2)" : "var(--pb-node-bg)",
                          cursor: disabled ? "not-allowed" : "grab",
                          opacity: disabled ? 0.5 : 1,
                          fontSize: 12,
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                        }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLDivElement).style.background = "var(--pb-node-bg-2)";
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLDivElement).style.background = disabled ? "var(--pb-node-bg-2)" : "var(--pb-node-bg)";
                        }}
                      >
                        <span style={{ color: catColor, display: "inline-flex", flexShrink: 0 }}>
                          <CategoryIcon category={cat} size={14} />
                        </span>
                        <span
                          style={{
                            flex: 1,
                            minWidth: 0,
                            color: "var(--pb-text)",
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                          }}
                        >
                          {blockDisplayName(b.name)}
                        </span>
                        {/* ℹ icon — opens BlockDocsDrawer */}
                        <button
                          data-testid={`block-info-${b.name}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            setDocsBlock(b);
                          }}
                          draggable={false}
                          onDragStart={(e) => e.stopPropagation()}
                          title="查看說明與範例"
                          style={{
                            background: "none",
                            border: "none",
                            padding: 0,
                            margin: 0,
                            width: 16,
                            height: 16,
                            display: "inline-flex",
                            alignItems: "center",
                            justifyContent: "center",
                            cursor: "pointer",
                            color: hoveredBlock === b.name ? "#4F46E5" : "#94A3B8",
                            fontSize: 11,
                            fontWeight: 700,
                            flexShrink: 0,
                          }}
                          onMouseEnter={() => setHoveredBlock(b.name)}
                          onMouseLeave={() => setHoveredBlock(null)}
                        >
                          ⓘ
                        </button>
                        {/* PR-F: only surface status pill when NOT the default 'production'
                            (which is ~100% of blocks) — otherwise noise. */}
                        {b.status !== "production" && (
                          <span
                            style={{
                              fontSize: 9,
                              color: statusStyle.fg,
                              background: statusStyle.bg,
                              padding: "1px 5px",
                              borderRadius: 2,
                              flexShrink: 0,
                            }}
                          >
                            {statusStyle.label}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

      <BlockDocsDrawer block={docsBlock} onClose={() => setDocsBlock(null)} />
    </div>
  );
}
