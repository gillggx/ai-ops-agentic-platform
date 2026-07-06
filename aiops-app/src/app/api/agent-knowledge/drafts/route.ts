import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

/** W2 — 跨 user 草稿清單（PE/IT_ADMIN；ON_DUTY 403）。 */
export async function GET(_req: NextRequest) {
  const res = await fetch(`${FASTAPI_BASE}/api/v1/agent-knowledge/drafts`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
