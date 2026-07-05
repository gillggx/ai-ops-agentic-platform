"use client";

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { useTranslations } from "next-intl";
import { AlarmDetail, useBriefing, type Alarm } from "./AlarmDetailLegacy";
import type { Cluster } from "./types";
import { activeLocale } from "@/i18n/format";

const KNOWN_SEVERITIES = ["critical", "high", "med", "low"] as const;

function useSevLabel() {
  const t = useTranslations("alarms");
  return (severity: string): string =>
    (KNOWN_SEVERITIES as readonly string[]).includes(severity)
      ? t(`sevLong.${severity}`)
      : severity;
}

function fmtDateRange(first: string | null, last: string | null): string {
  if (!first || !last) return "—";
  const f = new Date(first), l = new Date(last);
  const sameDay = f.toDateString() === l.toDateString();
  const t = (d: Date) => d.toLocaleTimeString(activeLocale(), { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return `${f.toLocaleDateString(activeLocale())} ${t(f)} → ${t(l)}`;
  return `${f.toLocaleDateString(activeLocale())} ${t(f)} → ${l.toLocaleDateString(activeLocale())} ${t(l)}`;
}

export function ClusterDetailPanel({ cluster, onAcked }: {
  cluster: Cluster | null;
  onAcked: (count: number) => void;
}) {
  const t = useTranslations("alarms");
  const sevLabel = useSevLabel();
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>;
  // Cluster-level briefing.
  const briefingData = useMemo(() => cluster ? JSON.stringify({
    total: cluster.count,
    severities: { [cluster.severity]: cluster.count },
    top_equipment: [{ equipment_id: cluster.equipment_id, count: cluster.count }],
    cluster_focus: {
      equipment_id: cluster.equipment_id,
      first_at: cluster.first_at,
      last_at: cluster.last_at,
      affected_lots: cluster.affected_lots,
      cause: cluster.cause,
      trigger_events: cluster.trigger_events,
    },
  }) : "", [cluster]);
  // Cache key = cluster_id + open_count + last_at. Re-opening the same
  // cluster within TTL replays cached text. Any state change (new alarms,
  // ACK / resolve) shifts the count or last_at and invalidates.
  const synthesis = useBriefing("alarm", briefingData,
    cluster ? `${cluster.cluster_id}:${cluster.open_count}:${cluster.last_at ?? ""}` : undefined);
  useEffect(() => { if (cluster) synthesis.refresh(); }, [cluster?.cluster_id]); // eslint-disable-line

  const [acking, setAcking] = useState(false);
  const [ackError, setAckError] = useState<string | null>(null);
  const ack = async () => {
    if (!cluster) return;
    setAcking(true);
    setAckError(null);
    try {
      const res = await fetch("/api/admin/alarms/cluster-ack", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ equipment_id: cluster.equipment_id }),
      });
      if (!res.ok) { setAckError(`HTTP ${res.status}`); return; }
      const j = await res.json();
      onAcked(j.acknowledged ?? 0);
    } catch (e) { setAckError(String(e)); }
    finally { setAcking(false); }
  };

  // ── Drill-down state — swap middle pane between alarm list and a single
  //    alarm's detail. Modal flag opens the same detail in a 95% overlay. ──
  const [selectedAlarmId, setSelectedAlarmId] = useState<number | null>(null);
  const [selectedAlarm, setSelectedAlarm] = useState<Alarm | null>(null);
  const [loadingAlarm, setLoadingAlarm] = useState(false);
  const [alarmError, setAlarmError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  // Reset drill-down when cluster changes.
  useEffect(() => {
    setSelectedAlarmId(null);
    setSelectedAlarm(null);
    setExpanded(false);
    setAlarmError(null);
  }, [cluster?.cluster_id]);

  // Fetch single alarm when row clicked.
  useEffect(() => {
    if (selectedAlarmId == null) return;
    setLoadingAlarm(true);
    setAlarmError(null);
    fetch(`/api/admin/alarms/${selectedAlarmId}`)
      .then(async r => {
        if (!r.ok) { setAlarmError(`HTTP ${r.status}`); setSelectedAlarm(null); return; }
        const d = await r.json();
        setSelectedAlarm(d?.data ?? d ?? null);
      })
      .catch(e => setAlarmError(String(e)))
      .finally(() => setLoadingAlarm(false));
  }, [selectedAlarmId]);

  if (!cluster) {
    return (
      <main className="alarm-center__detail">
        <div className="alarm-center__empty">
          <div>
            <div style={{ fontSize: 32, marginBottom: 8 }}>👈</div>
            <div>{t("detail.emptyPrompt")}</div>
          </div>
        </div>
      </main>
    );
  }

  const inDetailMode = selectedAlarmId != null;

  return (
    <main className="alarm-center__detail" aria-label="Cluster detail" data-tour-id="alarm-detail">
      <header className="cluster-detail__head">
        <h1 className="cluster-detail__title">
          {cluster.equipment_id}{" "}
          <span style={{ color: "var(--text-3)", fontWeight: 400, fontSize: 13 }}>
            ({sevLabel(cluster.severity)})
          </span>
        </h1>
        <div className="cluster-detail__meta">
          <span>{t.rich("card.alarms", { n: cluster.count, strong })}</span>
          <span>{t.rich("detail.metaOpen", { n: cluster.open_count, strong })}</span>
          {cluster.ack_count > 0 && <span>{t.rich("detail.metaAcked", { n: cluster.ack_count, strong })}</span>}
          {cluster.affected_lots > 0 && <span>{t.rich("card.lots", { n: cluster.affected_lots, strong })}</span>}
          <span style={{ flexBasis: "100%" }} />
          <span>{fmtDateRange(cluster.first_at, cluster.last_at)}</span>
          {cluster.cause && <span>{t("detail.cause", { cause: cluster.cause })}</span>}
        </div>
        <button
          className="cluster-detail__action"
          onClick={ack}
          disabled={acking || cluster.open_count === 0}
          title={cluster.open_count === 0 ? t("detail.ackNoOpen") : t("detail.ackTitle", { n: cluster.open_count })}
        >
          {acking ? t("detail.ackBusy") : t("detail.ackButton", { n: cluster.open_count })}
        </button>
        {ackError && (
          <div style={{ position: "absolute", top: 48, right: 16, color: "var(--high)", fontSize: 11 }}>
            {ackError}
          </div>
        )}
      </header>

      {inDetailMode ? (
        <DetailView
          alarm={selectedAlarm}
          loading={loadingAlarm}
          error={alarmError}
          alarmId={selectedAlarmId}
          onBack={() => { setSelectedAlarmId(null); setSelectedAlarm(null); setExpanded(false); }}
          onExpand={() => setExpanded(true)}
        />
      ) : (
        <ListView
          cluster={cluster}
          synthesis={synthesis}
          onPick={id => setSelectedAlarmId(id)}
        />
      )}

      {expanded && selectedAlarm && (
        <ExpandedModal alarm={selectedAlarm} onClose={() => setExpanded(false)} />
      )}
    </main>
  );
}

