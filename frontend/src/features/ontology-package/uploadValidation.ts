export const MAX_METADATA_UPLOAD_BYTES = 20 * 1024 * 1024;

interface UploadCandidate {
  name: string;
  size: number;
}

const allowedExtensions = new Set([".xlsx", ".tsv", ".txt"]);

export function metadataUploadValidationError(file: UploadCandidate): string | null {
  const dot = file.name.lastIndexOf(".");
  const extension = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!allowedExtensions.has(extension)) {
    return "仅支持无宏 XLSX、UTF-8 TSV/TXT";
  }
  if (file.size > MAX_METADATA_UPLOAD_BYTES) {
    return "单个文件不能超过 20 MB";
  }
  return null;
}
