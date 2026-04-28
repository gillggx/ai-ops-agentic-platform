import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

export async function PUT(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json();
  // { description?, source?, isActive?, attributes? }
  const res = await fetch(`${FASTAPI_BASE}/api/v1/event-types/${id}`, {
    method: "PUT",
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    return NextResponse.json(
      { error: data.message ?? data.detail ?? data.error?.message ?? "更新失敗" },
      { status: res.status },
    );
  }
  return NextResponse.json(data.data ?? data);
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const res = await fetch(`${FASTAPI_BASE}/api/v1/event-types/${id}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(
      { error: data.message ?? data.error?.message ?? "刪除失敗" },
      { status: res.status },
    );
  }
  return NextResponse.json({ status: "deleted", id });
}
