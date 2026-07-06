"use client";

/**
 * DOC_REVISE readable preview (W2 supervisor inbox).
 *
 * A DOC_REVISE proposal carries {block_id, revised_doc_draft, trace_refs,
 * display_title?}. `revised_doc_draft` is the LLM's PROPOSED passage — an
 * addition / revision, NOT a full rewrite. So we do NOT char-diff; we stack
 * two panels:
 *   目前文件          — the current block doc (read-only, fetched on expand)
 *   建議修訂 / 新增段落 — the proposed draft (green ◆ box)
 *
 * Fail-open: if the current doc can't be loaded we still show the proposed
 * draft. Collapsed by default so the inbox card stays compact.
 *
 * The ◆ marker lives in JSX, never in an i18n string (GLOSSARY rule).
 */

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { TOK, Proposal } from "./model";

/** Defensive proposal parse — string-or-object with JSON.parse fallback,
 *  mirroring the pattern the rest of the supervisor components use. */
function parseProposal(p: Proposal): Record<string, unknown> {
  const raw = p.proposal as unknown;
  if (raw && typeof raw === "object") return raw as Record<string, unknown>;
  try {
    return JSON.parse(String(raw ?? "{}")) as Record<string, unknown>;
  } catch {
    return {};
  }
}

const asStr = (v: unknown): string =>
  typeof v === "string" ? v : v == null ? "" : String(v);

export function DocRevisePreview({ p }: { p: Proposal }) {
  const t = useTranslations("sup");
  const b = parseProposal(p);
  const blockId = asStr(b.block_id).trim();
  const draft = asStr(b.revised_doc_draft).trim();

  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState<string>("");
  const [docError, setDocError] = useState(false);
  const [loading, setLoading] = useState(false);
  const [fetched, setFetched] = useState(false);

  // Lazy fetch the current doc only once, on first expand.
  useEffect(() => {
    if (!open || fetched || !blockId) return;
    let alive = true;
    setLoading(true);
    (async () => {
      try {
        const res = await fetch(
          `/api/block-docs/${encodeURIComponent(blockId)}/1.0.0`,
          { cache: "no-store" },
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = await res.json().catch(() => ({}));
        const doc = (body?.data ?? body) as Record<string, unknown>;
        // block-docs proxy returns { markdown, auto_generated } (see
        // /api/block-docs route). Accept content/description as fallbacks.
        const md =
          typeof doc?.markdown === "string" ? doc.markdown
          : typeof doc?.content === "string" ? doc.content
          : typeof doc?.description === "string" ? doc.description
          : "";
        if (alive) setCurrent(md);
      } catch {
        if (alive) setDocError(true); // fail-open — proposed draft still shows
      } finally {
        if (alive) { setLoading(false); setFetched(true); }
      }
    })();
    return () => { alive = false; };
  }, [open, fetched, blockId]);

  const boxBase: React.CSSProperties = {
    maxHeight: 280, overflow: "auto", borderRadius: 7, padding: "10px 12px",
    font: `12px ${TOK.mono}`, lineHeight: 1.55, whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  };
  const labelBase: React.CSSProperties = {
    font: `700 10.5px ${TOK.mono}`, marginBottom: 4,
  };

  return (
    <div style={{ marginTop: 10 }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          cursor: "pointer", border: `1px solid ${TOK.btnBorder}`,
          background: TOK.cardFoot, color: TOK.secondary, borderRadius: 6,
          padding: "3px 10px", font: `600 11px ${TOK.mono}`,
        }}
      >
        {open ? t("docrev.toggleHide") : t("docrev.toggleShow")}
      </button>

      {open && (
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 10 }}>
          {/* top: current doc (read-only, muted) */}
          <div>
            <div style={{ ...labelBase, color: TOK.muted }}>
              {t("docrev.currentDoc")}{blockId ? ` · ${blockId}` : ""}
            </div>
            {loading ? (
              <div style={{ ...boxBase, background: "#f4f2ec", color: TOK.faint }}>
                {t("docrev.loading")}
              </div>
            ) : docError || !blockId ? (
              <div style={{ ...boxBase, background: "#f4f2ec", color: TOK.faint }}>
                {t("docrev.docUnavailable")}
              </div>
            ) : (
              <div style={{ ...boxBase, background: "#f4f2ec", color: TOK.body, border: `1px solid ${TOK.border}` }}>
                {current.trim() ? current : t("docrev.docEmpty")}
              </div>
            )}
          </div>

          {/* bottom: proposed revision (green ◆) */}
          <div>
            <div style={{ ...labelBase, color: TOK.green }}>
              ◆ {t("docrev.proposed")}
            </div>
            <div style={{ ...boxBase, background: TOK.greenBg, border: `1px solid ${TOK.greenBd}`, color: TOK.body }}>
              {draft || t("docrev.draftEmpty")}
            </div>
            <div style={{ fontSize: 10.5, color: TOK.faint, marginTop: 5 }}>
              {t("docrev.note")}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
