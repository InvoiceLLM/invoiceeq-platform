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
