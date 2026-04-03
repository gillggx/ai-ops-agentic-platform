import { NextRequest } from "next/server";

const AGENT_BASE_URL = process.env.AGENT_BASE_URL ?? "http://localhost:8000";
const INTERNAL_TOKEN = process.env.INTERNAL_API_TOKEN ?? "dev-token";

/**
 * POST /api/agent/chat
 * Proxies the SSE stream from fastapi_backend_refactored to the browser.
 */
export async function POST(req: NextRequest) {
  const body = await req.json();

  const upstream = await fetch(`${AGENT_BASE_URL}/api/v1/agent/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${INTERNAL_TOKEN}`,
    },
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
