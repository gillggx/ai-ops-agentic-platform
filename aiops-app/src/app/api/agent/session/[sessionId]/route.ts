import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

// 2026-07-10 fix: was sending legacy INTERNAL_API_TOKEN (Java /api/v1 wants
// the user JWT) and defaulted to :8000. Same disease as the monitor proxy.
const AGENT_BASE_URL = process.env.AGENT_BASE_URL ?? process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

/**
 * GET  /api/agent/session/[id] — hydrate an existing session (messages + last pipeline snapshot)
 * DELETE /api/agent/session/[id] — wipe the session history
 */
export async function GET(_req: NextRequest, { params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  const upstream = await fetch(`${AGENT_BASE_URL}/api/v1/agent/session/${sessionId}`, {
    headers: await authHeaders(),
  });
  const body = await upstream.text();
  return new Response(body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  const upstream = await fetch(`${AGENT_BASE_URL}/api/v1/agent/session/${sessionId}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  const body = await upstream.text();
  return new Response(body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
