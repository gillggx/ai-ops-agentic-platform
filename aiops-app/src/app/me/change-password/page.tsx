"use client";

import { useEffect, useState } from "react";

export default function ChangePasswordPage() {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [provider, setProvider] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch("/api/me/profile", { cache: "no-store" });
        const body = await res.json();
        const me = body.data ?? body;
        setProvider(me.oidc_provider ?? null);
      } catch {
        setProvider(null);
      }
    })();
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null); setSuccess(false);
    if (newPassword.length < 6) { setError("新密碼長度至少 6 字元"); return; }
    if (newPassword !== confirm) { setError("新密碼與確認不相符"); return; }
    setSubmitting(true);
    try {
      const res = await fetch("/api/me/password", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        // Java Jackson SNAKE_CASE → send snake_case keys
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error?.message ?? body.message ?? `HTTP ${res.status}`);
      }
      setSuccess(true);
      setOldPassword(""); setNewPassword(""); setConfirm("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  const isOidc = provider != null && provider !== "";

  return (
    <div style={{ padding: 24, maxWidth: 540, fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: "#0f172a" }}>🔑 變更密碼</h1>
      <p style={{ fontSize: 13, color: "#64748b", marginTop: 4, marginBottom: 20 }}>
        只適用於本地帳號（username + password）。OIDC 登入使用者請到該識別提供者變更密碼。
      </p>

      {isOidc && (
        <div style={{
          padding: "12px 14px", borderRadius: 6, fontSize: 13, marginBottom: 16,
          background: "#fef3c7", color: "#92400e", border: "1px solid #fde68a",
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>您用 <code>{provider}</code> 登入</div>
          此頁不適用 — 請到 {provider} 管理頁變更密碼。
        </div>
      )}

      {error && (
        <div style={msgErr}>{error}</div>
      )}
      {success && (
        <div style={msgOk}>已更新密碼。</div>
      )}

      <form onSubmit={submit} style={cardStyle}>
        <Field label="目前密碼">
          <input
            type="password"
            value={oldPassword}
            onChange={e => setOldPassword(e.target.value)}
            disabled={isOidc}
            autoComplete="current-password"
            style={inputStyle}
            required
          />
        </Field>
        <Field label="新密碼（至少 6 字元）">
          <input
            type="password"
            value={newPassword}
            onChange={e => setNewPassword(e.target.value)}
            disabled={isOidc}
            autoComplete="new-password"
            style={inputStyle}
            required
            minLength={6}
          />
        </Field>
        <Field label="再次輸入新密碼">
          <input
            type="password"
            value={confirm}
            onChange={e => setConfirm(e.target.value)}
            disabled={isOidc}
            autoComplete="new-password"
            style={inputStyle}
            required
          />
        </Field>
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 6 }}>
          <button
            type="submit"
            disabled={submitting || isOidc}
            style={{
              padding: "8px 18px", fontSize: 13, fontWeight: 600, borderRadius: 6,
              background: submitting || isOidc ? "#cbd5e0" : "#1f2937",
              color: "#fff", border: "none",
              cursor: submitting || isOidc ? "not-allowed" : "pointer",
            }}
          >
            {submitting ? "變更中…" : "變更密碼"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 12 }}>
      <label style={{ fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase" }}>
        {label}
      </label>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "7px 10px", border: "1px solid #cbd5e0", borderRadius: 6,
  fontSize: 13, color: "#2d3748", background: "#fff", width: "100%", boxSizing: "border-box",
};
const cardStyle: React.CSSProperties = {
  background: "#fff", border: "1px solid #e5e7eb", borderRadius: 8,
  padding: 18,
};
const msgErr: React.CSSProperties = {
  padding: "8px 12px", borderRadius: 6, fontSize: 13, marginBottom: 12,
  background: "#fef2f2", color: "#991b1b", border: "1px solid #fca5a5",
};
const msgOk: React.CSSProperties = {
  padding: "8px 12px", borderRadius: 6, fontSize: 13, marginBottom: 12,
  background: "#dcfce7", color: "#166534", border: "1px solid #86efac",
};
