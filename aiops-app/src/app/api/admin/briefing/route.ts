import { NextRequest } from "next/server";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const scope = searchParams.get("scope") ?? "fab";
  const toolId = searchParams.get("toolId") ?? "";

  const params = new URLSearchParams({ scope });
  if (toolId) params.set("toolId", toolId);

  const res = await fetch(`${FASTAPI_BASE}/api/v1/briefing?${params}`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
    cache: "no-store",
  });

  return new Response(res.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
    },
  });
}

export async function POST(request: NextRequest) {
  const body = await request.json();

  const res = await fetch(`${FASTAPI_BASE}/api/v1/briefing`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  return new Response(res.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
    },
  });
}
