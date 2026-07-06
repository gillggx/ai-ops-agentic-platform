"use client";

/**
 * 案情四段 shared proposal body (W2) — used by BOTH the Supervisor
 * workbench detail pane and the knowledge workshop inbox cards.
 *
 * When the proposal carries a narrative (new W2 DTO field), render FOUR
 * sections:
 *   發生了什麼  — narrative.happened + evidence chips (▣/△/◆) merged here
 *   觀察到的問題 — narrative.observed
 *   影響對象   — narrative.subject as a clickable chip:
 *                 kind=block               → /admin/block-docs?block={id}
 *                 kind=knowledge|preference → /agent-knowledge?id={id}
 *                 anything else (cfg, …)    → plain label, not clickable
 *   提議       — narrative.action + the type-specific bullets + target chips
 *
 * Fallback (narrative null / old rows): the pre-W2 三段式 layout
 * 提案 (what) / 為什麼 (why) / 依據 (evidence) — identical to the previous
 * ProposalDetail body, so nothing regresses while Java catches up.
 *
 * Geometric marks (▣ △ ◆ ·) stay in JSX, never in i18n strings.
 */

import { useTranslations } from "next-intl";
import {
  TOK, EV_STYLE, Proposal, NarrativeSubject,
  narrativeOf, proposalWhy, whatLines, targetChips, evidenceRows,
} from "./model";

function subjectHref(s: NarrativeSubject): string | null {
  const kind = String(s.kind ?? "").toLowerCase();
  const id = s.id == null ? "" : String(s.id);
  if (id === "") return null;
  if (kind === "block") return `/admin/block-docs?block=${encodeURIComponent(id)}`;
  if (kind === "knowledge" || kind === "preference") {
    return `/agent-knowledge?id=${encodeURIComponent(id)}`;
  }
  return null; // cfg / unknown kinds — plain label
}

