/**
 * Gap 146: Persistent draft file storage across client-side page navigation.
 * Prevents files dropped/selected on the Ingestion screen from being silently
 * discarded when navigating to other routes before clicking Submit Ingestion.
 */

let draftFiles: File[] = [];

export function getDraftFiles(): File[] {
  return draftFiles;
}

export function setDraftFiles(files: File[]): void {
  draftFiles = [...files];
}

export function clearDraftFiles(): void {
  draftFiles = [];
}
