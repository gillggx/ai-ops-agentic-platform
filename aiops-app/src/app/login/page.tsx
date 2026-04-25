import { availableProviders } from "@/auth";
import LoginClient from "./LoginClient";

// Server-rendered entry: enumerate registered providers (server-side env)
// and hand to client component for the interactive form.
export default function LoginPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | undefined>>;
}) {
  const providers = availableProviders();
  return (
    <LoginClientWrapper providers={providers} searchParamsPromise={searchParams} />
  );
}

async function LoginClientWrapper({
  providers,
  searchParamsPromise,
}: {
  providers: { id: string; label: string }[];
  searchParamsPromise?: Promise<Record<string, string | undefined>>;
}) {
  const searchParams = (await searchParamsPromise) ?? {};
  return <LoginClient providers={providers} error={searchParams.error ?? null} callbackUrl={searchParams.callbackUrl ?? "/"} />;
}
