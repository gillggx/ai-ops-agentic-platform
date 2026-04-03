import { NextRequest, NextResponse } from "next/server";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

function authHeaders() {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${TOKEN}`,
  };
}

export async function GET(req: NextRequest) {
  const activeOnly = req.nextUrl.searchParams.get("active_only") ?? "false";
  try {
    const res = await fetch(
      `${FASTAPI_BASE}/api/v1/auto-patrols?active_only=${activeOnly}`,
      { headers: authHeaders(), cache: "no-store" }
    );
    const data = await res.json();
    const list = data.data ?? data;
    return NextResponse.json(Array.isArray(list) ? list : []);
  } catch (err) {
    console.error("[auto-patrols GET]", err);
    return NextResponse.json([], { status: 200 });
  }
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/auto-patrols`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json(
      { error: data.message ?? data.detail ?? "建立失敗" },
      { status: res.status }
    );
  }
  return NextResponse.json(data.data ?? data, { status: 201 });
}
