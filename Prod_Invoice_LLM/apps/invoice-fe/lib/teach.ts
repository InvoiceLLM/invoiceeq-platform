// =============================================================================
// FILE: lib/teach.ts
// FEATURE: FE Feature 22 Task 22.13 — the Trainer as a mode of Ask.
//
// Two pure helpers, kept out of the components so they are tested on their own:
//   parseTeachCommand  "teach: freight is not taxable for Rajesh" -> the rule text
//   defaultVendorFor   which known vendor the sentence names, if exactly one
//
// The vendor default is a plain, visible string match against the tenant's own
// vendor list (GET /trainer/vendors) — it only PRE-SELECTS the scope picker, the
// user can change it, and nothing is saved until Confirm. It is not a guess at
// meaning: when the sentence names no vendor, or more than one could match, no
// default is chosen and the user picks.
// =============================================================================

import type { VendorOption } from "@/lib/trainer-service";

const TEACH_PREFIX = /^\s*teach\s*:\s*([\s\S]*)$/i;

/** The rule text after `teach:`, or null when the message is not a teach command. */
export function parseTeachCommand(text: string): string | null {
  const match = TEACH_PREFIX.exec(text);
  if (!match) return null;
  const rule = match[1].trim();
  return rule === "" ? null : rule;
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * The vendor the sentence names:
 *   1. a vendor whose FULL name appears in the text (the longest wins), else
 *   2. the one vendor whose first word appears as a whole word (3+ letters).
 * Two vendors sharing that first word -> null (ambiguous; the user picks).
 */
export function defaultVendorFor(text: string, vendors: VendorOption[]): VendorOption | null {
  const haystack = text.toLowerCase();

  const fullMatches = vendors
    .filter((v) => v.name.trim() !== "" && haystack.includes(v.name.trim().toLowerCase()))
    .sort((a, b) => b.name.length - a.name.length);
  if (fullMatches.length > 0) return fullMatches[0];

  const wordMatches = vendors.filter((v) => {
    const first = v.name.trim().split(/\s+/)[0] ?? "";
    if (first.length < 3) return false;
    return new RegExp(`(^|[^\\p{L}\\p{N}])${escapeRegExp(first.toLowerCase())}($|[^\\p{L}\\p{N}])`, "u").test(haystack);
  });
  return wordMatches.length === 1 ? wordMatches[0] : null;
}
