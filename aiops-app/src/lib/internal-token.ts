const RAW = process.env.INTERNAL_API_TOKEN;
const DEV_FALLBACK = "dev-token-LOCAL-ONLY-NOT-FOR-PROD";
const MIN_LEN = 16;

function isWeak(t: string | undefined): boolean {
  if (!t) return true;
  if (t === "dev-token") return true;
  if (t.length < MIN_LEN) return true;
  return false;
}

if (isWeak(RAW)) {
  if (process.env.NODE_ENV === "production") {
    throw new Error(
      "[internal-token] INTERNAL_API_TOKEN is missing, placeholder, or too short " +
      `(min ${MIN_LEN} chars). Production builds require a real token. ` +
      "Set INTERNAL_API_TOKEN in the deploy environment."
    );
  } else {
    // eslint-disable-next-line no-console
    console.warn(
      "[internal-token] INTERNAL_API_TOKEN not set / weak — using dev fallback. " +
      "DO NOT deploy this build."
    );
  }
}

export const INTERNAL_API_TOKEN: string = isWeak(RAW) ? DEV_FALLBACK : (RAW as string);
