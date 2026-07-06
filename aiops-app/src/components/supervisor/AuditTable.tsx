"use client";

/**
 * 簽核紀錄 tab — one row per case, 4-stage lifecycle columns
 * (提案 → 簽核 → 落地 → 驗證). 落地 fills from landed_at/landed_by and
 * 驗證 from verify_result/verify_at (W2 write-back); old rows without
 * those columns render "—". Rejected rows carry reject_reason as a
 * hover title on the sign cell.
 */

import { useTranslations } from "next-intl";
import { TOK, Proposal, proposalTitle, fmtWhen } from "./model";

const GRID = "300px 150px 190px 190px 1fr";

export function AuditTable({ items }: { items: Proposal[] }) {
  const t = useTranslations("sup");

  return (
    <div style={{
      background: TOK.card, border: `1px solid ${TOK.border}`, borderRadius: 10,
      overflow: "hidden", maxWidth: 1200,
    }}>
      <div style={{
        display: "grid", gridTemplateColumns: GRID, background: "#f7f5ef",
        borderBottom: `1px solid ${TOK.border}`, padding: "8px 16px",
        font: `600 10.5px ${TOK.mono}`, color: TOK.faint, letterSpacing: ".06em",
      }}>
        <span>{t("audit.colCase")}</span>
        <span>{t("audit.colProposed")}</span>
        <span>{t("audit.colSign")}</span>
        <span>{t("audit.colLand")}</span>
        <span>{t("audit.colVerify")}</span>
      </div>

      {items.length === 0 && (
        <div style={{ padding: "36px 16px", textAlign: "center", color: TOK.faint, fontSize: 12.5 }}>
          {t("audit.empty")}
        </div>
      )}

      {items.map((p) => {
        const approved = p.status === "approved";
        const rejected = p.status === "rejected";
        const signFg = approved ? TOK.green : rejected ? TOK.red : TOK.muted;
        const sign = approved || rejected
          ? `${approved ? "✓" : "✕"} #${p.reviewed_by ?? "?"} ${fmtWhen(p.reviewed_at)}`
          : "—";
        // reject_reason surfaces on hover only (rejected rows, W2 column)
        const rejectTitle = rejected && (p.reject_reason ?? "").trim() !== ""
          ? t("audit.rejectReason", { reason: p.reject_reason as string })
          : undefined;
        // 落地 / 驗證 — W2 write-back columns; "—" when missing (old rows)
        const landed = p.landed_at != null && p.landed_at !== "";
        const land = landed
          ? `✓ ${p.landed_by != null ? `#${p.landed_by} ` : ""}${fmtWhen(p.landed_at)}`
          : "—";
        const verified = (p.verify_result ?? "") !== "" || (p.verify_at != null && p.verify_at !== "");
        const verify = verified
          ? `${p.verify_result ?? ""} ${fmtWhen(p.verify_at)}`.trim()
          : "—";
        return (
          <div key={p.id} title={rejectTitle} style={{
            display: "grid", gridTemplateColumns: GRID, padding: "10px 16px",
            borderBottom: `1px solid ${TOK.borderRow}`, alignItems: "start",
          }}>
            <div style={{ paddingRight: 14 }}>
              <span style={{ font: `600 11px ${TOK.mono}`, color: TOK.faint }}>#{p.id}</span>{" "}
              <span style={{ fontSize: 12, fontWeight: 600 }}>
                {p.action_type} · {proposalTitle(p)}
              </span>
            </div>
            <div style={{ fontSize: 11.5, color: TOK.secondary }}>{fmtWhen(p.created_at)}</div>
            <div style={{ fontSize: 11.5, color: signFg }} title={rejectTitle}>{sign}</div>
            <div style={{ fontSize: 11.5, color: landed ? TOK.green : TOK.fainter }}>{land}</div>
            <div style={{ fontSize: 11.5, color: verified ? TOK.secondary : TOK.fainter }}>{verify}</div>
          </div>
        );
      })}

      <div style={{ padding: "9px 16px", fontSize: 10.5, color: TOK.faint }}>
        {t("audit.lifecycle")}
      </div>
    </div>
  );
}
