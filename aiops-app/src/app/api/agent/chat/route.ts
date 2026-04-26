import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const AGENT_BASE_URL = process.env.AGENT_BASE_URL ?? process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

/**
 * POST /api/agent/chat
 * Proxies the SSE stream from Java :8002 to the browser.
 *
 * Phase 8-A-1d follow-up: must use the logged-in user's Java JWT (via
 * authHeaders) — the legacy shared-secret bypass propagates user_id=null
 * to the sidecar, which then can't persist the agent_session, which
 * means follow-up turns ("加個分佈圖") see no prior canvas and the
 * Glass Box agent can't extend the pipeline.
 */
export async function POST(req: NextRequest) {
  const body = await req.json();
  const headers = await authHeaders();

  const upstream = await fetch(`${AGENT_BASE_URL}/api/v1/agent/chat/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    // Required for SSE streaming — do not buffer
    // @ts-expect-error: Node.js fetch duplex option
    duplex: "half",
  });

  if (!upstream.ok) {
    return new Response(
      JSON.stringify({ error: `Agent responded with ${upstream.status}` }),
      { status: upstream.status, headers: { "Content-Type": "application/json" } }
    );
  }

  // Pass-through the SSE stream
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
}
