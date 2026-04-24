import { NextRequest, NextResponse } from "next/server";

// Java cutover v2 note: Java's /api/v1/agent/build is one-step SSE, but the
// frontend expects the two-step {session_id → /stream/{id}} contract from the
// legacy Python backend. Pin agent/build proxies to Python until Java or the
// frontend converges on one flow. AGENT_BUILD_BASE_URL overrides FASTAPI_BASE_URL
// for just these 4 routes.
const FASTAPI_BASE = process.env.AGENT_BUILD_BASE_URL
  ?? process.env.FASTAPI_BASE_URL
  ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

function authHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${TOKEN}`,
  };
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/agent/build`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
