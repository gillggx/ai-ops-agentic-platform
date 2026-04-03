import { NextRequest, NextResponse } from "next/server";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

function authHeaders() {
  return {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${TOKEN}`,
  };
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const body = await req.json();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/skill-definitions/${id}`, {
    method: "PATCH",
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json(
      { error: data.message ?? data.detail ?? "更新失敗" },
      { status: res.status }
    );
  }
  const skill = data.data ?? data;
  return NextResponse.json({ ...skill, id: String(skill.id) });
}

// PUT → PATCH (backward compat)
export const PUT = PATCH;

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const res = await fetch(`${FASTAPI_BASE}/api/v1/skill-definitions/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(
      { error: (data as Record<string, string>).message ?? "刪除失敗" },
      { status: res.status }
    );
  }
  return NextResponse.json({ success: true, id });
}
