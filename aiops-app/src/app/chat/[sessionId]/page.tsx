"use client";

/**
 * /chat/[sessionId] — session tab. One URL = one conversation.
 *
 * Layout: Pipeline Builder canvas + results panel (center), AI Agent panel (right).
 * Phase 5-UX-3b unifies "ask for analysis" + "edit pipeline" + "see result" into
 * a single tab backed by a persistent Agent session.
 */

import dynamic from "next/dynamic";
import { Suspense, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import type { PipelineJSON } from "@/lib/pipeline-builder/types";

// React Flow can't SSR
const BuilderLayout = dynamic(() => import("@/components/pipeline-builder/BuilderLayout"), {
  ssr: false,
});

interface SessionHydration {
  session_id: string;
  title: string | null;
  last_pipeline_json: PipelineJSON | null;
  messages: Array<{ role: string; content: string }>;
}

export default function ChatSessionPage() {
  // Next.js 15 requires useSearchParams() inside Suspense for SSG bailout.
  return (
    <Suspense fallback={<div style={{ padding: 40, textAlign: "center", color: "#718096" }}>載入對話中…</div>}>
      <ChatSessionInner />
    </Suspense>
  );
}

function ChatSessionInner() {
  const params = useParams();
  const searchParams = useSearchParams();
  const sessionId = Array.isArray(params?.sessionId)
    ? params.sessionId[0]
    : (params?.sessionId as string);

  const [hydrated, setHydrated] = useState<SessionHydration | null>(null);
  const [error, setError] = useState<string | null>(null);

  const initialPrompt = searchParams.get("prompt") ?? undefined;

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/agent/session/${sessionId}`);
        if (!res.ok) {
          if (res.status === 404) {
            throw new Error(`Session ${sessionId} 不存在或已過期`);
          }
          throw new Error(`載入 session 失敗 (${res.status})`);
        }
        const payload = await res.json();
        if (!cancelled) setHydrated(payload);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId]);

  if (error) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "system-ui, sans-serif" }}>
        <div style={{ maxWidth: 420, textAlign: "center", color: "#4a5568" }}>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8, color: "#c53030" }}>
            無法載入對話
          </div>
          <div style={{ fontSize: 12, color: "#718096", marginBottom: 16 }}>{error}</div>
          <a
            href="/chat/new"
            style={{ fontSize: 13, color: "var(--p, #2b6cb0)", textDecoration: "none" }}
          >
            開啟新對話 →
          </a>
        </div>
      </div>
    );
  }

  if (!hydrated) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "system-ui, sans-serif", color: "#718096", fontSize: 13 }}>
        載入對話中…
      </div>
    );
  }

  return (
    <BuilderLayout
      mode="session"
      sessionId={sessionId}
      initialPipelineJson={hydrated.last_pipeline_json ?? undefined}
      initialPrompt={initialPrompt}
    />
  );
}
