import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const AGENT_BASE_URL = process.env.AGENT_BASE_URL ?? process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
import { INTERNAL_API_TOKEN as INTERNAL_TOKEN } from "@/lib/internal-token";

/**
 * GET  /api/agent/session/[id] — hydrate an existing session (messages + last pipeline snapshot)
 * DELETE /api/agent/session/[id] — wipe the session history
 */
export async function GET(_req: NextRequest, { params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  const upstream = await fetch(`${AGENT_BASE_URL}/api/v1/agent/session/${sessionId}`, {
    headers: { "Authorization": `Bearer ${INTERNAL_TOKEN}` },
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
    headers: { "Authorization": `Bearer ${INTERNAL_TOKEN}` },
  });
  const body = await upstream.text();
  return new Response(body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
