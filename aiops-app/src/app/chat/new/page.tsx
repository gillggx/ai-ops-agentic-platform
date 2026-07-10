"use client";

/**
 * /chat/new — creates a fresh Agent session and redirects to /chat/[id].
 *
 * Usage:
 *   /chat/new                — blank session
 *   /chat/new?prompt=Hello   — pre-fills the first message
 */

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function NewChatPage() {
  // Next.js 15 prod build requires useSearchParams() to live inside a
  // Suspense boundary (SSG bailout rule).
  return (
    <Suspense fallback={<FallbackLoading />}>
      <NewChatInner />
    </Suspense>
  );
}

function FallbackLoading() {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "system-ui, sans-serif",
        color: "#718096",
        fontSize: 13,
      }}
    >
      建立新對話中…
    </div>
  );
}

function NewChatInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/agent/session", { method: "POST" });
        if (!res.ok) {
          const txt = await res.text().catch(() => "");
          throw new Error(`Create session failed: ${res.status} ${txt}`);
        }
        const payload = await res.json();
        const sid = payload.session_id;
        if (!sid) throw new Error("Session API returned no session_id");
        if (cancelled) return;
        const prompt = searchParams.get("prompt");
        const q = prompt ? `?prompt=${encodeURIComponent(prompt)}` : "";
        router.replace(`/chat/${sid}${q}`);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "system-ui, -apple-system, 'Noto Sans TC', sans-serif",
        color: "#4a5568",
      }}
    >
      {error ? (
        <div style={{ maxWidth: 400, textAlign: "center" }}>
          <div style={{ fontSize: 14, color: "#c53030", marginBottom: 12 }}>
            無法建立 session
          </div>
          <div style={{ fontSize: 12, color: "#718096", marginBottom: 16 }}>{error}</div>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: "6px 14px",
              background: "var(--p, #2b6cb0)",
              color: "#fff",
              border: "none",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            重試
          </button>
        </div>
      ) : (
        <div style={{ fontSize: 13 }}>建立新對話中…</div>
      )}
    </div>
  );
}