// ── Embedded views ────────────────────────────────────────────

function ListView({ cluster, synthesis, onPick }: {
  cluster: Cluster;
  synthesis: ReturnType<typeof useBriefing>;
  onPick: (id: number) => void;
}) {
  const t = useTranslations("alarms");
  const sevLabel = useSevLabel();
  return (
    <>
      <section className="cluster-synthesis" data-tour-id="alarm-dr">
        <div className="cluster-synthesis__title">✨ {t("detail.synthesisTitle", { id: cluster.equipment_id })}</div>
        <div className="cluster-synthesis__meta">
          {t("detail.synthesisMeta", {
            n: cluster.count,
            sev: sevLabel(cluster.severity),
            range: fmtDateRange(cluster.first_at, cluster.last_at),
          })}
        </div>
        <div className="cluster-synthesis__body">
          {synthesis.loading ? (
            <span className="cluster-synthesis__loading">
              <span style={{ display: "inline-block", width: 8, height: 14, background: "var(--accent)", animation: "blink 1s step-end infinite", marginRight: 6, verticalAlign: "text-bottom" }} />
              {t("detail.synthesisLoading")}
            </span>
          ) : synthesis.text ? (
            <ReactMarkdown>{synthesis.text}</ReactMarkdown>
          ) : (
            <span className="cluster-synthesis__loading">{t("detail.synthesisEmpty")}</span>
          )}
        </div>
      </section>

      <section>
        <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8, fontFamily: "var(--font-mono)" }}>
          {t("detail.rowsHint", { n: cluster.count })}
        </div>
        {cluster.alarm_ids.length === 0 && (
          <div style={{ padding: 24, color: "var(--text-3)", textAlign: "center", fontSize: 13 }}>{t("detail.noAlarms")}</div>
        )}
        {cluster.alarm_ids.map(id => (
          <button
            key={id}
            type="button"
            className="alarm-row"
            style={{ display: "block", width: "100%", textAlign: "left", background: "var(--surface)", border: "1px solid var(--border)", cursor: "pointer", font: "inherit" }}
            onClick={() => onPick(id)}
          >
            <div className="alarm-row__head">
              <span style={{ color: "var(--text)", fontWeight: 600 }}>#{id}</span>
              <span>{sevLabel(cluster.severity)}</span>
              <span>{cluster.equipment_id}</span>
              <span className="alarm-row__link">{t("detail.enterDeep")}</span>
            </div>
            <div className="alarm-row__title">{cluster.title}</div>
          </button>
        ))}
      </section>
    </>
  );
}

