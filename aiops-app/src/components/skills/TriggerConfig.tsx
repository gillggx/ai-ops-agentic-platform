"use client";

/**
 * TriggerConfig — Phase 11 v3 (doc-style).
 *
 * Author mode renders the trigger as a single, non-editable prose sentence
 * ("TRIGGER · OOC 發生時 trigger（針對 event payload 所帶的對象）"). Run /
 * Execute mode renders the same sentence but key tokens are inline pills
 * that, when clicked, expand a small editor below for that one field.
 *
 * Replaces the v2 collapsible grid panel that exposed scope / SLA /
 * evidence-window / etc. — those v2 fields were too "form-like" for the
 * "skill = knowledge document" design philosophy.
 */
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { Icon } from "./atoms";
import type { TriggerConfig as TC } from "./atoms";

// ── Catalog fetch (same as v2) ───────────────────────────────────────
type SystemEventDef = {
  id: string;
  label: string;
  desc: string;
  owner: string;
  color: string;
};

function ownerOf(name: string): string {
  const pref = name.split("_")[0].toUpperCase();
  if (["SPC", "FDC", "APC", "PM", "EQUIPMENT"].includes(pref)) {
    return pref === "EQUIPMENT" ? "EQ" : pref;
  }
  if (name.includes("RECIPE")) return "RECIPE";
  if (name.includes("MONITOR")) return "QA";
  if (name.includes("ALARM")) return "ALARM";
  if (name.includes("ENGINEER")) return "ENG";
  return "SYS";
}

function colorFor(owner: string): string {
  if (["SPC", "FDC", "ALARM"].includes(owner)) return "var(--fail)";
  if (["APC", "ENG", "RECIPE"].includes(owner)) return "var(--warn)";
  return "var(--ai)";
}

function useEventCatalog(): { events: SystemEventDef[]; loading: boolean } {
  const [events, setEvents] = useState<SystemEventDef[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    fetch("/api/admin/event-types")
      .then((r) => r.ok ? r.json() : [])
      .then((rows: Array<Record<string, unknown>>) => {
        if (cancelled) return;
        const list: SystemEventDef[] = (Array.isArray(rows) ? rows : [])
          .filter((r) => r.is_active !== false && r.isActive !== false)
          .map((r) => {
            const name = String(r.name ?? "");
            const owner = ownerOf(name);
            return {
              id: name,
              label: name,
              desc: String(r.description ?? ""),
              owner,
              color: colorFor(owner),
            };
          });
        setEvents(list);
      })
      .catch(() => setEvents([]))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);
  return { events, loading };
}

// ── Hardcoded EQP / station id list (matches simulator config) ──────
// Keeping in sync with ontology_simulator/config.py: TOTAL_TOOLS = 10.
// If the fleet grows, swap to fetch /api/admin/equipment.
const TOOL_IDS = Array.from({ length: 10 }, (_, i) => `EQP-${String(i + 1).padStart(2, "0")}`);
const STATION_IDS = ["PHOTO", "ETCH", "CMP", "IMP", "DIFF", "THIN"];

// ── Inline pill primitives ──────────────────────────────────────────
function InlinePill({
  children, onClick, accent, mono, disabled,
}: {
  children: ReactNode;
  onClick?: () => void;
  accent?: boolean;
  mono?: boolean;
  disabled?: boolean;
}) {
  const styles: CSSProperties = {
    all: "unset",
    cursor: disabled ? "default" : "pointer",
    display: "inline-flex", alignItems: "center", gap: 4,
    padding: "1px 7px", borderRadius: 4,
    background: accent ? "var(--ai-bg)" : "var(--surface-2)",
    color: accent ? "var(--ai)" : "var(--ink)",
    border: `1px dashed ${accent ? "color-mix(in oklch, var(--ai), transparent 60%)" : "var(--line-strong)"}`,
    fontSize: 13.5, fontWeight: 500, lineHeight: 1.4,
    fontFamily: mono ? "JetBrains Mono, ui-monospace, monospace" : "inherit",
  };
  return (
    <button onClick={disabled ? undefined : onClick} style={styles} disabled={disabled}>
      {children}
    </button>
  );
}

