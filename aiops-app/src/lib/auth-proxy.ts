/**
 * Shared helper for all /api/* proxy routes.
 *
 * Returns the Authorization Bearer token to use when proxying to Java:
 *   - If a user is logged in via NextAuth, use their per-user Java JWT.
 *   - Else fall back to the shared INTERNAL_API_TOKEN (legacy mode).
 *
 * This lets the cutover be gradual: existing proxy routes keep working
 * unchanged while new per-user auth activates as users log in.
 */

import { auth } from "@/auth";

const INTERNAL_API_TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

export interface AuthContext {
  token: string;          // Bearer value
  source: "session" | "shared";
  username?: string;
  userId?: number;
  roles?: string[];
}

/**
 * Get the best available bearer token. Returns the session JWT if the caller
 * is logged in, otherwise the shared INTERNAL_API_TOKEN.
 */
export async function getBearerToken(): Promise<AuthContext> {
  try {
    const session = await auth();
    const s = session as unknown as {
      javaJwt?: string;
      userId?: number;
      roles?: string[];
      user?: { name?: string };
    } | null;
    if (s?.javaJwt) {
      return {
        token: s.javaJwt,
        source: "session",
        userId: s.userId,
        roles: s.roles,
        username: s.user?.name,
      };
    }
  } catch {
    // auth() can throw in edge cases — fall through to shared token
  }
  return { token: INTERNAL_API_TOKEN, source: "shared" };
}

/** Auth headers ready to merge into a fetch(). */
export async function authHeaders(extra: Record<string, string> = {}): Promise<Record<string, string>> {
  const ctx = await getBearerToken();
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${ctx.token}`,
    ...extra,
  };
}
