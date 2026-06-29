"use client";

/**
 * Skills v2 — Automate (画面 3 from spec §3.3).
 *
 * Bind a Skill to a Trigger (schedule | event) + Alarm Gate (patrol only)
 * + Outcome. Draft edits are local; "Done · 啟動" POSTs the automation
 * and bounces back to Library so the new role chip shows immediately.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { TK, FONT, ROLE_COLORS, ensurePlexFont } from "@/components/skills-v2/tokens";
import {
  GATES, OUTCOMES, SCHEDULES, TARGETS, parsePipelineNodes, parseTrigger,
  type AlarmSource, type EventType, type Role, type Skill, type Trigger, type TriggerKind,
} from "@/components/skills-v2/types";

type Identity = "patrol" | "datacheck";
/** Event-driven trigger sub-mode: subscribe to a raw simulator event by name,
 *  or to an upstream Auto Patrol's alarm. */
type EventMode = "raw" | "patrol";

export default function AutomatePage() {
  const params = useParams<{ slug: string }>();
  const router = useRouter();
  const slug = params?.slug ?? "";

  const [skill, setSkill] = useState<Skill | null>(null);
  const [sources, setSources] = useState<AlarmSource[]>([]);
  const [eventTypes, setEventTypes] = useState<EventType[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState("");

  // Draft state — separate from skill so Cancel doesn't mutate.
  const [identity, setIdentity] = useState<Identity>("patrol");
  const [triggerKind, setTriggerKind] = useState<TriggerKind>("schedule");
  const [eventMode, setEventMode] = useState<EventMode>("raw");
  const [schedule, setSchedule] = useState<string>(SCHEDULES[1]);
  const [target, setTarget]     = useState<string>(TARGETS[0]);
  const [source, setSource]     = useState<string>("");
  const [rawEvent, setRawEvent] = useState<string>("");
  const [gate, setGate]         = useState<string>(GATES[0]);
  const [outcome, setOutcome]   = useState<string>(OUTCOMES[0]);

  useEffect(() => { ensurePlexFont(); }, []);

  useEffect(() => {
    if (!slug) return;
    Promise.all([
      fetch(`/api/skills-v2/${encodeURIComponent(slug)}`).then(r => r.json()),
      fetch(`/api/skills-v2/alarm-sources?excludeSlug=${encodeURIComponent(slug)}`).then(r => r.json()),
      fetch(`/api/skills-v2/event-types`).then(r => r.json()),
    ]).then(([sEnv, srcEnv, evEnv]) => {
      const s = (sEnv?.data ?? sEnv) as Skill;
      setSkill(s);
      setSources((srcEnv?.data ?? srcEnv) as AlarmSource[]);
      setEventTypes((evEnv?.data ?? evEnv) as EventType[]);

      // Seed draft from existing automation, or sensible defaults.
      const ident: Identity = s.role === "datacheck" ? "datacheck" : "patrol";
      setIdentity(ident);
      const t = parseTrigger(s.trigger_config);
      if (t) {
        setTriggerKind(t.kind);
        if (t.kind === "schedule") {
          if (t.schedule) setSchedule(t.schedule);
          if (t.target)   setTarget(t.target);
        } else {
          // raw-event subscription uses `event`; alarm subscription uses `source`.
          if (t.event) { setEventMode("raw"); setRawEvent(t.event); }
          else if (t.source) { setEventMode("patrol"); setSource(t.source); }
        }
      }
      if (s.alarm_gate) setGate(s.alarm_gate);
      if (s.outcome)    setOutcome(ident === "datacheck" ? "data only" : s.outcome);
    }).catch(e => setLoadError(e instanceof Error ? e.message : String(e)));
  }, [slug]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  // ── handlers ─────────────────────────────────────────────────────────

  const cycle = useCallback(<T extends string>(list: readonly T[], cur: T): T => {
    const i = list.indexOf(cur);
    return list[(i + 1) % list.length];
  }, []);

  const buildTrigger = useCallback((): Trigger => {
    if (triggerKind === "schedule") return { kind: "schedule", schedule, target };
    if (eventMode === "raw") return { kind: "event", event: rawEvent || eventTypes[0]?.name || "" };
    return { kind: "event", source: source || sources[0]?.slug || "" };
  }, [triggerKind, eventMode, schedule, target, source, sources, rawEvent, eventTypes]);

  const handleDone = useCallback(async () => {
    if (!skill) return;
    const role: Role = identity;
    const trigger = buildTrigger();
    if (role === "patrol" && !skill.has_alarm) {
      setToast("pipeline 沒有 alarm 判斷式 — 請先回 Editor 加入判斷條件再重新編譯。");
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch(`/api/skills-v2/${encodeURIComponent(slug)}/automation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role,
          trigger,
          alarm_gate: role === "patrol" ? gate : null,
          outcome: role === "patrol" ? outcome : "data only",
        }),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || `HTTP ${res.status}`);
      }
      router.push("/skills");
    } catch (e) {
      setToast(`套用失敗：${e instanceof Error ? e.message : e}`);
    } finally {
      setSubmitting(false);
    }
  }, [buildTrigger, gate, identity, outcome, skill, slug, router]);

  const handleRemoveAutomation = useCallback(async () => {
    if (!skill) return;
    if (!confirm("確認將此 Skill 改回「工具」並清空 trigger / gate / outcome?")) return;
    setSubmitting(true);
    try {
      const res = await fetch(`/api/skills-v2/${encodeURIComponent(slug)}/automation`, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      router.push("/skills");
    } catch (e) {
      setToast(`移除失敗：${e instanceof Error ? e.message : e}`);
    } finally {
      setSubmitting(false);
    }
  }, [skill, slug, router]);

  const nodeCount = useMemo(() => skill ? parsePipelineNodes(skill.pipeline_nodes).length : 0, [skill]);

  if (loadError) return <Center>讀取失敗：{loadError}</Center>;
  if (!skill) return <Center>載入中...</Center>;

  return (
    <div style={{ background: TK.page, minHeight: "100vh", padding: "24px 24px 80px", fontFamily: FONT.sans, color: TK.ink }}>
      <div style={{ maxWidth: 900, margin: "0 auto" }}>
        <div style={{ marginBottom: 12 }}>
          <Link href="/skills" style={{ color: TK.body, fontSize: 13, textDecoration: "none" }}>
            ← Skills Library
          </Link>
        </div>

        {/* Header */}
        <Card>
          <div style={{
            font: `600 11px ${FONT.mono}`,
            letterSpacing: ".13em",
            color: TK.faint,
            textTransform: "uppercase",
            marginBottom: 6,
          }}>
            自動化設定 · 綁定 TRIGGER
          </div>
          <h1 style={{ font: `700 22px ${FONT.sans}`, color: TK.ink, margin: "0 0 4px" }}>{skill.name}</h1>
          <div style={{ fontSize: 13, color: TK.body }}>
            為 Skill 綁上自動化層；Skill 本身不變，可同時被多處引用。
          </div>
        </Card>

        {/* Identity */}
        <Section title="身分" subtitle="一顆 Skill 在被自動化的當下要扮演哪種身分。">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }} className="auto-cards">
            <IdentityCard
              role="patrol"
              active={identity === "patrol"}
              onClick={() => setIdentity("patrol")}
              title="Auto Patrol"
              note="會出 alarm，可被下游 event-driven 接、可接 action / workflow。"
            />
            <IdentityCard
              role="datacheck"
              active={identity === "datacheck"}
              onClick={() => setIdentity("datacheck")}
              title="Data Check"
              note="無 alarm，只彙整 / 呈現資料，終點。"
            />
          </div>
          <SystemCheck identity={identity} hasAlarm={skill.has_alarm} />
        </Section>

        {/* Trigger */}
        <Section title="TRIGGER" subtitle="什麼時候會自動跑這顆 Skill。">
          <Row label="類型">
            <Pill
              onClick={() => setTriggerKind(triggerKind === "schedule" ? "event" : "schedule")}
              color={TK.stripTrigger}
            >
              {triggerKind === "schedule" ? "排程時間到 ↔ 事件觸發" : "事件觸發 (Event-driven) ↔ 排程"}
            </Pill>
          </Row>
          {triggerKind === "schedule" ? (
            <>
              <Row label="排程">
                <BluePill onClick={() => setSchedule(cycle(SCHEDULES, schedule))}>{schedule}</BluePill>
              </Row>
              <Row label="對象">
                <BluePill onClick={() => setTarget(cycle(TARGETS, target))}>{target}</BluePill>
              </Row>
              <div style={{ fontSize: 12, color: TK.faint, marginTop: 6, fontStyle: "italic" }}>
                → 每 {schedule.replace("每 ", "")} 檢查 {target}
              </div>
            </>
          ) : (
            <>
              <Row label="事件種類">
                <Pill
                  onClick={() => setEventMode(eventMode === "raw" ? "patrol" : "raw")}
                  color={TK.stripTrigger}
                >
                  {eventMode === "raw" ? "原始事件 (Simulator) ↔ 上游 Patrol" : "上游 Auto Patrol ↔ 原始事件"}
                </Pill>
              </Row>
              {eventMode === "raw" ? (
                <>
                  <Row label="事件">
                    {eventTypes.length === 0 ? (
                      <span style={{ fontSize: 12, color: TK.faint }}>沒有可用的事件種類。</span>
                    ) : (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                        {eventTypes.map(e => (
                          <button key={e.name} onClick={() => setRawEvent(e.name)} title={e.description} style={{
                            font: `500 12.5px ${FONT.sans}`,
                            background: rawEvent === e.name ? TK.indigoTint : "#fff",
                            color: TK.ink,
                            border: `1.5px solid ${rawEvent === e.name ? TK.indigo : TK.divider}`,
                            padding: "7px 11px", borderRadius: 8, cursor: "pointer",
                            textAlign: "left", minWidth: 160, maxWidth: 280,
                          }}>
                            <div style={{ font: `600 12px ${FONT.mono}` }}>{e.name}</div>
                            <div style={{ fontSize: 11, color: TK.faint, marginTop: 2,
                                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {e.description}
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                  </Row>
                  <div style={{ fontSize: 12, color: TK.faint, marginTop: 6 }}>
                    Simulator 發出該事件時即觸發此 Skill（例：OOC = SPC 超管制界限）。
                  </div>
                </>
              ) : (
                <>
                  <Row label="來源">
                    {sources.length === 0 ? (
                      <span style={{ fontSize: 12, color: TK.faint }}>
                        目前沒有可用的上游 Auto Patrol（需要至少一顆 role=patrol、含 alarm 的 skill）。
                      </span>
                    ) : (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                        {sources.map(s => (
                          <button key={s.slug} onClick={() => setSource(s.slug)} style={{
                            font: `500 12.5px ${FONT.sans}`,
                            background: source === s.slug ? TK.indigoTint : "#fff",
                            color: TK.ink,
                            border: `1.5px solid ${source === s.slug ? TK.indigo : TK.divider}`,
                            padding: "7px 11px", borderRadius: 8, cursor: "pointer",
                            textAlign: "left", minWidth: 180,
                          }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                              <span style={{ fontWeight: 600 }}>{s.name}</span>
                              <span style={{
                                font: `600 10px ${FONT.mono}`,
                                color: TK.patrol, background: TK.patrolTint,
                                padding: "2px 6px", borderRadius: 4,
                              }}>alarm</span>
                            </div>
                            <div style={{ fontSize: 11, color: TK.faint, marginTop: 2 }}>{s.sub}</div>
                          </button>
                        ))}
                      </div>
                    )}
                  </Row>
                  <div style={{ fontSize: 12, color: TK.faint, marginTop: 6 }}>
                    接一個上游 Auto Patrol 的 alarm。
                  </div>
                </>
              )}
            </>
          )}
        </Section>

        {/* Alarm Gate (patrol only) */}
        {identity === "patrol" && (
          <Section title="ALARM GATE" subtitle="checklist 跑完依此條件決定是否告警。">
            <Row label="條件">
              <Pill onClick={() => setGate(cycle(GATES, gate))} color={TK.stripAlarmGate}>{gate}</Pill>
            </Row>
            <div style={{ fontSize: 12, color: TK.faint, marginTop: 4 }}>
              由你設定 · 系統檢查
            </div>
          </Section>
        )}

        {/* Outcome */}
        <Section title="OUTCOME" subtitle="觸發後的最終結果。">
          {identity === "datacheck" ? (
            <Row label="結果">
              <Pill color={TK.stripOutcome} disabled>data only</Pill>
              <span style={{ fontSize: 12, color: TK.faint, marginLeft: 12 }}>
                Data Check 不可串接下游。
              </span>
            </Row>
          ) : (
            <Row label="結果">
              <Pill onClick={() => setOutcome(cycle(OUTCOMES, outcome))} color={TK.stripOutcome}>{outcome}</Pill>
            </Row>
          )}
        </Section>

        {/* Composite strip */}
        <CompositeStrip
          trigger={triggerKind === "schedule"
            ? `${schedule} · ${target}`
            : eventMode === "raw"
              ? `event ${rawEvent || eventTypes[0]?.name || "(選一個事件)"}`
              : `on ${source || sources[0]?.name || "(選一個來源)"}`}
          checklist={`${skill.name} · ${nodeCount} steps`}
          gate={identity === "patrol" ? gate : "— 無"}
          outcome={identity === "patrol" ? outcome : "data only"}
        />

        {/* Footer */}
        <div style={{
          marginTop: 18, display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap",
        }}>
          <button onClick={handleRemoveAutomation} disabled={submitting || skill.role === "tool"} style={{
            font: `600 12.5px ${FONT.sans}`,
            color: TK.body, background: "transparent",
            border: `1px solid ${TK.divider}`,
            padding: "9px 14px", borderRadius: 9,
            cursor: skill.role === "tool" ? "not-allowed" : "pointer",
            opacity: skill.role === "tool" ? 0.5 : 1,
          }}>
            取消自動化 · 維持工具
          </button>
          <button onClick={handleDone} disabled={submitting} style={{
            font: `600 13px ${FONT.sans}`,
            color: "#fff", background: TK.black, border: `1px solid ${TK.black}`,
            padding: "9px 18px", borderRadius: 9, cursor: "pointer",
          }}>
            {submitting ? "Saving…" : "Done · 啟動"}
          </button>
        </div>
      </div>

      {toast && <Toast text={toast} />}

      <style>{`
        @media (max-width: 700px) {
          .auto-cards { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

// ── Small components ────────────────────────────────────────────────────────

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      background: TK.card, borderRadius: 14,
      boxShadow: "0 1px 3px rgba(15,18,30,.06)",
      padding: "18px 22px", marginBottom: 14,
    }}>{children}</div>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <Card>
      <div style={{
        font: `600 11px ${FONT.mono}`, letterSpacing: ".13em",
        color: TK.faint, textTransform: "uppercase", marginBottom: 4,
      }}>{title}</div>
      <div style={{ fontSize: 12.5, color: TK.body, marginBottom: 12 }}>{subtitle}</div>
      {children}
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 8, flexWrap: "wrap" }}>
      <span style={{
        font: `500 12px ${FONT.mono}`, color: TK.body,
        minWidth: 64, paddingTop: 6,
      }}>{label}</span>
      <div style={{ flex: 1, minWidth: 200 }}>{children}</div>
    </div>
  );
}

function Pill({ children, onClick, color, disabled }: {
  children: React.ReactNode; onClick?: () => void; color: string; disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        font: `600 12.5px ${FONT.sans}`,
        color, background: "#fff", border: `1.5px solid ${color}`,
        padding: "6px 14px", borderRadius: 8,
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.7 : 1,
      }}
    >{children}</button>
  );
}

function BluePill({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      font: `600 12.5px ${FONT.sans}`,
      color: TK.pillBlue, background: TK.pillBlueBg, border: `1.5px solid ${TK.pillBlueBorder}`,
      padding: "6px 14px", borderRadius: 8, cursor: "pointer",
    }}>{children}</button>
  );
}