function Pill({ active, onClick, children, color }: {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
  color?: string;
}) {
  return (
    <button onClick={onClick} style={{
      all: "unset", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6,
      padding: "3px 9px", borderRadius: 5,
      background: active ? (color || "var(--ink)") : "var(--surface-2)",
      color: active ? "var(--bg)" : "var(--ink)",
      border: `1px solid ${active ? (color || "var(--ink)") : "var(--line-strong)"}`,
      fontSize: 13, fontWeight: 450,
    }}>{children}</button>
  );
}

function Editor({ title, children, onClose }: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  return (
    <div style={{
      marginTop: 8, padding: "14px 16px",
      background: "var(--surface)",
      border: "1px solid var(--line)", borderRadius: 8,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-3)", letterSpacing: "0.08em" }}>{title}</span>
        <button onClick={onClose} style={{ all: "unset", cursor: "pointer", color: "var(--ink-3)", fontSize: 11.5 }}>Done</button>
      </div>
      {children}
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────

/** Coerce legacy v1/v2 trigger shape into v3 canonical (event/schedule/target). */
export function migrateTrigger(t: TC): TC {
  const out: TC = { ...t };
  // system → event
  if (out.type === "system") {
    out.type = "event";
    if (!out.event && out.event_type) out.event = out.event_type;
  }
  // legacy schedule flat fields → schedule.*
  if ((out.type === "schedule" || !out.type) && !out.schedule) {
    if (out.unit === "hour" && out.every) {
      out.schedule = { mode: "hourly", every: out.every };
    } else if (out.unit === "minute" && out.every) {
      // Map minute-based intervals to nearest hourly bucket; keep `every` minutes
      out.schedule = { mode: "hourly", every: Math.max(1, Math.round(out.every / 60) || 1) };
    } else if (out.unit === "day" && out.every) {
      out.schedule = { mode: "daily", time: "08:00" };
    }
  }
  // best-effort scope → target
  if (!out.target) {
    const s = (out.scope ?? "").trim();
    if (!s) {
      out.target = { kind: "all", ids: [] };
    } else {
      // tool_id IN ('EQP-01','EQP-02') → ids
      const m = s.match(/['"]([A-Z0-9_-]+)['"]/g);
      if (m && m.length) {
        const ids = m.map((x) => x.replace(/['"]/g, ""));
        out.target = { kind: "tools", ids };
      } else {
        out.target = { kind: "all", ids: [] };
      }
    }
  }
  // strip legacy v2 header fields — UI doesn't show them anymore
  delete out.sla_seconds;
  delete out.evidence_window_lots;
  delete out.evidence_window_days;
  return out;
}

/** Render-only helper used by both author + run modes. */
function buildDescription(t: TC, eventLabel: string | null, targetText: string): string {
  if (t.type === "event") {
    return `${eventLabel || t.event || "—"} 發生時 trigger（針對 event payload 所帶的對象）`;
  }
  const m = t.schedule?.mode ?? "hourly";
  if (m === "hourly") return `每 ${t.schedule?.every ?? 4} 小時檢查 ${targetText}`;
  return `每日 ${t.schedule?.time ?? "08:00"} 檢查 ${targetText}`;
}

// ── Main component ──────────────────────────────────────────────────

export function TriggerConfigEditor({
  trigger, setTrigger, mode,
}: {
  trigger: TC;
  setTrigger: (t: TC) => void;
  mode: "author" | "run";
}) {
  const { events, loading } = useEventCatalog();
  const [editing, setEditing] = useState<null | "type" | "event" | "schedule" | "target">(null);

  const ev = events.find((e) => e.id === trigger.event);
  const targetText =
    !trigger.target || trigger.target.kind === "all" ? "所有機台"
    : trigger.target.kind === "tools" ? (trigger.target.ids.join(", ") || "（未指定機台）")
    : (trigger.target.ids.join(" / ") || "（未指定站點）") + " 站";

  const description = buildDescription(trigger, ev?.label ?? null, targetText);
  const setEvent = (id: string) => { setTrigger({ ...trigger, event: id }); setEditing(null); };
  const setSched = (patch: Partial<NonNullable<TC["schedule"]>>) => setTrigger({
    ...trigger, schedule: { ...(trigger.schedule ?? { mode: "hourly", every: 4 }), ...patch },
  });
  const setTarget = (target: NonNullable<TC["target"]>) => setTrigger({ ...trigger, target });

  // Phase 11 v11 — 3-row labeled layout. Replaces the previous inline-prose
  // approach where the 對象 pill could disappear behind a wrapped line / be
  // missed by users (per feedback「在 execute mode 選時間，一樣不能設定對象」).
  // Author mode shows read-only with a pencil to flip into editable;
  // Execute mode is always editable.
  const [authorEditing, setAuthorEditing] = useState(false);
  const editable = mode === "run" || authorEditing;

  const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div style={{
      display: "grid", gridTemplateColumns: "78px 1fr",
      alignItems: "center", gap: 14,
      padding: "8px 0",
    }}>
      <span className="mono" style={{
        fontSize: 10.5, color: "var(--ink-3)", letterSpacing: "0.08em",
      }}>{label}</span>
      <div>{children}</div>
    </div>
  );

  const scheduleLabel = trigger.schedule?.mode === "daily"
    ? `每日 ${trigger.schedule.time ?? "08:00"}`
    : `每 ${trigger.schedule?.every ?? 4} 小時`;

  return (
    <div style={{ marginTop: 24 }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "12px 0 4px",
      }}>
        <span className="mono" style={{
          fontSize: 10.5, color: "var(--ink-3)", letterSpacing: "0.08em",
        }}>TRIGGER</span>
        <span style={{ flex: 1, height: 1, background: "var(--line)" }}/>
        {mode === "author" && (
          <button
            type="button"
            onClick={() => setAuthorEditing((v) => !v)}
            aria-label={authorEditing ? "完成編輯" : "編輯 trigger"}
            style={{
              all: "unset", cursor: "pointer",
              padding: "3px 9px", borderRadius: 5,
              fontSize: 11, color: authorEditing ? "var(--bg)" : "var(--ink-2)",
              background: authorEditing ? "var(--ink)" : "var(--surface-2)",
              border: `1px solid ${authorEditing ? "var(--ink)" : "var(--line-strong)"}`,
              display: "inline-flex", alignItems: "center", gap: 5,
            }}>
            {authorEditing ? "Done" : <><Icon.Pencil/> Edit</>}
          </button>
        )}
      </div>

      {!editable ? (
        // Author mode read-only: prose summary + meta
        <div style={{
          fontSize: 14.5, lineHeight: 1.6, color: "var(--ink)",
          padding: "8px 0 16px",
        }}>
          {loading ? "…" : description}
        </div>
      ) : (
        <div style={{ padding: "4px 0 12px" }}>
          <Row label="類型">
            <InlinePill onClick={() => setEditing(editing === "type" ? null : "type")}>
              {trigger.type === "event" ? "Event 發生" : "排程時間到"}
              <Chev open={editing === "type"}/>
            </InlinePill>
          </Row>

          {trigger.type === "event" ? (
            <Row label="事件">
              <InlinePill mono accent onClick={() => setEditing(editing === "event" ? null : "event")}>
                {ev?.label || trigger.event || "—"}
                <Chev open={editing === "event"}/>
              </InlinePill>
            </Row>
          ) : (
            <Row label="排程">
              <InlinePill mono accent onClick={() => setEditing(editing === "schedule" ? null : "schedule")}>
                {scheduleLabel}
                <Chev open={editing === "schedule"}/>
              </InlinePill>
            </Row>
          )}

          <Row label="對象">
            {trigger.type === "event" ? (
              <span style={{ color: "var(--ink-3)", fontSize: 12.5, fontStyle: "italic" }}>
                對象來自 event payload（不可指定 — event 自己帶 tool_id / lot_id）
              </span>
            ) : (
              <InlinePill onClick={() => setEditing(editing === "target" ? null : "target")}>
                {targetText}
                <Chev open={editing === "target"}/>
              </InlinePill>
            )}
          </Row>

          <div style={{
            marginTop: 4, fontSize: 12, color: "var(--ink-3)", fontStyle: "italic",
          }}>
            → {description}
          </div>
        </div>
      )}

      {editable && editing === "type" && (
        <Editor onClose={() => setEditing(null)} title="Trigger 類型">
          <div style={{ display: "flex", gap: 8 }}>
            <Pill active={trigger.type === "event"} color="var(--fail)"
              onClick={() => { setTrigger({ ...trigger, type: "event" }); setEditing(null); }}>
              <span style={{
                width: 6, height: 6, borderRadius: 999,
                background: trigger.type === "event" ? "var(--bg)" : "var(--fail)",
              }}/>
              Event-driven
            </Pill>
            <Pill active={trigger.type === "schedule"} color="var(--pass)"
              onClick={() => { setTrigger({ ...trigger, type: "schedule" }); setEditing(null); }}>
              <span style={{
                width: 6, height: 6, borderRadius: 999,
                background: trigger.type === "schedule" ? "var(--bg)" : "var(--pass)",
              }}/>
              定期排程
            </Pill>
          </div>
        </Editor>
      )}

      {editable && editing === "event" && (
        <Editor onClose={() => setEditing(null)} title="選擇 system event">
          {loading ? (
            <div style={{ fontSize: 12, color: "var(--ink-3)" }}>loading event catalog…</div>
          ) : events.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--ink-3)" }}>
              （沒有已註冊的 event_type，IT_ADMIN 可在 /admin/event-types 新增）
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {events.map((e) => {
                const active = e.id === trigger.event;
                return (
                  <button key={e.id} onClick={() => setEvent(e.id)}
                    style={{
                      all: "unset", cursor: "pointer",
                      display: "grid", gridTemplateColumns: "auto 1fr", gap: 10, alignItems: "center",
                      padding: "9px 11px", borderRadius: 6,
                      background: active ? "var(--surface-2)" : "transparent",
                      border: `1px solid ${active ? "var(--ink-2)" : "var(--line)"}`,
                    }}>
                    <span style={{ width: 6, height: 6, borderRadius: 999, background: e.color }}/>
                    <div>
                      <div className="mono" style={{ fontSize: 12, color: "var(--ink)", fontWeight: 500 }}>
                        {e.label}
                      </div>
                      <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 2 }}>
                        {e.desc}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </Editor>
      )}

      {editable && editing === "schedule" && (
        <Editor onClose={() => setEditing(null)} title="排程設定">
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ display: "flex", gap: 8 }}>
              <Pill active={(trigger.schedule?.mode ?? "hourly") === "hourly"}
                onClick={() => setSched({ mode: "hourly", every: trigger.schedule?.every ?? 4 })}>
                每 N 小時
              </Pill>
              <Pill active={trigger.schedule?.mode === "daily"}
                onClick={() => setSched({ mode: "daily", time: trigger.schedule?.time ?? "08:00" })}>
                每日固定時間
              </Pill>
            </div>
            {(trigger.schedule?.mode ?? "hourly") === "hourly" ? (
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 12, color: "var(--ink-3)" }}>每</span>
                <select
                  value={trigger.schedule?.every ?? 4}
                  onChange={(e) => setSched({ every: parseInt(e.target.value) })}
                  style={{
                    padding: "6px 10px", fontSize: 12.5,
                    border: "1px solid var(--line-strong)",
                    background: "var(--surface)", color: "var(--ink)",
                    borderRadius: 5, fontFamily: "JetBrains Mono, monospace",
                  }}>
                  {[1, 2, 3, 4, 6, 8, 12].map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
                <span style={{ fontSize: 12, color: "var(--ink-3)" }}>小時跑一次（最短 1h、最長 12h）</span>
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 12, color: "var(--ink-3)" }}>每日</span>
                <input
                  type="time" value={trigger.schedule?.time ?? "08:00"}
                  onChange={(e) => setSched({ time: e.target.value })}
                  style={{
                    padding: "6px 10px", fontSize: 12.5,
                    border: "1px solid var(--line-strong)",
                    background: "var(--surface)", color: "var(--ink)",
                    borderRadius: 5, fontFamily: "JetBrains Mono, monospace",
                  }}/>
                <span style={{ fontSize: 12, color: "var(--ink-3)" }}>（Asia/Taipei）</span>
              </div>
            )}
          </div>
        </Editor>
      )}

      {editable && editing === "target" && (
        <Editor onClose={() => setEditing(null)} title="檢查對象">
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", gap: 8 }}>
              <Pill active={!trigger.target || trigger.target.kind === "all"}
                onClick={() => setTarget({ kind: "all", ids: [] })}>所有機台</Pill>
              <Pill active={trigger.target?.kind === "tools"}
                onClick={() => setTarget({
                  kind: "tools",
                  ids: trigger.target?.ids?.length ? trigger.target.ids : ["EQP-01", "EQP-02"],
                })}>指定機台</Pill>
              <Pill active={trigger.target?.kind === "stations"}
                onClick={() => setTarget({
                  kind: "stations",
                  ids: trigger.target?.ids?.length ? trigger.target.ids : ["PHOTO"],
                })}>指定站點</Pill>
            </div>
            {trigger.target?.kind === "tools" && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {TOOL_IDS.map((id) => {
                  const active = trigger.target?.ids?.includes(id) ?? false;
                  return (
                    <button key={id}
                      onClick={() => setTarget({
                        kind: "tools",
                        ids: active
                          ? (trigger.target?.ids ?? []).filter((x) => x !== id)
                          : [...(trigger.target?.ids ?? []), id],
                      })}
                      style={{
                        all: "unset", cursor: "pointer",
                        padding: "5px 10px", borderRadius: 999, fontSize: 11.5,
                        background: active ? "var(--ink)" : "var(--surface)",
                        color: active ? "var(--bg)" : "var(--ink-2)",
                        border: `1px solid ${active ? "var(--ink)" : "var(--line-strong)"}`,
                        fontFamily: "JetBrains Mono, monospace",
                      }}>
                      {active ? "✓ " : ""}{id}
                    </button>
                  );
                })}
              </div>
            )}
            {trigger.target?.kind === "stations" && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {STATION_IDS.map((id) => {
                  const active = trigger.target?.ids?.includes(id) ?? false;
                  return (
                    <button key={id}
                      onClick={() => setTarget({
                        kind: "stations",
                        ids: active
                          ? (trigger.target?.ids ?? []).filter((x) => x !== id)
                          : [...(trigger.target?.ids ?? []), id],
                      })}
                      style={{
                        all: "unset", cursor: "pointer",
                        padding: "5px 10px", borderRadius: 999, fontSize: 11.5,
                        background: active ? "var(--ink)" : "var(--surface)",
                        color: active ? "var(--bg)" : "var(--ink-2)",
                        border: `1px solid ${active ? "var(--ink)" : "var(--line-strong)"}`,
                      }}>
                      {active ? "✓ " : ""}{id}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </Editor>
      )}
    </div>
  );
}

function Chev({ open }: { open: boolean }) {
  // Icon.Chevron's prop type is `object`, so we wrap in a span to apply
  // the rotate transform without fighting the typedef.
  return (
    <span style={{ display: "inline-flex", transform: open ? "rotate(180deg)" : "none" }}>
      <Icon.Chevron/>
    </span>
  );
}
