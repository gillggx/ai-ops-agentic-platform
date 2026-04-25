import { NextRequest, NextResponse } from "next/server";
import { authHeaders, getBearerToken } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

/**
 * /me/memories — returns ONLY the current user's memories by passing
 * `?userId=<session.userId>` to Java. If the user isn't logged in via
 * NextAuth, falls back to empty.
 */
export async function GET(req: NextRequest) {
  const ctx = await getBearerToken();
  const userId = ctx.userId;
  if (!userId) {
    return NextResponse.json({ memories: [], experience: [] });
  }
  const limit = req.nextUrl.searchParams.get("limit") ?? "100";
  const params = new URLSearchParams({ limit, userId: String(userId) });

  try {
    const [legacyRes, expRes] = await Promise.all([
      fetch(`${FASTAPI_BASE}/api/v1/agent/memory?${params.toString()}`, {
        headers: await authHeaders(), cache: "no-store",
      }),
      fetch(`${FASTAPI_BASE}/api/v1/experience-memory?${params.toString()}`, {
        headers: await authHeaders(), cache: "no-store",
      }),
    ]);
    const legacyData = legacyRes.ok ? await legacyRes.json() : {};
    const expData = expRes.ok ? await expRes.json() : {};
    const legacy = Array.isArray(legacyData) ? legacyData
      : (legacyData.memories ?? legacyData.data ?? []);
    const experience = Array.isArray(expData) ? expData : (expData.data ?? []);
    // Filter experience-memory by userId (Java's alias controller doesn't filter on that endpoint)
    const expFiltered = experience.filter(
      (e: Record<string, unknown>) => Number(e.user_id) === Number(userId),
    );
    return NextResponse.json({
      memories: legacy,
      experience: expFiltered,
      user_id: userId,
    });
  } catch (err) {
    console.error("[/me/memories]", err);
    return NextResponse.json({ memories: [], experience: [], error: (err as Error).message });
  }
}
