"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { formatAlarmSkipped, type PatrolItem } from "./types";

interface Props {
  item: PatrolItem;
  onClose: () => void;
}

/**
 * Side panel showing every field on a skill_run plus drill links to:
 *   - /alarms/[id]    when AlarmEmitter wrote a row
 *   - /skills?slug=X  when the skill_documents row is reachable
 *   - sidebar query for the skill's execution_logs (deferred — would show
 *     per-step pipeline output; current ExecutionLogController list endpoint
 *     already supports the skill_id filter we'd need.)
 *
 * We deliberately do NOT show the raw step_results JSON — that goes in the
 * Skill Run replay view, which lives under /skills/<slug>/runs/<id>. Linking
 * out keeps this panel focused on "did it trigger?" rather than "what data
 * did it see?".
 */
export function PatrolDetailPanel({ item, onClose }: Props) {
  const t = useTranslations("patrol");
  return (
    <div style={{
      width: 360,
      flexShrink: 0,
      background: "#fff",
      borderRadius: 8,
      border: "1px solid #e2e8f0",
      padding: 16,
      maxHeight: "calc(100vh - 200px)",
      overflowY: "auto",
      position: "sticky",
      top: 16,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 13, fontWeight: 700 }}>
          {t("runTitle", { id: item.skill_run_id })}
        </h3>
        <button
          onClick={onClose}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "#a0aec0",
            fontSize: 18,
            padding: 0,
            lineHeight: 1,
          }}
        >×</button>
      </div>

      <Field label={t("fieldSkill")}>
        <div style={{ fontWeight: 600 }}>{item.skill_title ?? "—"}</div>
        <div style={{ fontSize: 10, color: "#a0aec0", fontFamily: "ui-monospace, monospace" }}>
          {item.skill_slug ?? `id=${item.skill_id}`} · stage={item.skill_stage ?? "—"}
        </div>
      </Field>

      <Field label={t("fieldTrigger")}>
        <div>{item.triggered_by ?? "—"}</div>
        <div style={{ fontSize: 10, color: "#a0aec0" }}>{item.triggered_at}</div>
      </Field>

      <Field label={t("fieldEvent")}>
        <div>{item.event_type ?? "—"}</div>
        {item.event_time && (
          <div style={{ fontSize: 10, color: "#a0aec0" }}>event_time={item.event_time}</div>
        )}
      </Field>

      <Field label={t("fieldPayload")}>
        <KV k="equipment_id" v={item.equipment_id} />
        <KV k="lot_id" v={item.lot_id} />
        <KV k="step_id" v={item.step_id} />
      </Field>

      <Field label={t("fieldRun")}>
        <KV k="status" v={item.status} />
        <KV k="duration_ms" v={item.duration_ms?.toString() ?? null} />
        <KV k="steps" v={`${item.steps_passed} / ${item.steps_total}`} />
      </Field>

      <Field label={t("fieldAlarm")}>
        {item.alarm_id ? (
          <Link
            href={`/alarms/${item.alarm_id}`}
            style={{ color: "#3182ce", textDecoration: "none", fontWeight: 600 }}
          >
            → {t("openAlarm", { id: item.alarm_id })}
          </Link>
        ) : (
          <div>
            <span style={{ color: "#9c4221" }}>{formatAlarmSkipped(item.alarm_skipped_reason, t)}</span>
            {item.alarm_skipped_reason && (
              <div style={{ fontSize: 10, color: "#a0aec0", marginTop: 2 }}>
                code = {item.alarm_skipped_reason}
              </div>
            )}
          </div>
        )}
      </Field>

      {item.skill_slug && (
        <div style={{ marginTop: 16, paddingTop: 12, borderTop: "1px solid #f0f4f8" }}>
          <Link
            href={`/skills?slug=${encodeURIComponent(item.skill_slug)}`}
            style={{ fontSize: 12, color: "#3182ce", textDecoration: "none" }}
          >
            ↗ {t("openInSkillLibrary", { slug: item.skill_slug })}
          </Link>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{
        fontSize: 10,
        fontWeight: 700,
        color: "#718096",
        textTransform: "uppercase",
        letterSpacing: "0.4px",
        marginBottom: 4,
      }}>
        {label}
      </div>
      <div style={{ fontSize: 12, color: "#2d3748" }}>{children}</div>
    </div>
  );
}

function KV({ k, v }: { k: string; v: string | null }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: 6, fontSize: 11 }}>
      <span style={{ color: "#a0aec0", fontFamily: "ui-monospace, monospace" }}>{k}</span>
      <span style={{ fontFamily: "ui-monospace, monospace" }}>{v ?? "—"}</span>
    </div>
  );
}