function DetailView({ alarm, loading, error, alarmId, onBack, onExpand }: {
  alarm: Alarm | null;
  loading: boolean;
  error: string | null;
  alarmId: number | null;
  onBack: () => void;
  onExpand: () => void;
}) {
  const t = useTranslations("alarms");
  return (
    <section style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: 18 }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 12, gap: 10 }}>
        <button
          type="button"
          onClick={onBack}
          style={{
            background: "transparent", border: "1px solid var(--border)", borderRadius: 6,
            padding: "6px 12px", fontSize: 12, color: "var(--text-2)", cursor: "pointer",
            fontFamily: "var(--font-mono)",
          }}
        >
          {t("detail.backToList")}
        </button>
        <span style={{ fontSize: 12, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>
          {t("detail.alarmRef", { id: alarmId ?? "" })}
        </span>
        <button
          type="button"
          onClick={onExpand}
          disabled={!alarm}
          style={{
            marginLeft: "auto",
            background: "transparent", border: "1px solid var(--border)", borderRadius: 6,
            padding: "6px 12px", fontSize: 12, color: "var(--text-2)", cursor: alarm ? "pointer" : "not-allowed",
            fontFamily: "var(--font-mono)", opacity: alarm ? 1 : 0.4,
          }}
          title={t("detail.fullscreenTitle")}
        >
          ⛶ {t("detail.fullscreen")}
        </button>
      </div>
      {loading && <div style={{ color: "var(--text-3)", fontSize: 13 }}>{t("loading")}</div>}
      {error && <div style={{ color: "var(--high)", fontSize: 13 }}>{t("detail.loadFailed", { error })}</div>}
      {alarm && <AlarmDetail alarm={alarm} />}
    </section>
  );
}

function ExpandedModal({ alarm, onClose }: { alarm: Alarm; onClose: () => void }) {
  const t = useTranslations("alarms");
  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="alarm-detail-modal"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div className="alarm-detail-modal__panel" onClick={e => e.stopPropagation()}>
        <button
          type="button"
          className="alarm-detail-modal__close"
          onClick={onClose}
          aria-label={t("detail.close")}
          title={t("detail.closeEsc")}
        >
          ✕
        </button>
        <div className="alarm-detail-modal__body">
          <AlarmDetail alarm={alarm} />
        </div>
      </div>
    </div>
  );
}