function IdentityCard({
  role, active, onClick, title, note,
}: {
  role: Identity;
  active: boolean;
  onClick: () => void;
  title: string;
  note: string;
}) {
  const c = ROLE_COLORS[role];
  return (
    <button onClick={onClick} style={{
      textAlign: "left",
      background: active ? c.tint : "#fff",
      border: `1.5px solid ${active ? c.color : TK.divider}`,
      borderRadius: 11, padding: "14px 16px",
      cursor: "pointer",
      font: FONT.sans,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span style={{ width: 9, height: 9, borderRadius: 5, background: c.color }} />
        <span style={{ font: `700 14.5px ${FONT.sans}`, color: TK.ink }}>{title}</span>
      </div>
      <div style={{ fontSize: 12.5, color: TK.body, lineHeight: 1.5 }}>{note}</div>
    </button>
  );
}

function SystemCheck({ identity, hasAlarm }: { identity: Identity; hasAlarm: boolean }) {
  if (identity === "datacheck") {
    return (
      <div style={{
        marginTop: 12, padding: "9px 12px", borderRadius: 8,
        background: TK.toolTint, color: TK.body,
        font: `500 12px ${FONT.sans}`,
        border: `1px solid ${TK.toolBorder}`,
      }}>
        ℹ Data Check 不需要 alarm — pipeline 是否含 verdict 不影響此身分。
      </div>
    );
  }
  if (hasAlarm) {
    return (
      <div style={{
        marginTop: 12, padding: "9px 12px", borderRadius: 8,
        background: "#e6f6f0", color: "#0b7a55",
        font: `500 12px ${FONT.sans}`,
        border: "1px solid #c5e7d3",
      }}>
        ✓ pipeline 含 alarm，適合 Auto Patrol
      </div>
    );
  }
  return (
    <div style={{
      marginTop: 12, padding: "9px 12px", borderRadius: 8,
      background: TK.patrolTint, color: TK.patrolDeep,
      font: `500 12px ${FONT.sans}`,
      border: `1px solid ${TK.patrolBorder}`,
    }}>
      ⚠ pipeline 目前無 alarm 判斷式，需先在 Skill 加入條件
    </div>
  );
}

function CompositeStrip({
  trigger, checklist, gate, outcome,
}: {
  trigger: string; checklist: string; gate: string; outcome: string;
}) {
  return (
    <Card>
      <div style={{
        font: `600 11px ${FONT.mono}`, letterSpacing: ".13em",
        color: TK.faint, textTransform: "uppercase", marginBottom: 10,
      }}>
        COMPOSITE
      </div>
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        flexWrap: "wrap",
      }}>
        <StripNode color={TK.stripTrigger} label="TRIGGER" value={trigger} />
        <Arrow />
        <StripNode color={TK.stripChecklist} label="CHECKLIST" value={checklist} />
        <Arrow />
        <StripNode color={TK.stripAlarmGate} label="ALARM GATE" value={gate} />
        <Arrow />
        <StripNode color={TK.stripOutcome} label="OUTCOME" value={outcome} />
      </div>
    </Card>
  );
}

