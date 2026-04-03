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
    const res = await fetch(`${FASTAPI_BASE}/api/v1/skill-definitions`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    const data = await res.json();
    // Unwrap StandardResponse { success, data, message }
    const skills = data.data ?? data;
    return NextResponse.json(
      (Array.isArray(skills) ? skills : []).map((s: Record<string, unknown>) => ({
        ...s,
        id: String(s.id), // AdminTable expects string id
      }))
    );
  } catch (err) {
    console.error("[skills GET]", err);
    return NextResponse.json([], { status: 200 });
  }
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/skill-definitions`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json(
      { error: data.message ?? data.detail ?? "創建失敗" },
      { status: res.status }
    );
  }
  const skill = data.data ?? data;
  return NextResponse.json({ ...skill, id: String(skill.id) }, { status: 201 });
}
