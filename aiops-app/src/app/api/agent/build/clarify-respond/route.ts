import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const AGENT_BASE_URL = process.env.AGENT_BASE_URL ?? process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

/**
 * POST /api/agent/build/clarify-respond
 * v19 (2026-05-14): user submits BulletConfirmCard answers for a paused
 * Skill Builder build. Java proxies to sidecar
 * /internal/agent/build/clarify-respond. Returns the resumed SSE stream
 * (macro_plan → compile → finalize → done).
 *
 * Body: { sessionId, confirmations: {bid: {action, edit_text}} }
 *       (also accepts legacy `answers: {qid: value}` for old MCQ format)
 */
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const headers = await authHeaders();

  const upstream = await fetch(`${AGENT_BASE_URL}/api/v1/agent/build/clarify-respond`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    // @ts-expect-error: Node.js fetch duplex option for SSE streaming
    duplex: "half",
  });

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    return new Response(text || `upstream ${upstream.status}`, {
      status: upstream.status,
    });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
      Connection: "keep-alive",
    },
  });
}
