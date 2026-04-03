import { NextRequest, NextResponse } from "next/server";
import { readEventTypes, writeEventTypes } from "@/lib/store";

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const types = readEventTypes();
  const filtered = types.filter((t) => t.id !== id);
  if (filtered.length === types.length) return NextResponse.json({ error: "Not found" }, { status: 404 });
  writeEventTypes(filtered);
  return NextResponse.json({ status: "deleted", id });
}
