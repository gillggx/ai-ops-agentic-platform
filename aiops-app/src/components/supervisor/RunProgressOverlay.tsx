"use client";

/** 巡檢進行中的阻擋式進度罩（2026-07-06）。
 *
 *  page 層渲染 — 蓋住整個工作台，擋掉簽核/再觸發，直到 run 結束。
 *  自己輪詢 status（跑批中 2s、閒置 6s），所以「任何 admin 開工作台若有
 *  run 在跑就看到同一個罩」（feature C）。running→false 時呼叫 onDone
 *  讓頁面 reload 提案。進度以「共 N 筆、檢查到第 X 筆」為主軸。
 *
 *  startSignal：RunTrigger 觸發成功後遞增，讓罩立刻樂觀顯示（不必等下次輪詢）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { TOK } from "./model";

interface Progress {
  stage?: string;
  scanned?: number; scan_total?: number;
  checked?: number; check_total?: number;
  block?: string; proposed?: number;
}
interface Status {
  running: boolean;
  kind?: string;
  started_at?: string;
  progress?: Progress | null;
  last?: { ok?: boolean; summary?: string } | null;
}

export function RunProgressOverlay({ startSignal, onDone }: {
  startSignal: number;
  onDone: () => void;
}) {
  const t = useTranslations("sup");
  const [status, setStatus] = useState<Status | null>(null);
  const [optimistic, setOptimistic] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wasRunningRef = useRef(false);

  const fetchStatus = useCallback(async (): Promise<boolean> => {
    try {
      const r = await fetch("/api/supervisor/runs/status", { cache: "no-store" });
      const j = await r.json();
      const st: Status = j.data ?? j;
      setStatus(st);
      if (st.running) setOptimistic(false);
      // running → not running edge: reload the page's proposals
      if (wasRunningRef.current && !st.running) onDone();
      wasRunningRef.current = st.running;
      return st.running;
    } catch { return false; }
  }, [onDone]);

  // adaptive poll loop
  const schedule = useCallback((running: boolean) => {
    if (pollRef.current) clearTimeout(pollRef.current);
    pollRef.current = setTimeout(async () => {
      const r = await fetchStatus();
      schedule(r);
    }, running || optimistic ? 2000 : 6000);
  }, [fetchStatus, optimistic]);

  useEffect(() => {
    void fetchStatus().then((r) => schedule(r));
    return () => { if (pollRef.current) clearTimeout(pollRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // RunTrigger fired — show immediately + poll fast
  useEffect(() => {
    if (startSignal > 0) {
      setOptimistic(true);
      void fetchStatus();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startSignal]);

  const showing = optimistic || status?.running === true;

  // elapsed timer while showing
  useEffect(() => {
    if (showing) {
      const started = status?.started_at ? Date.parse(status.started_at) : Date.now();
      const tick = () => setElapsed(Math.max(0, Math.round((Date.now() - started) / 1000)));
      tick();
      timerRef.current = setInterval(tick, 1000);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [showing, status?.started_at]);

  if (!showing) return null;

  const p = status?.progress ?? {};
  const stage = p.stage ?? "starting";
  // 主軸數字：掃描階段用 scanned/scan_total；取證階段用 checked/check_total
  const cur = stage === "checking" ? p.checked : p.scanned;
  const total = stage === "checking" ? p.check_total : p.scan_total;
  const hasCounter = typeof cur === "number" && typeof total === "number" && total > 0;
  const pct = hasCounter ? Math.min(100, Math.round((cur! / total!) * 100)) : null;

  const stageLabel = t(`progress.stage.${["scanning", "aggregating", "checking", "finalizing", "done"].includes(stage) ? stage : "starting"}` as Parameters<typeof t>[0]);

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 200,
      background: "rgba(33,31,28,.42)", backdropFilter: "blur(1.5px)",
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{
        background: TOK.paper, border: `1px solid ${TOK.border}`, borderRadius: 14,
        boxShadow: "0 12px 40px rgba(33,31,28,.28)", padding: "26px 30px",
        width: 440, maxWidth: "90vw",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <span style={{
            width: 14, height: 14, borderRadius: "50%", flex: "none",
            border: `2px solid ${TOK.ink}`, borderTopColor: "transparent",
            animation: "supspin .8s linear infinite",
          }} />
          <span style={{ fontSize: 15, fontWeight: 800 }}>
            {t(status?.kind === "curation" ? "progress.titleCuration" : "progress.titleForensics")}
          </span>
          <span style={{ flex: 1 }} />
          <span style={{ font: `600 12px ${TOK.mono}`, color: TOK.muted }}>{elapsed}s</span>
        </div>
        <div style={{ fontSize: 12, color: TOK.muted, marginBottom: 16 }}>{stageLabel}</div>

        {/* 主軸：共 N 筆、檢查到第 X 筆 */}
        {hasCounter ? (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
              <span style={{ font: `800 26px ${TOK.mono}`, color: TOK.ink }}>{cur}</span>
              <span style={{ fontSize: 13, color: TOK.muted }}>
                {t("progress.ofTotal", { total: total! })}
              </span>
            </div>
            <div style={{ height: 7, borderRadius: 4, background: "#e7e3d9", overflow: "hidden" }}>
              <div style={{ width: `${pct}%`, height: "100%", background: TOK.ink, transition: "width .4s ease" }} />
            </div>
          </>
        ) : (
          <div style={{ fontSize: 13, color: TOK.muted }}>{t("progress.preparing")}</div>
        )}

        {/* 已提件數 running tally */}
        <div style={{ display: "flex", gap: 16, marginTop: 16, fontSize: 11.5, color: TOK.muted }}>
          {typeof p.proposed === "number" && (
            <span>{t("progress.proposed", { n: p.proposed })}</span>
          )}
          {p.block && stage === "checking" && (
            <span style={{ fontFamily: TOK.mono }}>▣ {p.block}</span>
          )}
        </div>

        <div style={{ marginTop: 18, paddingTop: 14, borderTop: `1px solid ${TOK.borderSub}`,
                      fontSize: 11, color: TOK.faint, lineHeight: 1.6 }}>
          {t("progress.blockingNote")}
        </div>
      </div>
      <style>{`@keyframes supspin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
