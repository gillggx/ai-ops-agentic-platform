"use client";

/**
 * Detail pane (right side of the master-detail inbox, design 1a).
 *
 * Body = shared NarrativeCard: 案情四段 (發生了什麼 / 觀察到的問題 /
 * 影響對象 / 提議) when the W2 narrative field is present, else the
 * legacy 三段式 (提案 / 為什麼 / 依據) — all parsed defensively.
 * Approve = black button; reject requires a non-empty reason; 擱置 just
 * deselects. Geometric marks (✓ ● ○ ▣ △ ◆ ↗ ·) stay in JSX, not i18n.
 */

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  TOK, LIFE_STYLE, LifeState, Proposal,
  typeChip, statusChip, signerOf, canSign as canSignFn,
  proposalTitle, isSuperseded, supersededBy, fmtWhen, metaSource, agentsOf,
} from "./model";
import { NarrativeCard } from "./NarrativeCard";
import { statusLabelKey } from "./ProposalList";

/** Types with a typeDesc.* i18n entry — unknown types skip the desc line. */
const DESCRIBED_TYPES = new Set(["MERGE", "CORRECT", "PRUNE", "PROMOTE", "DOC_REVISE"]);

export interface EpisodeMetaLite {
  status?: string | null; started_at?: string | null;
  finished_at?: string | null; user_id?: number | null;
}
export function ProposalDetail({ p, roles, busy, onApprove, onReject, onShelve, onGoto, episodeMeta }: {
  p: Proposal | null;
  roles: string[];
  busy: boolean;
  onApprove: (id: number) => void;
  onReject: (id: number, reason: string) => void;
  onShelve: () => void;
  onGoto: (id: number) => void;
  episodeMeta?: Record<string, EpisodeMetaLite>;
}) {
  const t = useTranslations("sup");

  if (!p) {
    return (
      <div style={{
        background: TOK.card, border: `1px solid ${TOK.border}`, borderRadius: 10,
        padding: "60px 24px", textAlign: "center", color: TOK.faint, fontSize: 13,
      }}>
        {t("detail.none")}
      </div>
    );
  }
  return <DetailInner key={p.id} p={p} roles={roles} busy={busy}
    onApprove={onApprove} onReject={onReject} onShelve={onShelve} onGoto={onGoto}
    episodeMeta={episodeMeta ?? {}} />;
}

