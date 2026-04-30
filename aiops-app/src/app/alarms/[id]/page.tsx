"use client";

/**
 * Alarm drill-down page. Triggered from the cluster detail view's
 * "進入深度診斷 →" link on each alarm row. Reuses the legacy
 * AlarmDetail (AI synthesis + Trigger / Evidence tabs + multi-run
 * auto_check cards + DR accordions) without the surrounding
 * cockpit shell so the user gets a focused full-page report.
 */

import "@/styles/alarm-center.css";
import Link from "next/link";
import { use, useEffect, useState } from "react";
import { AlarmDetail, type Alarm } from "@/components/alarms/AlarmDetailLegacy";

const FONT_LINK = "https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap";

export default function AlarmDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [alarm, setAlarm] = useState<Alarm | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const linkId = "alarm-center-fonts";
    if (!document.getElementById(linkId)) {
      const link = document.createElement("link");
      link.id = linkId;
      link.rel = "stylesheet";
      link.href = FONT_LINK;
      document.head.appendChild(link);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/admin/alarms/${id}`)
      .then(async r => {
        if (!r.ok) { setError(`HTTP ${r.status}`); setAlarm(null); return; }
        const d = await r.json();
        setAlarm(d?.data ?? d ?? null);
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [id]);

  return (
    <div className="alarm-center" style={{ display: "block", height: "auto", padding: "18px 28px" }}>
      <div style={{ marginBottom: 14 }}>
        <Link href="/alarms" style={{ fontSize: 12, color: "var(--accent)", fontWeight: 600, textDecoration: "none", fontFamily: "var(--font-mono)" }}>
          ← 返回 cluster 視圖
        </Link>
      </div>
      {loading && <div style={{ color: "var(--text-3)", fontSize: 13 }}>載入中…</div>}
      {error && <div style={{ color: "var(--high)", fontSize: 13 }}>載入失敗: {error}</div>}
      {alarm && (
        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: 22 }}>
          <AlarmDetail alarm={alarm} />
        </div>
      )}
    </div>
  );
}
