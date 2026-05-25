import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";
import { INTERNAL_API_TOKEN as INTERNAL_TOKEN } from "@/lib/internal-token";

const AGENT_BASE_URL = process.env.AGENT_BASE_URL ?? process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

/**
 * POST /api/agent/session — create a new agent session.
 * Returns { session_id, created_at }.
 */
export async function POST(_req: NextRequest) {
  const upstream = await fetch(`${AGENT_BASE_URL}/api/v1/agent/session`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${INTERNAL_TOKEN}`,
    },
  });
  const body = await upstream.text();
  return new Response(body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
