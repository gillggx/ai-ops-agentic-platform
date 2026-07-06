"use client";

/**
 * Inbox master list (left column of the master-detail layout, design 1a).
 * Signable proposals first; proposals the current role cannot sign are
 * dimmed (opacity .48) but still selectable — detail pane shows a
 * read-only note instead of the action bar.
 */

import { useTranslations } from "next-intl";
import {
  TOK, Proposal, typeChip, statusChip, signerOf, canSign,
  proposalTitle, fmtWhen, metaSource, agentsOf,
} from "./model";

export function statusLabelKey(status: string): string {
  switch (status) {
    case "proposed": return "status.pending";
    case "approved": return "status.approved";
    case "rejected": return "status.rejected";
    default: return "status.expired";
  }
}

export function ProposalList({ items, roles, selectedId, onSelect }: {
  items: Proposal[];
  roles: string[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const t = useTranslations("sup");
  const mine = items.filter((p) => canSign(p, roles)).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 2px 4px" }}>
        <span style={{ fontSize: 11.5, color: TOK.muted }}>
          {t("inbox.countNote", { mine, others: items.length - mine })}
        </span>
      </div>
      {items.length === 0 && (
        <div style={{
          padding: "40px 16px", textAlign: "center", color: TOK.faint, fontSize: 12.5,
          background: TOK.card, border: `1px dashed ${TOK.btnBorder}`, borderRadius: 9,
        }}>
          {t("inbox.empty")}
        </div>
      )}
      {items.map((p) => {
        const tc = typeChip(p.action_type);
        const sc = statusChip(p.status);
        const signable = canSign(p, roles);
        return (
          <div
            key={p.id}
            onClick={() => onSelect(p.id)}
            style={{
              cursor: "pointer", background: TOK.card,
              border: `1.5px solid ${p.id === selectedId ? TOK.ink : TOK.border}`,
              borderRadius: 9, padding: "10px 12px",
              opacity: signable ? 1 : 0.48,
            }}
          >
            <div style={{ display: "flex", gap: 7, alignItems: "center", marginBottom: 4 }}>
              <span style={{
                font: `700 10.5px ${TOK.mono}`, color: tc.fg, background: tc.bg,
                border: `1px solid ${tc.bd}`, borderRadius: 4, padding: "1px 6px",
              }}>{p.action_type}</span>
              <span style={{ font: `600 11px ${TOK.mono}`, color: TOK.faint }}>#{p.id}</span>
              <span title={t(`source.${metaSource(p)}Tip`)} style={{
                font: `600 9px ${TOK.mono}`, color: "#0e7490", background: "#e9f5f8",
                border: "1px solid #bfe0e9", borderRadius: 4, padding: "0 5px",
              }}>{t(`source.${metaSource(p)}`)}</span>
              {metaSource(p) === "curation" && agentsOf(p).length > 0 && (
                <span style={{ font: `600 9px ${TOK.mono}`, color: "#6d28d9" }}>
                  {agentsOf(p).length > 1
                    ? t("source.agentByMulti", { agent: agentsOf(p)[0] })
                    : t("source.agentBy", { agent: agentsOf(p)[0] })}
                </span>
              )}
              <span style={{ flex: 1 }} />
              <span style={{
                font: `600 10.5px ${TOK.mono}`, color: sc.fg, background: sc.bg,
                border: `1px solid ${sc.bd}`, borderRadius: 999, padding: "1px 8px",
              }}>{t(statusLabelKey(p.status))}</span>
            </div>
            <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.45, marginBottom: 3 }}>
              {proposalTitle(p)}
            </div>
            <div style={{ font: `500 10px ${TOK.mono}`, color: TOK.fainter, marginTop: 4 }}>
              {fmtWhen(p.created_at)} · {t("inbox.signerLabel", { signer: signerOf(p) })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
