/**
 * GET /api/mcp-catalog
 * Returns the live MCP catalog (from data/mcps.json, falls back to static).
 * aiops-agent pulls this at S1 Context Load.
 */
import { NextResponse } from "next/server";
import { readMcps } from "@/lib/store";

export async function GET() {
  const mcps = readMcps();
  // Return shape matches MCPDefinition (strip internal fields aiops-agent doesn't need)
  const catalog = mcps.map(({ id: _id, created_at: _c, updated_at: _u, ...rest }) => rest);
  return NextResponse.json(catalog);
}
