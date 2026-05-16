import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const AGENT_BASE_URL = process.env.AGENT_BASE_URL ?? process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

/**
 * POST /api/agent/build/plan-confirm
 * v30 (2026-05-16): user confirms (or edits) the goal plan phases.
 * Resumes a graph paused at goal_plan_confirm_gate.
 *
 * Body: { sessionId, confirmed: bool, phases?: [...] }
 */
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const headers = await authHeaders();

  const upstream = await fetch(`${AGENT_BASE_URL}/api/v1/agent/build/plan-confirm`, {
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