function DetailInner({ p, roles, busy, onApprove, onReject, onShelve, onGoto, episodeMeta }: {
  p: Proposal; roles: string[]; busy: boolean;
  onApprove: (id: number) => void;
  onReject: (id: number, reason: string) => void;
  onShelve: () => void;
  onGoto: (id: number) => void;
  episodeMeta: Record<string, EpisodeMetaLite>;
}) {
  const t = useTranslations("sup");
  const [reason, setReason] = useState("");
  const [ghCopied, setGhCopied] = useState(false);
  const [reasonErr, setReasonErr] = useState(false);

  const tc = typeChip(p.action_type);
  const sc = statusChip(p.status);
  const signer = signerOf(p);
  const superseded = isSuperseded(p);
  const supersederId = supersededBy(p);
  const signable = canSignFn(p, roles) && p.status === "proposed" && !superseded;

  // W2 lifecycle write-back — landed_at/landed_by + verify_result/verify_at
  // may be missing on old rows → those stages fall back to todo / "—".
  const landed = p.landed_at != null && p.landed_at !== "";
  const verified = (p.verify_result ?? "") !== "" || (p.verify_at != null && p.verify_at !== "");
  const lifeStages: { labelKey: string; st: LifeState; note: string }[] = [
    { labelKey: "life.propose", st: "done", note: fmtWhen(p.created_at) },
    p.status === "proposed"
      ? { labelKey: "life.sign", st: "current", note: t("life.waitSigner", { signer }) }
      : { labelKey: "life.sign", st: "done", note: `#${p.reviewed_by ?? "?"} ${fmtWhen(p.reviewed_at)}` },
    landed
      ? { labelKey: "life.land", st: "done", note: `${p.landed_by != null ? `#${p.landed_by} ` : ""}${fmtWhen(p.landed_at)}` }
      : { labelKey: "life.land", st: p.status === "approved" ? "current" : "todo", note: "—" },
    verified
      ? { labelKey: "life.verify", st: "done", note: `${p.verify_result ?? ""} ${fmtWhen(p.verify_at)}`.trim() }
      : { labelKey: "life.verify", st: "todo", note: "—" },
  ];

  const submitReject = () => {
    if (reason.trim() === "") { setReasonErr(true); return; }
    setReasonErr(false);
    onReject(p.id, reason.trim());
  };

  let noActionNote: string | null = null;
  if (superseded) noActionNote = t("detail.expiredNote");
  else if (p.status !== "proposed") {
    noActionNote = t("detail.reviewedNote", {
      status: t(statusLabelKey(p.status)),
      reviewer: p.reviewed_by ?? "?",
      time: fmtWhen(p.reviewed_at),
    });
  } else if (!canSignFn(p, roles)) {
    noActionNote = t("detail.readOnly", { signer, role: roles.join(" / ") || "—" });
  }

  return (
    <div style={{ background: TOK.card, border: `1px solid ${TOK.border}`, borderRadius: 10, minWidth: 0 }}>
      {/* header */}
      <div style={{ padding: "14px 18px", borderBottom: `1px solid ${TOK.borderSub}` }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
          <span style={{
            font: `700 11px ${TOK.mono}`, color: tc.fg, background: tc.bg,
            border: `1px solid ${tc.bd}`, borderRadius: 4, padding: "2px 7px",
          }}>{p.action_type}</span>
          <span style={{ font: `600 12px ${TOK.mono}`, color: TOK.faint }}>#{p.id}</span>
          <span title={t(`source.${metaSource(p)}Tip`)} style={{
            font: `600 9.5px ${TOK.mono}`, color: "#0e7490", background: "#e9f5f8",
            border: "1px solid #bfe0e9", borderRadius: 4, padding: "1px 6px",
          }}>{t(`source.${metaSource(p)}`)}</span>
          {metaSource(p) === "curation" && agentsOf(p).length > 0 && (
            <span style={{ font: `600 9.5px ${TOK.mono}`, color: "#6d28d9" }}>
              {agentsOf(p).length > 1
                ? t("source.agentByMulti", { agent: agentsOf(p)[0] })
                : t("source.agentBy", { agent: agentsOf(p)[0] })}
            </span>
          )}
          <span style={{
            font: `600 10.5px ${TOK.mono}`, color: sc.fg, background: sc.bg,
            border: `1px solid ${sc.bd}`, borderRadius: 999, padding: "1px 8px",
          }}>{t(statusLabelKey(superseded ? "expired" : p.status))}</span>
          <span style={{ flex: 1 }} />
          <span style={{ font: `500 11px ${TOK.mono}`, color: TOK.muted }}>
            {fmtWhen(p.created_at)} · {t("inbox.signerLabel", { signer })}
          </span>
        </div>
        <div style={{ fontSize: 15, fontWeight: 700, lineHeight: 1.4 }}>{proposalTitle(p)}</div>
        {DESCRIBED_TYPES.has(p.action_type) && (
          <div style={{ fontSize: 11, color: TOK.faint, marginTop: 3 }}>
            {t(`typeDesc.${p.action_type}` as Parameters<typeof t>[0])}
          </div>
        )}
      </div>

      {/* 案情四段 body (narrative) — falls back to 三段式 on old rows */}
      <div style={{ padding: "14px 18px" }}>
        <NarrativeCard p={p} />
        {/* activity ids（來源 build 紀錄，可調閱；也用於重跑防重複） */}
        {(() => {
          const meta = ((): Record<string, unknown> => {
            const m = p.proposer_meta as unknown;
            if (m && typeof m === "object") return m as Record<string, unknown>;
            try { return JSON.parse(String(m ?? "{}")); } catch { return {}; }
          })();
          const ids = Array.isArray(meta.activity_ids) ? (meta.activity_ids as unknown[]).map(String) : [];
          if (ids.length === 0) return null;
          return (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5, alignItems: "center", marginTop: 10 }}>
              <span style={{ fontSize: 10.5, color: TOK.muted }}>{t("detail.activityIds")}</span>
              {ids.slice(0, 8).map((id) => (
                <span key={id}
                  onClick={() => {
                    // session_id（uuid 形）→ 新版 agent activity 自動展開；
                    // legacy trace 檔名 → build-traces 頁。
                    const isEpisode = /^[0-9a-f-]{32,36}$/.test(id);
                    window.open(isEpisode
                      ? `/agent-activity?episode=${encodeURIComponent(id)}`
                      : `/admin/build-traces?trace=${encodeURIComponent(id)}`, "_blank");
                  }}
                  title={(() => {
                    const em = episodeMeta[id];
                    if (!em) return id;
                    const dur = em.started_at && em.finished_at
                      ? `${Math.max(1, Math.round((Date.parse(em.finished_at) - Date.parse(em.started_at)) / 1000))}s`
                      : em.finished_at ? "" : "進行中";
                    const who = em.user_id != null ? `#${em.user_id}` : "—";
                    const when = em.started_at ? new Date(em.started_at).toLocaleString() : "—";
                    const done = /fail|handover/i.test(String(em.status)) ? "失敗"
                      : /finish|success|done/i.test(String(em.status)) ? "成功" : String(em.status ?? "—");
                    return `${who} · ${when} · ${dur} · ${done}`;
                  })()}
                  style={{ cursor: "pointer", font: `600 10px ${TOK.mono}`, color: "#475569",
                           border: "1px solid #d7dee7", borderRadius: 4, padding: "1px 6px",
                           maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  ▣ {id}
                </span>
              ))}
              {ids.length > 8 && <span style={{ fontSize: 10, color: TOK.faint }}>+{ids.length - 8}</span>}
            </div>
          );
        })()}
      </div>

      {/* lifecycle strip (提案 → 簽核 → 落地 → 驗證) */}
      <div style={{
        display: "flex", margin: "0 18px 14px", background: TOK.lifeBg,
        border: `1px solid ${TOK.lifeBd}`, borderRadius: 8, padding: "10px 16px",
        alignItems: "center",
      }}>
        {lifeStages.map((st, i) => {
          const ls = LIFE_STYLE[st.st];
          return (
            <div key={st.labelKey} style={{ display: "flex", alignItems: "center" }}>
              <div style={{ textAlign: "center", minWidth: 110 }}>
                <div style={{ font: `700 11.5px ${TOK.mono}`, color: ls.fg }}>
                  {ls.mark} {t(st.labelKey as Parameters<typeof t>[0])}
                </div>
                <div style={{ fontSize: 10, color: TOK.muted, marginTop: 2 }}>{st.note}</div>
              </div>
              {i < lifeStages.length - 1 && (
                <div style={{
                  width: 36,
                  borderTop: `1.5px ${st.st === "done" ? "solid" : "dashed"} ${TOK.lifeConn}`,
                }} />
              )}
            </div>
          );
        })}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10.5, color: TOK.muted, maxWidth: 220, lineHeight: 1.5 }}>
          {t("detail.lifecycleNote")}
        </span>
      </div>

      {/* supersede banner (dashed, design lines ~225-229) */}
      {superseded && (
        <div style={{
          display: "flex", margin: "0 18px 14px", background: "#f4f2ec",
          border: `1px dashed #ccc5b5`, borderRadius: 8, padding: "9px 14px",
          fontSize: 12, color: "#6f6a61", gap: 6, alignItems: "center", flexWrap: "wrap",
        }}>
          {supersederId != null ? (
            <>
              <span>{t("detail.supersedePre")}</span>
              <span
                onClick={() => onGoto(supersederId)}
                style={{
                  cursor: "pointer", color: TOK.blue, font: `600 11.5px ${TOK.mono}`,
                  borderBottom: "1px solid #bcd0f5",
                }}
              >#{supersederId}</span>
              <span>{t("detail.supersedePost")}</span>
            </>
          ) : (
            <span>{t("detail.supersedeNoRef")}</span>
          )}
        </div>
      )}

      {/* W3 — ISSUE 型核准後：人建 issue，給 gh 指令複製鈕（不自動建，
          遵守「Supervisor 不落地」；landed 由人回填） */}
      {p.action_type === "ISSUE" && p.status === "approved" && !p.landed_at && (
        <div style={{
          margin: "0 18px 14px", background: "#f1f5f9", border: "1px solid #d7dee7",
          borderRadius: 8, padding: "10px 14px", display: "flex", gap: 10,
          alignItems: "center", flexWrap: "wrap",
        }}>
          <span style={{ fontSize: 12, color: TOK.muted, flex: 1, minWidth: 200 }}>
            {t("issue.manualNote")}
          </span>
          <button
            onClick={() => {
              const raw = ((): Record<string, unknown> => {
                const pr = p.proposal as unknown;
                if (pr && typeof pr === "object") return pr as Record<string, unknown>;
                try { return JSON.parse(String(pr ?? "{}")); } catch { return {}; }
              })();
              const title = String(raw.summary ?? p.rationale ?? `supervisor issue #${p.id}`).slice(0, 120);
              const refs = Array.isArray(raw.trace_refs) ? (raw.trace_refs as unknown[]).join("\n") : "";
              const cmd = `gh issue create --title ${JSON.stringify(title)} --body ${JSON.stringify(
                `${String(raw.suspect ?? p.rationale ?? "")}\n\ntraces:\n${refs}\n\nsupervisor proposal #${p.id}`)}`;
              void navigator.clipboard?.writeText(cmd).catch(() => {});
              setGhCopied(true);
            }}
            style={{
              border: `1px solid ${TOK.btnBorder}`, background: ghCopied ? "#eaf5ee" : "#fff",
              color: ghCopied ? "#1a7f4e" : TOK.muted, borderRadius: 6,
              fontSize: 11.5, fontWeight: 600, padding: "5px 12px", cursor: "pointer",
              fontFamily: "inherit",
            }}
          >{ghCopied ? t("issue.copied") : t("issue.copyGh")}</button>
        </div>
      )}

      {/* action bar / read-only note */}
      {signable ? (
        <div style={{
          display: "flex", gap: 8, alignItems: "center", padding: "12px 18px",
          borderTop: `1px solid ${TOK.borderSub}`, background: TOK.cardFoot,
          borderRadius: "0 0 10px 10px", flexWrap: "wrap",
        }}>
          <button
            disabled={busy}
            onClick={() => onApprove(p.id)}
            style={{
              background: TOK.ink, color: TOK.paper, border: "none", borderRadius: 7,
              padding: "8px 20px", fontSize: 12.5, fontWeight: 700,
              cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
            }}
          >{busy ? t("actions.working") : t("actions.approve")}</button>
          <input
            value={reason}
            onChange={(e) => { setReason(e.target.value); if (reasonErr) setReasonErr(false); }}
            placeholder={t("actions.rejectPlaceholder")}
            style={{
              border: `1px solid ${reasonErr ? TOK.redBtnBd : TOK.btnBorder}`,
              borderRadius: 7, padding: "7px 12px", fontSize: 12, width: 220,
              background: "#fff", color: TOK.ink, fontFamily: "inherit",
            }}
          />
          <button
            disabled={busy}
            onClick={submitReject}
            style={{
              background: "#fff", color: TOK.red, border: `1px solid ${TOK.redBtnBd}`,
              borderRadius: 7, padding: "8px 16px", fontSize: 12.5, fontWeight: 600,
              cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
            }}
          >{t("actions.reject")}</button>
          <button
            onClick={onShelve}
            style={{
              background: "none", color: TOK.muted, border: "none",
              fontSize: 12.5, cursor: "pointer", padding: "8px 10px",
            }}
          >{t("actions.shelve")}</button>
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 11, color: TOK.faint }}>
            {reasonErr ? (
              <span style={{ color: TOK.red }}>{t("actions.rejectReasonRequired")}</span>
            ) : t("actions.commitNote")}
          </span>
        </div>
      ) : (
        <div style={{
          padding: "12px 18px", borderTop: `1px solid ${TOK.borderSub}`,
          background: TOK.cardFoot, borderRadius: "0 0 10px 10px",
          fontSize: 12, color: TOK.muted,
        }}>{noActionNote}</div>
      )}
    </div>
  );
}
