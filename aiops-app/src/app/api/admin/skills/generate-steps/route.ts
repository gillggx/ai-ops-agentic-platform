import { NextRequest, NextResponse } from "next/server";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(
    `${FASTAPI_BASE}/api/v1/skill-definitions/generate-steps`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${TOKEN}`,
      },
      body: JSON.stringify(body),
    }
  );
  const data = await res.json() as Record<string, unknown>;
  if (!res.ok || data.status === "error") {
    const message = (data.message as string) ?? (data.detail as string) ?? "AI 生成失敗";
    return NextResponse.json({ error: message }, { status: res.ok ? 422 : res.status });
  }
  return NextResponse.json((data.data ?? data) as Record<string, unknown>);
}