function StripNode({ color, label, value }: { color: string; label: string; value: string }) {
  return (
    <div style={{
      flex: "1 1 180px", minWidth: 0,
      display: "flex", alignItems: "center", gap: 8,
      padding: "9px 12px", borderRadius: 8,
      background: "#fbfbfc", border: `1px solid ${TK.divider}`,
    }}>
      <span style={{ width: 8, height: 8, borderRadius: 4, background: color, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ font: `600 10px ${FONT.mono}`, color: TK.faint, letterSpacing: ".1em" }}>{label}</div>
        <div style={{ font: `500 12px ${FONT.sans}`, color: TK.ink,
                       overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {value}
        </div>
      </div>
    </div>
  );
}

function Arrow() {
  return <span style={{ color: TK.faint, fontSize: 14, lineHeight: 1 }}>→</span>;
}

function Center({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ background: TK.page, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: FONT.sans }}>
      <div style={{ background: "#fff", padding: "24px 30px", borderRadius: 12, color: TK.body }}>{children}</div>
    </div>
  );
}

function Toast({ text }: { text: string }) {
  return (
    <div style={{
      position: "fixed", bottom: 28, left: "50%", transform: "translateX(-50%)",
      background: TK.black, color: "#fff",
      padding: "9px 16px", borderRadius: 9,
      fontSize: 13, boxShadow: "0 8px 24px rgba(0,0,0,.25)",
      zIndex: 60, maxWidth: 480,
      fontFamily: FONT.sans,
    }}>{text}</div>
  );
}
