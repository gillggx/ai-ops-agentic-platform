/** client 端日期/時間格式 locale — 讀 NEXT_LOCALE cookie（與 request.ts 同源），
 *  給 toLocaleString 系列用。SSR 安全：無 document 時回預設。 */
import { DEFAULT_LOCALE, SUPPORTED_LOCALES, type AppLocale } from "./locales";

export function activeLocale(): AppLocale {
  if (typeof document === "undefined") return DEFAULT_LOCALE;
  const m = /(?:^|;\s*)NEXT_LOCALE=([^;]+)/.exec(document.cookie);
  const v = m?.[1] ?? "";
  return (SUPPORTED_LOCALES as readonly string[]).includes(v) ? (v as AppLocale) : DEFAULT_LOCALE;
}
