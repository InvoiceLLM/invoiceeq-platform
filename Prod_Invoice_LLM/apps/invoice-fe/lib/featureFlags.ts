// =============================================================================
// FILE: lib/featureFlags.ts
// FEATURE: FE side of BE Feature 27 task R5(a).
//
// The backend's process-wide `ENABLE_*` flags, fetched once and cached for the
// page's lifetime. This is the mechanism FE Gap 378 recorded as missing — the
// reason `DropZone`'s accept list could not be widened was that nothing could
// tell the browser whether `ENABLE_GENERIC_EXTRACTION` was on.
//
// WHY A MODULE-LEVEL PROMISE rather than React state or a context. Several
// unrelated components will eventually ask the same question, the answer does
// not change within a page load (the flags are process-wide, E2), and the
// consequence of two components mounting together must be ONE request, not two.
// A module-scoped in-flight promise gives that with no provider to thread and no
// re-render to coordinate.
//
// FAIL-CLOSED, and this is the part that matters. Every accessor returns
// `false` when the fetch fails, when it has not resolved yet, or when the key is
// absent. A flag read is a question about whether a BACKEND CAPABILITY exists,
// and answering "yes" when we do not know invites the user into a path the
// backend cannot serve — for `ENABLE_GENERIC_EXTRACTION` specifically, that
// means accepting a PNG the extractor would silently drop the visual channel
// for. Defaulting to `false` degrades to today's behaviour, which is exactly the
// same fail-closed choice `config.py` makes for every flag's default.
//
// FE FEATURE 19 NUANCE: fail-closed still governs FLAG READS, but not the
// upload accept list's floor. BE Feature 28 ships image->PDF conversion with no
// flag at all, so `acceptedUploadExtensions()` degrades to the image list, not
// to `.pdf`, when the fetch fails -- see the comment above that function.
// =============================================================================

export type FeatureFlags = Record<string, boolean>;

let inFlight: Promise<FeatureFlags> | null = null;

/**
 * Fetch the flag map once per page load.
 *
 * Errors are swallowed to `{}` rather than thrown: a feature check must not be
 * able to break a page that would otherwise render fine, and `{}` reads as
 * "everything off" through the accessors below, which is the safe answer.
 */
export function loadFeatureFlags(): Promise<FeatureFlags> {
  if (inFlight) return inFlight;

  inFlight = fetch("/api/config/features", { cache: "no-store" })
    .then((res) => (res.ok ? res.json() : { flags: {} }))
    .then((body) => (body?.flags ?? {}) as FeatureFlags)
    .catch(() => ({} as FeatureFlags));

  return inFlight;
}

/** Test seam and session-switch escape hatch. Not called in normal operation. */
export function resetFeatureFlagsCache(): void {
  inFlight = null;
}

/**
 * Which file extensions the ingestion picker should accept.
 *
 * Lives here rather than in `DropZone` because BOTH of that component's guards
 * -- the `accept` attribute and the suffix check in the change handler -- must
 * agree, and the surest way to make them agree is to give them one source. They
 * are separate checks for a real reason (a drag-and-drop bypasses the picker
 * entirely), and Feature 27 §4 calls out that they must move together or a user
 * drags a PNG past the picker and is rejected after selection.
 *
 * FE FEATURE 19 / BE FEATURE 28 changes the FLOOR of this list, not the flag.
 * BE Feature 28 converts images to PDF at the door unconditionally (BE decision
 * D1 -- no `ENABLE_IMAGE_UPLOAD_CONVERSION`), so the image suffixes are always
 * offered and the fail-closed default for THIS list is the image list, not
 * `.pdf` alone: a failed `/config/features` fetch says nothing about a
 * capability that does not depend on a flag, and degrading to PDF-only would
 * reject a file the backend would happily have accepted.
 *
 * `ENABLE_GENERIC_EXTRACTION` (Feature 27 / FE Gap 378) is untouched and still
 * read below -- the two COMPOSE. The always-on image list is the base; the
 * generic-extraction list is unioned on top when that flag is on, so widening
 * either one never narrows the other.
 *
 * `PDF_ONLY_EXTENSIONS` is kept as the label helper's degenerate case and for
 * any caller that genuinely means "PDF and nothing else".
 */
export const PDF_ONLY_EXTENSIONS = [".pdf"] as const;

/**
 * Always offered, flag-independent. Mirrors BE Feature 28's converter input set
 * (`services/image_conversion.py`); `.pdf` is first so it stays the primary
 * suggestion in the OS file dialog.
 */
export const IMAGE_UPLOAD_EXTENSIONS = [
  ".pdf",
  ".png",
  ".jpg",
  ".jpeg",
  ".tif",
  ".tiff",
  ".webp",
  ".bmp",
] as const;
export const GENERIC_EXTRACTION_EXTENSIONS = [
  ".pdf",
  ".png",
  ".jpg",
  ".jpeg",
  ".tiff",
  ".tif",
  ".bmp",
  ".webp",
] as const;

export function acceptedUploadExtensions(flags: FeatureFlags | null): string[] {
  // Union, de-duplicated, first-seen order -- so `.pdf` (first in the base
  // list) stays first whatever the flag says. The `flags` argument survives
  // because Feature 27's list may hold suffixes the image list does not.
  const merged = flags?.ENABLE_GENERIC_EXTRACTION
    ? [...IMAGE_UPLOAD_EXTENSIONS, ...GENERIC_EXTRACTION_EXTENSIONS]
    : [...IMAGE_UPLOAD_EXTENSIONS];
  return Array.from(new Set(merged));
}

/**
 * The words on screen for a given accept list.
 *
 * Every "what may I upload" string in the app reads from this rather than
 * spelling the formats out, so the copy and the `accept` attribute cannot
 * disagree -- the same property FE Gap 378 established for the two guards.
 *
 * `.jpeg` and `.tif` are aliases of `.jpg`/`.tiff` and are folded away: a user
 * does not need to be told both spellings, and "JPG, JPEG" reads like two
 * different things.
 */
const FORMAT_LABEL_ALIASES: Record<string, string> = {
  jpeg: "JPG",
  tif: "TIFF",
};

export function acceptedFormatsLabel(extensions: string[]): string {
  const names: string[] = [];
  for (const ext of extensions) {
    const bare = ext.replace(/^\./, "").toLowerCase();
    const name = FORMAT_LABEL_ALIASES[bare] ?? bare.toUpperCase();
    if (!names.includes(name)) names.push(name);
  }
  if (names.length === 0) return "";
  if (names.length === 1) return names[0];
  return `${names.slice(0, -1).join(", ")} or ${names[names.length - 1]}`;
}

/**
 * The picker's error copy, which has to name what is actually allowed.
 *
 * Hardcoding "Only PDF documents are allowed" was correct while that was true
 * and becomes a lie the moment the flag flips -- and a user told the wrong rule
 * retries the wrong thing.
 */
export function invalidFormatMessage(extensions: string[]): string {
  if (extensions.length === 1) {
    return "Invalid file format. Only PDF documents are allowed.";
  }
  const readable = extensions.map((e) => e.replace(".", "").toUpperCase()).join(", ");
  return `Invalid file format. Allowed: ${readable}.`;
}
