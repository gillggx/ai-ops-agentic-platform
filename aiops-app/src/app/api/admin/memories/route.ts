import { NextRequest, NextResponse } from "next/server";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

function authHeaders() {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${TOKEN}`,
  };
}

export async function GET(req: NextRequest) {
  const status = req.nextUrl.searchParams.get("status");
  const limit = req.nextUrl.searchParams.get("limit") ?? "100";
  const params = new URLSearchParams({ limit });
  if (status) params.set("status", status);

  try {
    // Fetch from both memory tables (agent_memories + agent_experience_memory)
    const [legacyRes, expRes] = await Promise.all([
      fetch(`${FASTAPI_BASE}/api/v1/agent/memory?${params.toString()}`, {
        headers: authHeaders(), cache: "no-store",
      }),
      fetch(`${FASTAPI_BASE}/api/v1/experience-memory?${params.toString()}`, {
        headers: authHeaders(), cache: "no-store",
      }),
    ]);
    const legacyData = legacyRes.ok ? await legacyRes.json() : [];
    const expData = expRes.ok ? await expRes.json() : {};
    // Merge: legacy returns array directly, experience returns { data: [...] }
    const legacy = Array.isArray(legacyData) ? legacyData : (legacyData.data ?? []);
    const experience = Array.isArray(expData) ? expData : (expData.data ?? []);
    // Tag source for UI distinction
    const tagged = [
      ...legacy.map((m: Record<string, unknown>) => ({ ...m, _memory_type: "rag" })),
      ...experience.map((m: Record<string, unknown>) => ({ ...m, _memory_type: "experience" })),
    ];
    return NextResponse.json(tagged);
  } catch (err) {
    console.error("[memories GET]", err);
    return NextResponse.json([], { status: 200 });
  }
}
