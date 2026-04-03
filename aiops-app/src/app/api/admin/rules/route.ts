import { NextRequest, NextResponse } from "next/server";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

function authHeaders() {
  return {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${TOKEN}`,
  };
}

export async function GET() {
  try {
    const res = await fetch(`${FASTAPI_BASE}/api/v1/diagnostic-rules`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    const data = await res.json();
    const rules = data.data ?? data;
    return NextResponse.json(
      (Array.isArray(rules) ? rules : []).map((r: Record<string, unknown>) => ({
        ...r,
        id: String(r.id),
      }))
    );
  } catch (err) {
    console.error("[rules GET]", err);
    return NextResponse.json([], { status: 200 });
  }
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/diagnostic-rules`, {
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
  const rule = data.data ?? data;
  return NextResponse.json({ ...rule, id: String(rule.id) }, { status: 201 });
}
