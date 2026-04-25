import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const res = await fetch(`${FASTAPI_BASE}/api/v1/experience-memory/${id}`, {
      method: "DELETE",
      headers: await authHeaders(),
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("[memories DELETE]", err);
    return NextResponse.json({ error: "delete failed" }, { status: 500 });
  }
}
