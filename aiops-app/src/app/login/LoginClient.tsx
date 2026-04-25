"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";

const PROVIDER_STYLES: Record<string, { emoji: string; bg: string; color: string; label: string }> = {
  "microsoft-entra-id": { emoji: "🪟", bg: "#0078d4", color: "#fff", label: "使用 Microsoft 登入" },
  google:                { emoji: "🔴", bg: "#fff",    color: "#1f2937", label: "使用 Google 登入" },
  keycloak:              { emoji: "🔑", bg: "#3c5fcc", color: "#fff", label: "使用 Keycloak 登入" },
  okta:                  { emoji: "🅾️", bg: "#007dc1", color: "#fff", label: "使用 Okta 登入" },
};

export default function LoginClient({
  providers,
  error,
  callbackUrl,
}: {
  providers: { id: string; label: string }[];
  error: string | null;
  callbackUrl: string;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const oidcProviders = providers.filter((p) => p.id !== "credentials");
  const hasCredentials = providers.some((p) => p.id === "credentials");

  async function handleLocalSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setSubmitting(true);
    setLocalError(null);
    try {
      const res = await signIn("credentials", {
        username,
        password,
        redirect: false,
        callbackUrl,
      });
      if (res?.error) {
        setLocalError("登入失敗：帳號或密碼錯誤");
      } else if (res?.ok) {
        window.location.href = callbackUrl;
      }
    } catch (err) {
      setLocalError(`連線失敗：${(err as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={pageStyle}>
      <div style={cardStyle}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: "#0F172A", margin: 0, marginBottom: 4 }}>
          AIOps Platform
        </h1>
        <p style={{ fontSize: 13, color: "#64748B", marginBottom: 24 }}>
          請選擇登入方式
        </p>

        {error && (
          <div style={errorStyle}>
            登入失敗：{error}
          </div>
        )}

        {/* OIDC provider buttons */}
        {oidcProviders.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 20 }}>
            {oidcProviders.map((p) => {
              const style = PROVIDER_STYLES[p.id] ?? { emoji: "🔐", bg: "#1e40af", color: "#fff", label: `使用 ${p.label} 登入` };
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => signIn(p.id, { callbackUrl })}
                  style={{
                    padding: "11px 16px",
                    borderRadius: 6,
                    cursor: "pointer",
                    background: style.bg,
                    color: style.color,
                    border: style.bg === "#fff" ? "1px solid #d1d5db" : "none",
                    fontSize: 14,
                    fontWeight: 600,
                    textAlign: "left",
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                  }}
                >
                  <span style={{ fontSize: 16 }}>{style.emoji}</span>
                  <span>{style.label}</span>
                </button>
              );
            })}
          </div>
        )}

        {/* Divider */}
        {oidcProviders.length > 0 && hasCredentials && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
            <div style={{ flex: 1, height: 1, background: "#e5e7eb" }} />
            <span style={{ fontSize: 11, color: "#9ca3af", textTransform: "uppercase" }}>或</span>
            <div style={{ flex: 1, height: 1, background: "#e5e7eb" }} />
          </div>
        )}

        {/* Local credentials form */}
        {hasCredentials && (
          <form onSubmit={handleLocalSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <label style={labelStyle}>
              使用者名稱
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                style={inputStyle}
                autoComplete="username"
                required
              />
            </label>
            <label style={labelStyle}>
              密碼
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={inputStyle}
                autoComplete="current-password"
                required
              />
            </label>
            {localError && (
              <div style={errorStyle}>
                {localError}
              </div>
            )}
            <button
              type="submit"
              disabled={submitting}
              style={{
                padding: "10px 16px",
                borderRadius: 6,
                cursor: submitting ? "wait" : "pointer",
                background: "#0f172a",
                color: "#fff",
                border: "none",
                fontSize: 14,
                fontWeight: 600,
                marginTop: 4,
              }}
            >
              {submitting ? "登入中…" : "本地登入"}
            </button>
          </form>
        )}

        {oidcProviders.length === 0 && !hasCredentials && (
          <div style={{ fontSize: 13, color: "#dc2626" }}>
            ⚠ 沒有可用的登入方式 — 請聯絡管理員配置 OIDC 或建立本地帳號。
          </div>
        )}
      </div>
    </div>
  );
}

// ── styles ──────────────────────────────────────────────────────

const pageStyle: React.CSSProperties = {
  minHeight: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: "#f8fafc",
  fontFamily: "system-ui, -apple-system, 'Noto Sans TC', sans-serif",
};
const cardStyle: React.CSSProperties = {
  width: "100%",
  maxWidth: 380,
  padding: 28,
  background: "#fff",
  borderRadius: 10,
  boxShadow: "0 2px 12px rgba(0,0,0,0.06)",
  border: "1px solid #e5e7eb",
};
const labelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  fontSize: 12,
  fontWeight: 600,
  color: "#374151",
};
const inputStyle: React.CSSProperties = {
  padding: "8px 10px",
  borderRadius: 5,
  border: "1px solid #d1d5db",
  fontSize: 13,
  color: "#111827",
};
const errorStyle: React.CSSProperties = {
  background: "#fef2f2",
  color: "#dc2626",
  padding: "8px 12px",
  borderRadius: 5,
  fontSize: 12,
  marginBottom: 12,
};
