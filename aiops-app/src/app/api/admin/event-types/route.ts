import { NextRequest, NextResponse } from "next/server";
import { readEventTypes, writeEventTypes, StoredEventType } from "@/lib/store";

export async function GET() {
  return NextResponse.json(readEventTypes());
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const types = readEventTypes();

  if (types.some((t) => t.name === body.name)) {
    return NextResponse.json({ error: `Event type '${body.name}' already exists` }, { status: 409 });
  }

  const newType: StoredEventType = {
    id: `et-${Date.now()}`,
    name: body.name,
    severity: body.severity ?? "info",
    description: body.description ?? "",
    created_at: new Date().toISOString(),
  };

  writeEventTypes([...types, newType]);
  return NextResponse.json(newType, { status: 201 });
}
