/**
 * /dev/charts — moved to /help/charts (logged-in users only).
 *
 * Kept as a permanent redirect so any bookmarked / linked URLs still work.
 * The mock-data factories the original page used now live at
 * src/lib/charts/mock-data.ts and feed both the catalog grid and detail
 * pages.
 */

import { redirect } from "next/navigation";

export default function DevChartsRedirect() {
  redirect("/help/charts");
}
