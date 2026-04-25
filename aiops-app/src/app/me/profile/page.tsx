"use client";

import { useEffect, useState } from "react";

interface MeProfile {
  id: number;
  username: string;
  email: string;
  display_name: string;
  roles: string[];
  oidc_provider: string | null;
}

export default function ProfilePage() {
  const [me, setMe] = useState<MeProfile | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch("/api/me/profile", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = await res.json();
        const profile: MeProfile = body.data ?? body;
        setMe(profile);
        setDisplayName(profile.display_name ?? profile.username);
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, []);

  async function save() {
    setSaving(true); setError(null); setSuccess(null);
    try {
      const res = await fetch("/api/me/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ displayName }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 160));
      }
      const body = await res.json();
      const updated = body.data ?? body;
      setMe((prev) => prev ? { ...prev, display_name: updated.display_name } : prev);
      setSuccess("已更新");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!me && !error) return <div style={{ padding: 24, color: "#94a3b8" }}>載入中…</div>;

  return (
    <div style={{ padding: 24, maxWidth: 640, fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: "#0f172a" }}>⚙️ 帳號設定</h1>
      <p style={{ fontSize: 13, color: "#64748b", marginTop: 4, marginBottom: 20 }}>
        使用者基本資料。username + email 不可變更（涉及登入與 IdP 對應）。如需調整請聯繫 IT_ADMIN。
      </p>

      {error && <Msg kind="error" text={error} />}
      {success && <Msg kind="success" text={success} />}

      {me && (
        <div style={cardStyle}>
          <Field label="Username（登入 ID）">
            <input value={me.username} readOnly style={inputStyle} />
          </Field>
          <Field label="Email（OIDC 對應用）">
            <input value={me.email} readOnly style={inputStyle} />
          </Field>
          <Field label="Display Name（顯示名稱，可改）">
            <input value={displayName} onChange={e => setDisplayName(e.target.value)} style={inputStyle} />
          </Field>
          <Field label="角色">
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {me.roles.map(r => (
                <span key={r} style={rolePill(r)}>{r}</span>
              ))}
            </div>
          </Field>
          <Field label="登入方式">
            <span style={{ fontSize: 13, color: "#475569" }}>
              {me.oidc_provider ?? "local (username + password)"}
            </span>
          </Field>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
            <button
              onClick={save}
              disabled={saving || displayName === me.display_name}
              style={{
                padding: "8px 18px", fontSize: 13, fontWeight: 600, borderRadius: 6,
                background: displayName === me.display_name ? "#cbd5e0" : "#1f2937",
                color: "#fff", border: "none",
                cursor: saving || displayName === me.display_name ? "not-allowed" : "pointer",
              }}
            >
              {saving ? "儲存中…" : "儲存變更"}
            </button>
          </div>
        </div>
      )}
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

function Msg({ kind, text }: { kind: "error" | "success"; text: string }) {
  const colors = kind === "error"
    ? { bg: "#fef2f2", color: "#991b1b", border: "#fca5a5" }
    : { bg: "#dcfce7", color: "#166534", border: "#86efac" };
  return (
    <div style={{
      padding: "8px 12px", borderRadius: 6, fontSize: 13, marginBottom: 12,
      background: colors.bg, color: colors.color, border: `1px solid ${colors.border}`,
    }}>{text}</div>
  );
}

function rolePill(r: string): React.CSSProperties {
  const colors: Record<string, { bg: string; color: string }> = {
    IT_ADMIN: { bg: "#fef2f2", color: "#991b1b" },
    PE: { bg: "#eff6ff", color: "#1e40af" },
    ON_DUTY: { bg: "#f0fdf4", color: "#166534" },
  };
  const c = colors[r] ?? { bg: "#f1f5f9", color: "#475569" };
  return { padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600, background: c.bg, color: c.color };
}

const inputStyle: React.CSSProperties = {
  padding: "7px 10px", border: "1px solid #cbd5e0", borderRadius: 6,
  fontSize: 13, color: "#2d3748", background: "#fff", width: "100%", boxSizing: "border-box",
};
const cardStyle: React.CSSProperties = {
  background: "#fff", border: "1px solid #e5e7eb", borderRadius: 8,
  padding: 18,
};
