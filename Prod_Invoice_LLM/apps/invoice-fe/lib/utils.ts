import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * FE Gap 183: takes the invoice's real currency instead of hardcoding USD.
 *
 * `currency` is the ISO-4217 code stored on `Invoice.currency` (nullable — the
 * column has always existed but historical rows and any document the extractor
 * couldn't read a currency off carry NULL). Null/blank falls back to "USD",
 * which is a *display* default only: nothing writes it back to the row.
 *
 * The argument is optional so the signature stays backwards compatible; a call
 * site that hasn't been given a currency to thread through keeps rendering
 * exactly as it did before.
 *
 * An unrecognised code (Intl throws a RangeError on anything that isn't a
 * well-formed currency code) degrades to "<CODE> 1,234.56" rather than taking
 * the whole panel down — a garbled extraction shouldn't blank the dashboard.
 */
export function normalizeCurrencyCode(currency?: string | null): string {
  const code = (currency ?? "").trim().toUpperCase();
  return code || "USD";
}

export function formatCurrency(
  amount: number | null | undefined,
  currency?: string | null
): string {
  const code = normalizeCurrencyCode(currency);
  const value = amount ?? 0;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: code,
    }).format(value);
  } catch {
    return `${code} ${new Intl.NumberFormat("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value)}`;
  }
}

export function formatDate(dateStr: string | Date | null | undefined): string {
  if (!dateStr) return "-";
  const date = typeof dateStr === "string" ? new Date(dateStr) : dateStr;
  if (isNaN(date.getTime())) return "-";
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * FE Gap 201: `date.toISOString().split("T")[0]` converts through UTC before
 * slicing, so building a `YYYY-MM-DD` API param this way is off by a day for
 * any non-UTC timezone whenever local and UTC land on different calendar
 * dates (e.g. IST, UTC+5:30 -- the 1st of the month becomes the 30th/31st,
 * and "today" between 00:00-05:29 is still yesterday in UTC). This reads the
 * date's own local year/month/day instead, so the string always matches what
 * the browser's clock says "today" is.
 */
export function toLocalDateString(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
