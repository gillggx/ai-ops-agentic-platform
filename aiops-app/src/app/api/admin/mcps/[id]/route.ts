import { NextRequest, NextResponse } from "next/server";
import { readMcps, writeMcps } from "@/lib/store";

export async function PUT(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json();
  const mcps = readMcps();
  const idx = mcps.findIndex((m) => m.id === id);
  if (idx === -1) return NextResponse.json({ error: "Not found" }, { status: 404 });

  mcps[idx] = { ...mcps[idx], ...body, id, updated_at: new Date().toISOString() };
  writeMcps(mcps);
  return NextResponse.json(mcps[idx]);
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const mcps = readMcps();
  const filtered = mcps.filter((m) => m.id !== id);
  if (filtered.length === mcps.length) return NextResponse.json({ error: "Not found" }, { status: 404 });
  writeMcps(filtered);
  return NextResponse.json({ status: "deleted", id });
}
