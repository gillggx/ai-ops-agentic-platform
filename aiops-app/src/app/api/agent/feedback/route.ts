import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

/**
 * POST /api/agent/feedback — proxy to Java POST /api/v1/agent/feedback.
 * Records 👍 / 👎 on a single agent answer (per session_id + message_idx).
 */
export async function POST(req: NextRequest) {
  const body = await req.text();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/agent/feedback`, {
    method: "POST",
    headers: await authHeaders(),
    body,
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
