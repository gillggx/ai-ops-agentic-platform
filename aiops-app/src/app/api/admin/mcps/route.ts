import { NextRequest, NextResponse } from "next/server";
import { readMcps, writeMcps, StoredMCP } from "@/lib/store";

export async function GET() {
  return NextResponse.json(readMcps());
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const mcps = readMcps();

  if (mcps.some((m) => m.name === body.name)) {
    return NextResponse.json({ error: `MCP name '${body.name}' already exists` }, { status: 409 });
  }

  const now = new Date().toISOString();
  const newMcp: StoredMCP = {
    id: `mcp-${Date.now()}`,
    name: body.name,
    description: body.description ?? "",
    is_handoff: body.is_handoff ?? false,
    parameters: body.parameters ?? {},
    usage_example: body.usage_example ?? "",
    output_description: body.output_description ?? "",
    created_at: now,
    updated_at: now,
  };

  writeMcps([...mcps, newMcp]);
  return NextResponse.json(newMcp, { status: 201 });
}
