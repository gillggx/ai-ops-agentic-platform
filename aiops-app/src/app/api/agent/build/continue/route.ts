import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const AGENT_BASE_URL = process.env.AGENT_BASE_URL ?? process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

/**
 * POST /api/agent/build/continue
 * SPEC_glassbox_continuation: when the user picks "再給 N 步" on a
 * ContinuationCard, the panel POSTs here. We proxy through to Java
 * /api/v1/agent/build/continue, which proxies on to the sidecar
 * /internal/agent/build/continue.
 *
 * The response is an SSE stream identical to /api/agent/build, so the
 * caller can feed it back into the same dispatcher.
 */
export async function POST(req: NextRequest) {
  const body = await req.json();
  const headers = await authHeaders();

  const upstream = await fetch(`${AGENT_BASE_URL}/api/v1/agent/build/continue`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    // @ts-expect-error: Node.js fetch duplex option for SSE streaming
    duplex: "half",
  });

  if (!upstream.ok) {
    return new Response(
      JSON.stringify({ error: `build/continue responded with ${upstream.status}` }),
      { status: upstream.status, headers: { "Content-Type": "application/json" } }
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
