import type { ImportPreview } from "./types";

export interface RevisionBoundPreview {
  sourceRevision: number;
  preview: ImportPreview;
}

export function installPreviewForRevision(
  preview: ImportPreview,
  sourceRevision: number,
  currentRevision: number
): RevisionBoundPreview | null {
  return sourceRevision === currentRevision ? { preview, sourceRevision } : null;
}

export function previewForCurrentRevision(
  value: RevisionBoundPreview | null,
  currentRevision: number
): RevisionBoundPreview | null {
  return value?.sourceRevision === currentRevision ? value : null;
}