export function NarrativeCard({ p, compact = false }: { p: Proposal; compact?: boolean }) {
  const t = useTranslations("sup");
  const narr = narrativeOf(p);

  const labelCell: React.CSSProperties = {
    font: `700 ${compact ? 10 : 10.5}px ${TOK.mono}`, color: TOK.muted, paddingTop: 2,
  };
  const bodyText: React.CSSProperties = {
    fontSize: compact ? 11.5 : 13, lineHeight: compact ? 1.6 : 1.7, color: TOK.body,
  };
  const gridStyle: React.CSSProperties = {
    display: "grid", gridTemplateColumns: `${compact ? 56 : 64}px 1fr`,
    rowGap: compact ? 8 : 14, columnGap: compact ? 10 : 14,
  };

  const evidence = (
    <div style={{ display: "flex", flexDirection: "column", gap: compact ? 4 : 6 }}>
      {evidenceRows(p).map((ev, i) => {
        const st = EV_STYLE[ev.kind];
        return (
          <div key={i} style={{
            display: "flex", gap: compact ? 7 : 10, alignItems: "flex-start",
            border: `1px ${st.line} ${st.bd}`, background: st.bg,
            borderRadius: compact ? 5 : 7, padding: compact ? "4px 8px" : "7px 11px",
          }}>
            <span style={{ font: `700 ${compact ? 10.5 : 12}px ${TOK.mono}`, color: st.fg, width: compact ? 13 : 16 }}>
              {st.sig}
            </span>
            {ev.label != null || ev.labelKey ? (
              <span style={{
                font: `600 ${compact ? 10 : 11.5}px ${TOK.mono}`, color: TOK.secondary,
                minWidth: compact ? 0 : 110,
              }}>
                {ev.label ?? (ev.labelKey ? t(ev.labelKey as Parameters<typeof t>[0]) : "—")}
              </span>
            ) : null}
            <span style={{
              fontSize: compact ? 10.5 : 12, color: TOK.body, lineHeight: 1.55, flex: 1,
              wordBreak: "break-word",
            }}>{ev.detail}</span>
          </div>
        );
      })}
      {!compact && (
        <div style={{ fontSize: 10.5, color: TOK.faint, marginTop: 2 }}>
          ▣ {t("detail.legendSys")} · △ {t("detail.legendSelf")} · ◆ {t("detail.legendMem")}
        </div>
      )}
    </div>
  );

  const bullets = (
    <>
      {whatLines(p).map((ln, i) => (
        <div key={i} style={{ display: "flex", gap: compact ? 6 : 8 }}>
          <span style={{ color: TOK.fainter }}>·</span>
          <span style={"text" in ln
            ? { fontFamily: TOK.mono, fontSize: compact ? 10.5 : 12, wordBreak: "break-all" } : undefined}>
            {"text" in ln
              ? ln.text
              : t(ln.key as Parameters<typeof t>[0], ln.params)}
          </span>
        </div>
      ))}
    </>
  );

  const targets = targetChips(p);
  const targetRow = targets.length > 0 && (
    <div style={{ display: "flex", marginTop: compact ? 5 : 9, flexWrap: "wrap", gap: 5, alignItems: "center" }}>
      <span style={{ fontSize: compact ? 10 : 11, color: TOK.muted, marginRight: 2 }}>target_ids</span>
      {targets.map((tg) => (
        <span
          key={tg.id}
          title={tg.short ?? undefined}
          onClick={() => {
            if (tg.numeric) window.open(`/agent-knowledge?id=${tg.id}`, "_blank");
          }}
          style={{
            cursor: tg.numeric ? "pointer" : "default",
            font: `600 ${compact ? 10 : 10.5}px ${TOK.mono}`, color: TOK.purple,
            background: TOK.purpleBg, border: `1px solid ${TOK.purpleBd}`,
            borderRadius: 4, padding: compact ? "1px 6px" : "2px 7px",
          }}
        >◆ #{tg.id}{tg.short ? ` ${tg.short}` : ""}</span>
      ))}
      {!compact && <span style={{ fontSize: 10.5, color: TOK.faint }}>{t("detail.targetHint")}</span>}
    </div>
  );

  if (narr) {
    const subj = narr.subject && typeof narr.subject === "object" ? narr.subject : null;
    const href = subj ? subjectHref(subj) : null;
    const subjText = subj
      ? [subj.kind, subj.id].filter((v) => v != null && String(v) !== "").join(":")
      : "";
    return (
      <div style={gridStyle}>
        <div style={labelCell}>{t("narr.happened")}</div>
        <div>
          <div style={bodyText}>{narr.happened?.trim() || "—"}</div>
          <div style={{ marginTop: compact ? 5 : 8 }}>{evidence}</div>
        </div>

        <div style={labelCell}>{t("narr.observed")}</div>
        <div style={bodyText}>{narr.observed?.trim() || "—"}</div>

        <div style={labelCell}>{t("narr.subject")}</div>
        <div>
          {subj && (subjText !== "" || (subj.label ?? "") !== "") ? (
            <span
              onClick={href ? () => window.open(href, "_blank") : undefined}
              title={href ?? undefined}
              style={{
                display: "inline-flex", gap: 6, alignItems: "center",
                cursor: href ? "pointer" : "default",
                font: `600 ${compact ? 10 : 10.5}px ${TOK.mono}`, color: TOK.cyan,
                background: TOK.cyanBg, border: `1px solid ${TOK.cyanBd}`,
                borderRadius: 4, padding: compact ? "1px 7px" : "2px 8px",
                textDecoration: href ? "underline dotted" : "none",
              }}
            >
              {subjText || "—"}
              {subj.label ? (
                <span style={{ fontFamily: TOK.font, fontWeight: 500 }}>{subj.label}</span>
              ) : null}
            </span>
          ) : (
            <span style={{ ...bodyText, color: TOK.fainter }}>—</span>
          )}
        </div>

        <div style={labelCell}>{t("narr.action")}</div>
        <div style={{ ...bodyText, color: TOK.ink }}>
          {narr.action?.trim() ? <div style={{ marginBottom: compact ? 3 : 5 }}>{narr.action}</div> : null}
          {bullets}
          {targetRow}
        </div>
      </div>
    );
  }

  // ── fallback: legacy 三段式 (提案 / 為什麼 / 依據) ─────────────────────
  const why = proposalWhy(p);
  return (
    <div style={gridStyle}>
      <div style={labelCell}>{t("detail.what")}</div>
      <div style={{ ...bodyText, color: TOK.ink }}>
        {bullets}
        {targetRow}
      </div>

      <div style={labelCell}>{t("detail.why")}</div>
      <div style={bodyText}>{why ?? "—"}</div>

      <div style={labelCell}>{t("detail.evidence")}</div>
      {evidence}
    </div>
  );
}
