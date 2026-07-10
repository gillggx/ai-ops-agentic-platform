import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

// 標準 Skill CRUD proxy (V82). GET list / POST create.
const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

export async function GET() {
  const res = await fetch(`${BASE}/api/v1/agent-skills`, {
    headers: await authHeaders(), cache: "no-store",
  });
  return new Response(await res.text(), {
    status: res.status, headers: { "Content-Type": "application/json" },
  });
}

export async function POST(req: NextRequest) {
  const res = await fetch(`${BASE}/api/v1/agent-skills`, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: await req.text(),
  });
  return new Response(await res.text(), {
    status: res.status, headers: { "Content-Type": "application/json" },
  });
}
