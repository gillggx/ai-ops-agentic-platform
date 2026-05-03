"use client";

/**
 * CommandPalette — cross-surface ⌘K palette.
 *
 * Queries every registered PaletteSource concurrently with the current
 * search string; groups results by `source.group`. Up/Down/Enter for
 * keyboard nav, Esc / outside-click to close.
 *
 * Empty query: show first N items from every source (recent / starred-style).
 * Typing: re-fetch each source with the query (sources own their own
 * matching logic — substring, fuzzy, server-side, whatever).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { PaletteItem, PaletteSource } from "./types";

const FETCH_DEBOUNCE_MS = 120;

interface Props {
  sources: PaletteSource[];
  onClose: () => void;
}

interface FetchState {
  loading: boolean;
  items: PaletteItem[];
  error: boolean;
}

export default function CommandPalette({ sources, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const [results, setResults] = useState<Map<string, FetchState>>(new Map());
  const [mounted, setMounted] = useState(false);
  const portalRef = useRef<HTMLDivElement | null>(null);
  const debounceRef = useRef<number | null>(null);

  // Mount portal
  useEffect(() => {
    setMounted(true);
    portalRef.current = document.createElement("div");
    portalRef.current.className = "tour-cmdk-portal";
    document.body.appendChild(portalRef.current);
    return () => {
      if (portalRef.current && portalRef.current.parentNode) {
        portalRef.current.parentNode.removeChild(portalRef.current);
      }
    };
  }, []);

  // Fetch sources on query change (debounced).
  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      // Mark all sources as loading initially
      setResults((prev) => {
        const next = new Map(prev);
        for (const s of sources) {
          next.set(s.sourceId, {
            loading: true,
            items: prev.get(s.sourceId)?.items ?? [],
            error: false,
          });
        }
        return next;
      });

      // Concurrent fetch — each source independent so a slow / failing one
      // doesn't block others.
      sources.forEach((s) => {
        s.fetch(query)
          .then((items) => {
            setResults((prev) => {
              const next = new Map(prev);
              next.set(s.sourceId, {
                loading: false,
                items: items.slice(0, s.limit ?? 8),
                error: false,
              });
              return next;
            });
          })
          .catch(() => {
            setResults((prev) => {
              const next = new Map(prev);
              next.set(s.sourceId, { loading: false, items: [], error: true });
              return next;
            });
          });
      });
    }, FETCH_DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [query, sources]);

  // Flatten + group results in source order. The activeIdx is over this
  // flat list so keyboard nav crosses group boundaries naturally.
  const flatItems = useMemo<PaletteItem[]>(() => {
    const out: PaletteItem[] = [];
    for (const s of sources) {
      const r = results.get(s.sourceId);
      if (!r || r.items.length === 0) continue;
      out.push(...r.items);
    }
    return out;
  }, [sources, results]);

  const groups = useMemo(() => {
    const out = new Map<string, PaletteItem[]>();
    for (const item of flatItems) {
      const arr = out.get(item.group);
      if (arr) arr.push(item);
      else out.set(item.group, [item]);
    }
    return out;
  }, [flatItems]);

  // Keyboard nav
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIdx((i) => Math.min(flatItems.length - 1, i + 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIdx((i) => Math.max(0, i - 1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const picked = flatItems[activeIdx];
        if (picked) {
          picked.onSelect();
          onClose();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [flatItems, activeIdx, onClose]);

  // Reset active index when query changes (so the first result is highlighted)
  useEffect(() => {
    setActiveIdx(0);
  }, [query]);

  const handleSelect = useCallback((item: PaletteItem) => {
    item.onSelect();
    onClose();
  }, [onClose]);

  if (!mounted || !portalRef.current) return null;

  const anyLoading = Array.from(results.values()).some((r) => r.loading);
  const allEmpty = flatItems.length === 0 && !anyLoading;

  // Compute display index per item for keyboard highlight
  let runningIdx = 0;

  return createPortal(
    <>
      <div className="tour-cmdk-overlay" onClick={onClose} />
      <div className="tour-cmdk-panel" role="dialog" aria-label="Command palette">
        <div className="tour-cmdk-h">
          <span className="ic">⌕</span>
          <input
            autoFocus
            placeholder="搜尋 pipeline / alarm / equipment / canvas node..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <span className="kbd">↑↓</span>
          <span className="kbd">↵</span>
          <span className="kbd">esc</span>
        </div>
        <ul className="tour-cmdk-list">
          {anyLoading && flatItems.length === 0 && (
            <li className="tour-cmdk-loading" style={{ cursor: "default" }}>載入中…</li>
          )}
          {allEmpty && (
            <li className="tour-cmdk-empty" style={{ cursor: "default" }}>無符合結果</li>
          )}
          {Array.from(groups.entries()).map(([group, items]) => (
            <div key={group}>
              <div className="tour-cmdk-group-h">{group}</div>
              {items.map((item) => {
                const idx = runningIdx;
                runningIdx += 1;
                return (
                  <li
                    key={`${group}-${item.id}`}
                    className={idx === activeIdx ? "active" : ""}
                    onClick={() => handleSelect(item)}
                    onMouseEnter={() => setActiveIdx(idx)}
                  >
                    <span className="ic">{item.icon ?? "•"}</span>
                    <span className="label">{item.label}</span>
                    {item.meta && <span className="meta">{item.meta}</span>}
                  </li>
                );
              })}
            </div>
          ))}
        </ul>
      </div>
    </>,
    portalRef.current,
  );
}
