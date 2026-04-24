"use client";

/**
 * Admin → Triggers Overview
 *
 * Cross-pipeline read-only table: all Auto-Patrols + Auto-Check Rules +
 * Published Skills in one place. Editing deep-links to the existing
 * dedicated CRUD pages for each trigger type (kept reachable via URL
 * even though their menu entries were removed in the Option A UX
 * consolidation).
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

type TriggerRow = {
  kind: "patrol" | "rule" | "skill";
  id: number;
  name: string;
  pipeline_id: number | null;
  pipeline_name: string | null;
  trigger_summary: string;  // cron expr / event type / on-demand
  severity: string | null;
  is_active: boolean;
  edit_href: string;
};

export default function TriggersOverviewPage() {
  const [rows, setRows] = useState<TriggerRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "patrol" | "rule" | "skill">("all");

  const load = useCallback(async () => {
    try {
      setError(null);
      // Fetch 3 sources in parallel
      const [patrolRes, ruleRes, skillRes] = await Promise.all([
        fetch("/api/admin/auto-patrols?with_stats=false", { cache: "no-store" }),
        fetch("/api/pipeline-builder/auto-check-rules", { cache: "no-store" }),
        fetch("/api/pipeline-builder/published-skills", { cache: "no-store" }),
      ]);
      const patrolJson = await patrolRes.json();
      const ruleJson = await ruleRes.json();
      const skillJson = await skillRes.json();

      const patrols = Array.isArray(patrolJson) ? patrolJson : (patrolJson?.data ?? []);
      const rules = Array.isArray(ruleJson) ? ruleJson : (ruleJson?.data ?? []);
      const skills = Array.isArray(skillJson) ? skillJson : (skillJson?.data ?? []);

      const unified: TriggerRow[] = [
        ...patrols.map((p: Record<string, unknown>) => ({
          kind: "patrol" as const,
          id: Number(p.id),
          name: String(p.name ?? ""),
          pipeline_id: (p.pipeline_id as number) ?? null,
          pipeline_name: null,  // filled below if wanted
          trigger_summary: p.trigger_mode === "schedule"
            ? `schedule: ${p.cron_expr ?? "?"}`
            : `event: ${p.event_type_id ?? "?"}`,
          severity: (p.alarm_severity as string) ?? null,
          is_active: Boolean(p.is_active),
          edit_href: `/admin/auto-patrols?selected=${p.id}`,
        })),
        ...rules.map((r: Record<string, unknown>) => ({
          kind: "rule" as const,
          id: Number(r.id),
          name: String(r.pipeline_name ?? `rule-${r.id}`),
          pipeline_id: (r.pipeline_id as number) ?? null,
          pipeline_name: (r.pipeline_name as string) ?? null,
          trigger_summary: `event: ${r.event_type ?? "?"}`,
          severity: null,
          is_active: true,
          edit_href: `/admin/auto-check-rules`,
        })),
        ...skills.map((s: Record<string, unknown>) => ({
          kind: "skill" as const,
          id: Number(s.id),
          name: String(s.name ?? s.skill_name ?? ""),
          pipeline_id: (s.pipeline_id as number) ?? null,
          pipeline_name: null,
          trigger_summary: "on-demand (chat / published skill)",
          severity: null,
          is_active: (s.status ?? "published") !== "archived",
          edit_href: `/admin/published-skills`,
        })),
      ];
      setRows(unified);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const visible = (rows ?? []).filter(r => filter === "all" || r.kind === filter);

  return (
    <div style={{ padding: 20, maxWidth: 1400 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: "#1a202c" }}>Triggers Overview</h1>
          <p style={{ margin: "4px 0 16px", fontSize: 13, color: "#718096" }}>
            跨 pipeline 的綁定總覽：Auto-Patrol（schedule/event） + Auto-Check Rule（event） + Published Skill（on-demand）。
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link href="/admin/auto-patrols?new=1" style={{
            padding: "8px 16px", fontSize: 13, fontWeight: 600,
            background: "#16a34a", color: "#fff",
            borderRadius: 6, textDecoration: "none",
            boxShadow: "0 1px 3px rgba(22,163,74,0.3)",
          }}>
            ＋ 建立 Patrol
          </Link>
          <Link href="/admin/pipeline-builder/new?kind=auto_check" style={{
            padding: "8px 16px", fontSize: 13, fontWeight: 600,
            background: "#fff", color: "#d46b08",
            border: "1px solid #d46b08", borderRadius: 6, textDecoration: "none",
          }} title="Auto-Check 由 pipeline publish 自動建立，到 Pipeline Builder 建立 kind=auto_check 的 pipeline">
            ＋ 建立 Auto-Check
          </Link>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        {(["all", "patrol", "rule", "skill"] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)} style={{
            padding: "6px 14px", fontSize: 12, borderRadius: 16,
            border: filter === f ? "1px solid #1890ff" : "1px solid #d9d9d9",
            background: filter === f ? "#e6f7ff" : "#fff",
            color: filter === f ? "#1890ff" : "#4a5568",
            fontWeight: 600, cursor: "pointer",
          }}>
            {f === "all" ? "全部"
              : f === "patrol" ? "Auto-Patrol"
              : f === "rule" ? "Auto-Check Rule"
              : "Published Skill"}
          </button>
        ))}
      </div>

      {error && <div style={{ padding: 12, color: "#cf1322", background: "#fff1f0", borderRadius: 6, marginBottom: 12 }}>{error}</div>}

      {rows === null ? (
        <div style={{ padding: 24, color: "#a0aec0" }}>Loading…</div>
      ) : visible.length === 0 ? (
        <div style={{ padding: 40, textAlign: "center", color: "#a0aec0", background: "#fafafa", borderRadius: 8 }}>
          沒有對應的 triggers
        </div>
      ) : (
        <div style={{ background: "#fff", borderRadius: 8, border: "1px solid #e2e8f0", overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f7fafc", borderBottom: "1px solid #e2e8f0" }}>
                <th style={th}>類型</th>
                <th style={th}>名稱</th>
                <th style={th}>Pipeline</th>
                <th style={th}>觸發</th>
                <th style={th}>Severity</th>
                <th style={th}>狀態</th>
                <th style={{ ...th, textAlign: "right" }}>編輯</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r, i) => (
                <tr key={`${r.kind}-${r.id}`} style={{ background: i % 2 ? "#fafafa" : "#fff", borderBottom: "1px solid #f0f0f0" }}>
                  <td style={td}><KindChip kind={r.kind} /></td>
                  <td style={{ ...td, fontWeight: 600, color: "#1a202c" }}>{r.name || "(無名)"}</td>
                  <td style={td}>
                    {r.pipeline_id != null ? (
                      <Link href={`/admin/pipeline-builder/${r.pipeline_id}`} style={{ color: "#1890ff", textDecoration: "none" }}>
                        #{r.pipeline_id}
                      </Link>
                    ) : "—"}
                  </td>
                  <td style={{ ...td, color: "#4a5568", fontFamily: "ui-monospace, monospace", fontSize: 12 }}>{r.trigger_summary}</td>
                  <td style={td}>
                    {r.severity ? <span style={severityBadge(r.severity)}>{r.severity}</span> : "—"}
                  </td>
                  <td style={td}>
                    <span style={{
                      padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600,
                      background: r.is_active ? "#c6f6d5" : "#e2e8f0",
                      color: r.is_active ? "#276749" : "#718096",
                    }}>
                      {r.is_active ? "active" : "inactive"}
                    </span>
                  </td>
                  <td style={{ ...td, textAlign: "right" }}>
                    <Link href={r.edit_href} style={{
                      padding: "4px 10px", fontSize: 11, borderRadius: 4,
                      border: "1px solid #d9d9d9", color: "#4a5568", textDecoration: "none", background: "#fff",
                    }}>編輯 →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const th: React.CSSProperties = {
  padding: "10px 12px", textAlign: "left", fontSize: 11,
  fontWeight: 700, color: "#4a5568", textTransform: "uppercase", letterSpacing: "0.3px",
};
const td: React.CSSProperties = { padding: "10px 12px", verticalAlign: "middle" };

function KindChip({ kind }: { kind: "patrol" | "rule" | "skill" }) {
  const [label, bg, fg] = kind === "patrol" ? ["🔍 Patrol", "#e6f7ff", "#1890ff"]
    : kind === "rule" ? ["⚡ Rule", "#fff7e6", "#d46b08"]
    : ["📘 Skill", "#f0f5ff", "#2f54eb"];
  return (
    <span style={{ padding: "2px 8px", borderRadius: 10, background: bg, color: fg, fontSize: 11, fontWeight: 600 }}>
      {label}
    </span>
  );
}

function severityBadge(sev: string): React.CSSProperties {
  const up = sev.toUpperCase();
  const [bg, fg] = up === "CRITICAL" || up === "HIGH" ? ["#fff1f0", "#cf1322"]
    : up === "MEDIUM" ? ["#fff7e6", "#d46b08"]
    : ["#f6ffed", "#389e0d"];
  return {
    padding: "2px 8px", borderRadius: 10, background: bg, color: fg, fontSize: 11, fontWeight: 600,
  };
}
