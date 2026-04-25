import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const res = await fetch(`${FASTAPI_BASE}/api/v1/auto-patrols/${id}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json({ error: data.message ?? "Not found" }, { status: res.status });
  }
  return NextResponse.json(data.data ?? data);
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await req.json();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/auto-patrols/${id}`, {
    method: "PATCH",
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json(
      { error: data.message ?? data.detail ?? "更新失敗" },
      { status: res.status }
    );
  }
  return NextResponse.json(data.data ?? data);
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const res = await fetch(`${FASTAPI_BASE}/api/v1/auto-patrols/${id}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json(
      { error: data.message ?? "刪除失敗" },
      { status: res.status }
    );
  }
  return NextResponse.json({ ok: true });
}
