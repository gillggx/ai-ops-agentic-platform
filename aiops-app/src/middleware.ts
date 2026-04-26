import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";

// Paths accessible without a session.
const PUBLIC_PATHS = [
  "/login",
  "/api/auth",          // NextAuth callbacks
  "/_next",
  "/favicon",
];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname.startsWith(p));
}

/**
 * Decode a JWT's exp claim without verifying signature.
 * Returns true if the token is missing or already expired.
 *
 * NextAuth's session cookie lives 30 days but the inner Java JWT only
 * lives ~60 minutes. Without this check the user appears "logged in"
 * to middleware long after API calls start failing 401.
 */
function isJwtExpired(jwt: string | undefined | null): boolean {
  if (!jwt) return true;
  const parts = jwt.split(".");
  if (parts.length !== 3) return true;
  try {
    const payload = JSON.parse(
      atob(parts[1].replace(/-/g, "+").replace(/_/g, "/"))
    );
    if (typeof payload.exp !== "number") return false;
    // 30-second clock skew tolerance.
    return payload.exp * 1000 < Date.now() + 30_000;
  } catch {
    return true;
  }
}

function buildLoginRedirect(req: NextRequest, pathname: string) {
  const fwdHost = req.headers.get("x-forwarded-host") ?? req.headers.get("host");
  const fwdProto = req.headers.get("x-forwarded-proto") ?? "https";
  const origin = fwdHost ? `${fwdProto}://${fwdHost}` : req.nextUrl.origin;
  const loginUrl = new URL("/login", origin);
  loginUrl.searchParams.set("callbackUrl", pathname);
  return NextResponse.redirect(loginUrl);
}

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (isPublicPath(pathname)) return NextResponse.next();

  // NextAuth v5: `auth()` inside middleware returns current session or null.
  const session = await auth();

  if (!session) {
    if (process.env.AIOPS_AUTH_REQUIRED !== "1") {
      return NextResponse.next();
    }
    return buildLoginRedirect(req, pathname);
  }

  // Even with a NextAuth session, the inner Java JWT may have expired.
  // When it has, every API proxy will start returning 401 — better to
  // redirect once now than let the user click around on a dead UI.
  if (process.env.AIOPS_AUTH_REQUIRED === "1") {
    const javaJwt = (session as unknown as { javaJwt?: string }).javaJwt;
    if (isJwtExpired(javaJwt)) {
      return buildLoginRedirect(req, pathname);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    // Match everything except Next internals and static files
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
