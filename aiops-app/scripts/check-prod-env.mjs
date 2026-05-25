// Fail fast when required production env vars are missing.
// Run before `next build` in CI/CD: `node scripts/check-prod-env.mjs && next build`.

const REQUIRED = [
  {
    name: "INTERNAL_API_TOKEN",
    minLen: 16,
    rejectLiterals: ["dev-token", "change-me-internal-token"],
    hint: "Generate via `openssl rand -hex 32`. Must match java-backend INTERNAL_API_TOKEN.",
  },
  {
    name: "NEXTAUTH_SECRET",
    minLen: 32,
    rejectLiterals: ["change-me"],
    hint: "Generate via `openssl rand -base64 32`.",
  },
  {
    name: "FASTAPI_BASE_URL",
    minLen: 1,
    rejectLiterals: [],
    hint: "Java backend URL, e.g. http://aiops-java-api:8002",
  },
];

const errors = [];
for (const { name, minLen, rejectLiterals, hint } of REQUIRED) {
  const v = process.env[name];
  if (!v) {
    errors.push(`  ${name}: missing. ${hint}`);
    continue;
  }
  if (v.length < minLen) {
    errors.push(`  ${name}: too short (need >= ${minLen} chars). ${hint}`);
    continue;
  }
  if (rejectLiterals.includes(v)) {
    errors.push(`  ${name}: placeholder value "${v}" is not allowed. ${hint}`);
  }
}

if (errors.length > 0) {
  console.error("[check-prod-env] Production env validation failed:");
  for (const e of errors) console.error(e);
  console.error("\nSet these in the deploy environment before running `next build`.");
  process.exit(1);
}

console.log("[check-prod-env] All required env vars present.");
