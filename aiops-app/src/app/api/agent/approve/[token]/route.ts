import { NextRequest } from "next/server";

const AGENT_BASE_URL = process.env.AGENT_BASE_URL ?? "http://localhost:8000";

/**
 * POST /api/agent/approve/[token]
 * Proxies the HITL approval decision to aiops-agent.
 */
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ token: string }> }
) {
  const { token } = await params;
  const body = await req.json();

  try {
    const upstream = await fetch(`${AGENT_BASE_URL}/api/v1/agent/approve/${token}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await upstream.json().catch(() => ({}));
    return Response.json(data, { status: upstream.status });
  } catch {
    return Response.json({ error: "Agent unreachable" }, { status: 503 });
  }
}
