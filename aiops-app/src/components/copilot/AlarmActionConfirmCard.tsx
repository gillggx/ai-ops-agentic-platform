"use client";

/**
 * AlarmActionConfirmCard (Alarm 處理能力包, 2026-07-10).
 *
 * The agent's ack/dispose/resolve tools emit this card instead of writing:
 * the browser performs the POST under the user's own JWT only on 確認 —
 * same write-confirm model as SkillActivateConfirmCard. Role gates
 * (resolve = ADMIN/PE) therefore apply as the signed-in user.
 */
import { useState } from "react";

export interface AlarmActionData {
  action: "ack_alarm" | "dispose_alarm" | "resolve_alarm";
  alarm_id?: number | null;
  equipment_id?: string | null;
  disposition?: string | null;
  reason?: string | null;
  /** 跨裝置一致 (2026-07-12)：處理結果隨 rich history 同步，別台裝置不能再按。 */
  resolved?: "done" | "cancelled";
}

const ACTION_LABEL: Record<AlarmActionData["action"], string> = {
  ack_alarm: "認領告警",
  dispose_alarm: "處置告警",
  resolve_alarm: "結案告警",
};

export function AlarmActionConfirmCard({ data, onResolved }: {
  data: AlarmActionData;
  onResolved?: (state: "done" | "cancelled") => void;
}) {
  const [reason, setReason] = useState(data.reason ?? "");
  const [state, setState] = useState<"idle" | "working" | "done" | "cancelled" | "error">(data.resolved ?? "idle");
  const [msg, setMsg] = useState("");

  const target = data.alarm_id
    ? `Alarm #${data.alarm_id}`
    : data.equipment_id
      ? `${data.equipment_id}（整台機台 cluster）`
      : "—";

  const confirm = async () => {
    setState("working"); setMsg("");
    try {
      let res: Response;
      if (data.action === "ack_alarm" && !data.alarm_id && data.equipment_id) {
        res = await fetch("/api/admin/alarms/cluster-ack", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ equipment_id: data.equipment_id }),
        });
      } else if (data.action === "ack_alarm") {
        res = await fetch(`/api/admin/alarms/${data.alarm_id}/ack`, { method: "POST" });
      } else if (data.action === "dispose_alarm") {
        res = await fetch(`/api/admin/alarms/${data.alarm_id}/dispose`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ disposition: data.disposition, reason }),
        });
      } else {
        res = await fetch(`/api/admin/alarms/${data.alarm_id}/resolve`, { method: "POST" });
      }
      if (!res.ok) {
        const env = await res.json().catch(() => ({}));
        throw new Error(env?.error?.message || `HTTP ${res.status}${res.status === 403 ? "（權限不足）" : ""}`);
      }
      setState("done");
      onResolved?.("done");
    } catch (e) {
      setState("error");
      setMsg(e instanceof Error ? e.message : "失敗");
    }
  };

  if (state === "done") {
    return (
      <div style={box}>
        <div style={{ padding: "11px 15px", fontSize: 12.5, color: "#166534", background: "#f0fdf4" }}>
          已完成：{ACTION_LABEL[data.action]} — {target}
          {data.action === "dispose_alarm" && data.disposition ? `（${data.disposition}）` : ""}
        </div>
      </div>
    );
  }
  if (state === "cancelled") {
    return <div style={box}><div style={{ padding: "10px 15px", fontSize: 12, color: "#94a3b8" }}>已取消。</div></div>;
  }

  const isDispose = data.action === "dispose_alarm";
  return (
    <div style={box}>
      <div style={{ padding: "11px 15px", borderBottom: "1px solid #EEF2F6", background: "var(--pn, #F8FAFC)" }}>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>{ACTION_LABEL[data.action]} — 需要你確認</div>
        <div style={{ fontSize: 11.5, color: "#64748B", marginTop: 2 }}>
          以你的帳號執行{data.action === "resolve_alarm" ? "（需 ADMIN / PE 權限）" : ""}；按確認才會生效。
        </div>
      </div>
      <div style={{ padding: "12px 15px", fontSize: 12.5, color: "#334155", display: "flex", flexDirection: "column", gap: 8 }}>
        <div>對象：<b>{target}</b></div>
        {isDispose && (
          <>
            <div>處置：<b style={{ color: data.disposition === "scrap" ? "#b91c1c" : "inherit" }}>
              {data.disposition}</b>{data.disposition === "scrap" ? "（不可逆）" : ""}</div>
            <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 11, fontWeight: 600, color: "#64748B" }}>
              原因（會寫入記錄）
              <input value={reason} onChange={(e) => setReason(e.target.value)}
                style={{ fontSize: 12.5, padding: "6px 9px", borderRadius: 6, border: "1px solid #E2E8F0", outline: "none", color: "#0f172a" }} />
            </label>
          </>
        )}
      </div>
      {msg && <div style={{ padding: "0 15px 8px", fontSize: 12, color: "#B91C1C" }}>{msg}</div>}
      <div style={{ padding: "10px 15px", borderTop: "1px solid #EEF2F6", display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button onClick={() => { setState("cancelled"); onResolved?.("cancelled"); }} disabled={state === "working"}
          style={{ fontSize: 12.5, padding: "7px 14px", borderRadius: 8, border: "1px solid #E2E8F0",
            background: "#fff", color: "#475569", cursor: "pointer" }}>取消</button>
        <button onClick={confirm} disabled={state === "working" || (isDispose && !reason.trim())}
          style={{ fontSize: 12.5, padding: "7px 16px", borderRadius: 8, border: "none",
            background: "var(--p, #2b6cb0)", color: "#fff", fontWeight: 700, cursor: "pointer",
            opacity: isDispose && !reason.trim() ? 0.5 : 1 }}>
          {state === "working" ? "執行中…" : "確認執行"}
        </button>
      </div>
    </div>
  );
}

const box: React.CSSProperties = {
  maxWidth: 420, border: "1px solid #E2E8F0", borderRadius: 12,
  overflow: "hidden", background: "#fff",
};
