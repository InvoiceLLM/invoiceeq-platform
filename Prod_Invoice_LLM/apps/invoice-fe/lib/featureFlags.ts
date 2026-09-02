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
 * With the flag OFF the list is `.pdf` alone -- byte-identical to before this
 * mechanism existed -- because `document_to_base64_images()` is only reachable
 * through the flag-on graph; with it off a non-PDF loses the multimodal channel
 * silently, which §4's "Non-PDF image support" section calls the real defect.
 */
export const PDF_ONLY_EXTENSIONS = [".pdf"] as const;
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
  return flags?.ENABLE_GENERIC_EXTRACTION
    ? [...GENERIC_EXTRACTION_EXTENSIONS]
    : [...PDF_ONLY_EXTENSIONS];
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
