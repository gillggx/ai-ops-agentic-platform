import { getRequestConfig } from "next-intl/server";
import { cookies } from "next/headers";

/** i18n P0 (2026-07-05) — cookie-based locale, NO URL routing.
 *
 *  內部工具不做 /en/... prefix；locale 存 NEXT_LOCALE cookie（Topbar 切換器
 *  寫入後 reload）。預設 zh-TW。訊息檔按 namespace 拆檔，這裡合併 —
 *  讓不同 surface 的翻譯工作可以平行進行不打架。
 */
import { SUPPORTED_LOCALES, DEFAULT_LOCALE, type AppLocale } from "./locales";

const NAMESPACES = [
  "common", "buildFlow", "console", "agentPanel", "phaseTimeline",
  "nav", "dashboard", "patrol", "skills", "alarms",
  "sup", "kb", "mem", "me",
] as const;

export default getRequestConfig(async () => {
  const store = await cookies();
  const raw = store.get("NEXT_LOCALE")?.value;
  const locale: AppLocale = (SUPPORTED_LOCALES as readonly string[]).includes(raw ?? "")
    ? (raw as AppLocale)
    : DEFAULT_LOCALE;

  const messages: Record<string, unknown> = {};
  for (const ns of NAMESPACES) {
    try {
      messages[ns] = (await import(`../../messages/${locale}/${ns}.json`)).default;
    } catch {
      // namespace 檔還沒建 — fail-open，t() 會顯示 key（開發期可見即可修）
    }
  }
  return { locale, messages };
});
