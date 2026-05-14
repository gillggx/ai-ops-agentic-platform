import { NextRequest } from "next/server";

// v19 (2026-05-14): chat intent confirmation resume.
// Forwards directly to sidecar (bypasses Java) — same pattern as
// admin/build-traces. Sidecar binds 127.0.0.1:8050 so localhost works.
const SIDECAR_BASE = process.env.SIDECAR_BASE_URL ?? "http://127.0.0.1:8050";
const SIDECAR_TOKEN = process.env.SIDECAR_SERVICE_TOKEN ?? "";

export const dynamic = "force-dynamic";

/**
 * POST /api/agent/chat/intent-respond
 * Body: { chatSessionId, confirmations }
 * Returns SSE stream from the resumed build.
 */
export async function POST(req: NextRequest) {
  if (!SIDECAR_TOKEN) {
    return new Response(
      JSON.stringify({ error: "SIDECAR_SERVICE_TOKEN not configured" }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    );
  }
  const body = await req.json();
  const upstream = await fetch(`${SIDECAR_BASE}/internal/agent/chat/intent-respond`, {
    method: "POST",
    headers: {
      "X-Service-Token": SIDECAR_TOKEN,
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    // @ts-expect-error: Node fetch duplex
    duplex: "half",
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(
      JSON.stringify({ error: `Sidecar responded with ${upstream.status}` }),
      { status: upstream.status || 502, headers: { "Content-Type": "application/json" } },
    );
  }
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
}
