"use client";

/**
 * Supervisor 工作台 — master-detail inbox redesign (design doc
 * docs-design/supervisor-design.dc.html, section 1a).
 *
 * Three tabs:
 *   收件匣  — pending proposals, master list left / 三段式 detail right
 *   定期報告 — empty state until the W2 report generator ships
 *   簽核紀錄 — reviewed proposals as a 4-stage lifecycle audit table
 *
 * Role comes from the NextAuth session (roles: IT_ADMIN / PE / ON_DUTY);
 * the design's demo role switcher is intentionally NOT reproduced.
 * Signer mapping: PRUNE / PROMOTE / MERGE / CORRECT / DOC_REVISE → PE,
 * anything else → IT_ADMIN. Non-signers see proposals dimmed + read-only.
 *
 * Hard rule (V63): the Supervisor only proposes — nothing mutates until a
 * human approves here; dangerous actions run only from this authed UI.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSession } from "next-auth/react";
import { useTranslations } from "next-intl";
import { TOK, Proposal, api, canSign } from "@/components/supervisor/model";
import { HealthStrip } from "@/components/supervisor/HealthStrip";
import { RunTrigger } from "@/components/supervisor/RunTrigger";
import { RunProgressOverlay } from "@/components/supervisor/RunProgressOverlay";
import { ProposalList } from "@/components/supervisor/ProposalList";
import { ProposalDetail } from "@/components/supervisor/ProposalDetail";
import { AuditTable } from "@/components/supervisor/AuditTable";

type Tab = "inbox" | "digest" | "audit";

export default function SupervisorPage() {
  const t = useTranslations("sup");
  const session = useSession();
  // Same session shape AppShell trusts — roles ride on the session object.
  const roles: string[] = useMemo(
    () => (session?.data as unknown as { roles?: string[] })?.roles ?? [],
    [session?.data],
  );

  const [tab, setTab] = useState<Tab>("inbox");
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selId, setSelId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [healthTick, setHealthTick] = useState(0);
  const [startSignal, setStartSignal] = useState(0);
  // case-meta（誰/何時/多久/結果）— episode 摘要 join，給提案的來源紀錄 chip hover
  const [episodeMeta, setEpisodeMeta] = useState<Record<string, {
    status?: string | null; started_at?: string | null;
    finished_at?: string | null; user_id?: number | null;
  }>>({});
  useEffect(() => {
    void (async () => {
      try {
        const rows = await api<Array<Record<string, unknown>>>("/api/agent-activity/episodes?limit=100");
        const m: Record<string, { status?: string | null; started_at?: string | null; finished_at?: string | null; user_id?: number | null }> = {};
        for (const r of rows) {
          const k = String(r.episode_key ?? "");
          if (k) m[k] = { status: r.status as string, started_at: r.started_at as string, finished_at: r.finished_at as string, user_id: r.user_id as number };
        }
        setEpisodeMeta(m);
      } catch { /* fail-open：chip 仍可點，只是沒 hover 摘要 */ }
    })();
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // no status filter → Java returns the latest 200 across all statuses
      setProposals(await api<Proposal[]>("/api/supervisor/proposals"));
    } catch (e) {
      setError(t("loadError", { msg: String((e as Error).message || e) }));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  const inboxItems = useMemo(() => {
    const pending = proposals.filter((p) => p.status === "proposed");
    // signable-by-me first, then newest first (design sort)
    return [...pending].sort((a, b) => {
      const av = canSign(a, roles) ? 0 : 1;
      const bv = canSign(b, roles) ? 0 : 1;
      return av - bv || b.id - a.id;
    });
  }, [proposals, roles]);

  const auditItems = useMemo(
    () => proposals.filter((p) => p.status !== "proposed"),
    [proposals],
  );

  // auto-select the first signable proposal once data + roles are in
  useEffect(() => {
    if (selId != null && inboxItems.some((p) => p.id === selId)) return;
    setSelId(inboxItems.length > 0 ? inboxItems[0].id : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inboxItems]);

  const selected = inboxItems.find((p) => p.id === selId) ?? null;
  const myPending = inboxItems.filter((p) => canSign(p, roles)).length;

  const act = useCallback(async (path: string, init?: RequestInit) => {
    setBusy(true);
    setError(null);
    try {
      await api(path, { method: "POST", ...init });
      await load();
      setHealthTick((n) => n + 1);   // pending count on the strip changed
    } catch (e) {
      setError(t("actions.actionError", { msg: String((e as Error).message || e) }));
    } finally {
      setBusy(false);
    }
  }, [load, t]);

  const approve = useCallback(
    (id: number) => act(`/api/supervisor/proposals/${id}/approve`),
    [act],
  );
  const reject = useCallback(
    (id: number, reason: string) =>
      act(`/api/supervisor/proposals/${id}/reject`, {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      }),
    [act],
  );

  const tabs: { key: Tab; label: string; badge?: number }[] = [
    { key: "inbox", label: t("tabs.inbox"), badge: myPending || undefined },
    { key: "digest", label: t("tabs.digest") },
    { key: "audit", label: t("tabs.audit") },
  ];

  return (
    <div style={{
      minHeight: "100vh", background: TOK.paper, color: TOK.ink,
      fontFamily: TOK.font, padding: "18px 24px 24px",
    }}>
      <div style={{ maxWidth: 1600, margin: "0 auto" }}>
        {/* page header */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
          <span style={{ fontSize: 16, fontWeight: 700 }}>{t("title")}</span>
          <span style={{ fontSize: 11.5, color: TOK.muted }}>{t("subtitle")}</span>
          <span style={{ flex: 1 }} />
          {roles.includes("IT_ADMIN") && (
            <RunTrigger onStarted={() => setStartSignal((n) => n + 1)} />
          )}
        </div>

        <HealthStrip refreshKey={healthTick} />
        {roles.includes("IT_ADMIN") && (
          <RunProgressOverlay startSignal={startSignal}
            onDone={() => { void load(); setHealthTick((n) => n + 1); }} />
        )}

        {/* tabs */}
        <div style={{
          display: "flex", gap: 2, borderBottom: `1px solid ${TOK.border}`,
          marginBottom: 14, alignItems: "center",
        }}>
          {tabs.map((tb) => (
            <button
              key={tb.key}
              onClick={() => setTab(tb.key)}
              style={{
                display: "flex", gap: 7, alignItems: "center", padding: "9px 16px",
                border: "none", background: "none", cursor: "pointer", fontSize: 13,
                color: tab === tb.key ? TOK.ink : TOK.muted,
                fontWeight: tab === tb.key ? 700 : 500,
                borderBottom: `2px solid ${tab === tb.key ? TOK.ink : "transparent"}`,
                marginBottom: -1, fontFamily: "inherit",
              }}
            >
              <span>{tb.label}</span>
              {tb.badge != null && (
                <span style={{
                  background: "#f4e8cf", color: TOK.amber, borderRadius: 999,
                  font: `700 10.5px ${TOK.mono}`, padding: "1px 7px",
                }}>{tb.badge}</span>
              )}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 11.5, color: TOK.muted, paddingRight: 4 }}>
            {t("roleNote", { roles: roles.length > 0 ? roles.join(" / ") : "—" })}
          </span>
        </div>

        {error && (
          <div style={{
            marginBottom: 12, padding: "9px 14px", borderRadius: 8, fontSize: 12.5,
            color: TOK.red, background: TOK.redBg, border: `1px solid ${TOK.redBd}`,
          }}>{error}</div>
        )}

        {tab === "inbox" && (
          loading ? (
            <div style={{ padding: "48px 0", textAlign: "center", color: TOK.faint, fontSize: 13 }}>
              {t("loading")}
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "400px 1fr", gap: 16, alignItems: "start" }}>
              <ProposalList
                items={inboxItems}
                roles={roles}
                selectedId={selId}
                onSelect={setSelId}
              />
              <ProposalDetail
                p={selected}
                roles={roles}
                busy={busy}
                onApprove={approve}
                onReject={reject}
                onShelve={() => setSelId(null)}
                onGoto={(id) => { setTab("inbox"); setSelId(id); }}
                episodeMeta={episodeMeta}
              />
            </div>
          )
        )}

        {tab === "digest" && (
          <div style={{
            background: TOK.card, border: `1px solid ${TOK.border}`, borderRadius: 10,
            padding: "72px 24px", textAlign: "center", maxWidth: 1120,
          }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: TOK.secondary, marginBottom: 8 }}>
              {t("digest.empty")}
            </div>
            <div style={{ fontSize: 12, color: TOK.faint, lineHeight: 1.7 }}>
              {t("digest.hint")}
            </div>
          </div>
        )}

        {tab === "audit" && (
          loading ? (
            <div style={{ padding: "48px 0", textAlign: "center", color: TOK.faint, fontSize: 13 }}>
              {t("loading")}
            </div>
          ) : (
            <AuditTable items={auditItems} />
          )
        )}
      </div>
    </div>
  );
}
