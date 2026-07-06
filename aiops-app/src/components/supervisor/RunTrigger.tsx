"use client";

/** 手動觸發 Supervisor 巡檢（IT_ADMIN only）。
 *
 *  kind 下拉（查案 forensics / 策展 curation）+「先清除未審核」checkbox +
 *  立即巡檢鈕。觸發後輪詢 status（5s）直到 running=false，完成時回呼
 *  onFinished 讓頁面 reload 提案。單飛由後端保證（409 → 顯示進行中）。
 */

import { useState } from "react";
import { useTranslations } from "next-intl";
import { TOK } from "./model";

export function RunTrigger({ onStarted }: { onStarted: () => void }) {
  const t = useTranslations("sup");
  const [kind, setKind] = useState<"forensics" | "curation">("forensics");
  const [clearPending, setClearPending] = useState(false);
  const [days, setDays] = useState(7);
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const trigger = async () => {
    setNote(null);
    setRunning(true);
    try {
      const r = await fetch("/api/supervisor/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, days, clear_pending: clearPending }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.status === 409 || j?.data?.running === true) {
        setNote(t("runs.alreadyRunning"));
        onStarted();   // overlay 會顯示現有 run
        setRunning(false);
        return;
      }
      if (!r.ok) {
        setRunning(false);
        setNote(t("runs.failed", { msg: `HTTP ${r.status}` }));
        return;
      }
      const cleared = Number(j?.data?.cleared ?? 0);
      if (cleared > 0) setNote(t("runs.cleared", { n: cleared }));
      setRunning(false);
      onStarted();   // 交棒給阻擋式進度罩
    } catch (e) {
      setRunning(false);
      setNote(t("runs.failed", { msg: String((e as Error).message || e) }));
    }
  };

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      <select
        value={kind}
        onChange={(e) => setKind(e.target.value as "forensics" | "curation")}
        disabled={running}
        style={{
          border: `1px solid ${TOK.btnBorder}`, borderRadius: 6, padding: "5px 8px",
          fontSize: 11.5, background: "#fff", color: TOK.ink, fontFamily: "inherit",
        }}
      >
        <option value="forensics">{t("runs.kindForensics")}</option>
        <option value="curation">{t("runs.kindCuration")}</option>
      </select>
      <select
        value={days}
        onChange={(e) => setDays(Number(e.target.value))}
        disabled={running}
        title={t("runs.daysTip")}
        style={{
          border: `1px solid ${TOK.btnBorder}`, borderRadius: 6, padding: "5px 8px",
          fontSize: 11.5, background: "#fff", color: TOK.ink, fontFamily: "inherit",
        }}
      >
        {[1, 3, 7, 14].map((d) => (
          <option key={d} value={d}>{t("runs.daysOpt", { d })}</option>
        ))}
      </select>
      <label style={{ display: "flex", gap: 5, alignItems: "center", fontSize: 11.5, color: TOK.muted, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={clearPending}
          onChange={(e) => setClearPending(e.target.checked)}
          disabled={running}
        />
        {t("runs.clearPending")}
      </label>
      <button
        onClick={() => void trigger()}
        disabled={running}
        style={{
          background: running ? "#f1f5f9" : TOK.ink,
          color: running ? TOK.muted : TOK.paper,
          border: "none", borderRadius: 7, padding: "6px 16px",
          fontSize: 12, fontWeight: 700, cursor: running ? "default" : "pointer",
          fontFamily: "inherit",
        }}
      >{running ? t("runs.running") : t("runs.trigger")}</button>
      {note && <span style={{ fontSize: 11, color: TOK.muted, maxWidth: 420 }}>{note}</span>}
    </div>
  );
}
