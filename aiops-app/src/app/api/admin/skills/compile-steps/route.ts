import { NextRequest, NextResponse } from "next/server";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/skill-definitions/compile-steps`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${TOKEN}`,
    },
    body: JSON.stringify(body),
  });
  const data = await res.json() as Record<string, unknown>;

  // FastAPI StandardResponse.error() returns HTTP 200 with {status:"error",...}
  // Detect both HTTP errors and application-level errors.
  if (!res.ok || data.status === "error") {
    const message = (data.message as string) ?? (data.detail as string) ?? "AI 編譯失敗";
    return NextResponse.json(
      { error: message },
      { status: res.ok ? 422 : res.status },
    );
  }

  // Unwrap StandardResponse envelope: {status:"ok", data:{...}}
  const payload = (data.data ?? data) as Record<string, unknown>;
  return NextResponse.json(payload);
}
