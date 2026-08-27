import {
  fieldPath,
  importTemplatePath,
  importPreviewFormData,
  diagnosticResolutionPath,
  diagnosticResolutionPayload,
  mapImportPreview,
  mapVersionSummary,
  objectPath,
  relationPath,
  safeAttachmentFileName,
  temporalPolicyPath,
  versionsPath,
  workspacePath,
} from "../src/features/ontology-package/api";
import {
  installPreviewForRevision,
  previewForCurrentRevision,
} from "../src/features/ontology-package/importPreviewState";
import { metadataUploadValidationError } from "../src/features/ontology-package/uploadValidation";

function equal(actual: string, expected: string, label: string): void {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${expected}, received ${actual}`);
  }
}

function truthy(value: unknown, label: string): asserts value {
  if (!value) throw new Error(label);
}

equal(
  workspacePath("workspace / 中文"),
  "/ontology-packages/workspaces/workspace%20%2F%20%E4%B8%AD%E6%96%87",
  "workspace IDs are URL encoded"
);
equal(
  objectPath("workspace / 中文", "object/alpha beta"),
  "/ontology-packages/workspaces/workspace%20%2F%20%E4%B8%AD%E6%96%87/objects/object%2Falpha%20beta",
  "object IDs are URL encoded"
);
equal(
  fieldPath("workspace / 中文", "field/alpha beta"),
  "/ontology-packages/workspaces/workspace%20%2F%20%E4%B8%AD%E6%96%87/fields/field%2Falpha%20beta",
  "field IDs are URL encoded"
);
equal(
  relationPath("workspace / 中文", "relation/alpha beta"),
  "/ontology-packages/workspaces/workspace%20%2F%20%E4%B8%AD%E6%96%87/relations/relation%2Falpha%20beta",
  "relation IDs are URL encoded"
);
equal(
  temporalPolicyPath("workspace / 中文", "object/alpha beta"),
  "/ontology-packages/workspaces/workspace%20%2F%20%E4%B8%AD%E6%96%87/temporal-policies/object%2Falpha%20beta",
  "temporal object IDs are URL encoded"
);
equal(
  diagnosticResolutionPath("workspace / 中文", "diagnostic/alpha beta"),
  "/ontology-packages/workspaces/workspace%20%2F%20%E4%B8%AD%E6%96%87/diagnostics/diagnostic%2Falpha%20beta/resolve",
  "diagnostic IDs are URL encoded"
);
equal(
  versionsPath("workspace / 中文"),
  "/ontology-packages/workspaces/workspace%20%2F%20%E4%B8%AD%E6%96%87/versions",
  "versions path is workspace scoped"
);
equal(
  importTemplatePath("workspace / 中文", "multiple"),
  "/ontology-packages/workspaces/workspace%20%2F%20%E4%B8%AD%E6%96%87/imports/template?variant=multiple",
  "template path is workspace scoped and encoded"
);
equal(
  safeAttachmentFileName(
    'attachment; filename="ontology-import-single.xlsx"',
    "fallback.xlsx"
  ),
  "ontology-import-single.xlsx",
  "safe ASCII attachment name is retained"
);
equal(
  safeAttachmentFileName('attachment; filename="../unsafe.xlsx"', "fallback.xlsx"),
  "fallback.xlsx",
  "unsafe attachment names fall back"
);
equal(
  safeAttachmentFileName('attachment; filename="sample.tsv"', "fallback.xlsx"),
  "fallback.xlsx",
  "non-XLSX attachment names fall back"
);
if (metadataUploadValidationError({ name: "objects.XLSX", size: 1024 }) !== null) {
  throw new Error("supported XLSX files must remain selectable");
}
equal(
  metadataUploadValidationError({ name: "objects.xls", size: 1024 }) ?? "",
  "仅支持无宏 XLSX、UTF-8 TSV/TXT",
  "legacy XLS files are rejected"
);
equal(
  metadataUploadValidationError({ name: "objects.tsv", size: 20 * 1024 * 1024 + 1 }) ?? "",
  "单个文件不能超过 20 MB",
  "oversized files are rejected"
);
const dispositionPayload = diagnosticResolutionPayload("业务核对完成", "dismissed", 9);
equal(String(dispositionPayload.expected_revision), "9", "diagnostic disposition uses the supplied revision");
equal(dispositionPayload.status, "dismissed", "diagnostic disposition preserves the selected status");

const mappedPreview = mapImportPreview({
  status: "ready",
  token: "preview-token",
  object_count: 2,
  field_count: 5,
  diagnostics: [
    {
      id: "diagnostic/1",
      code: "metadata_warning",
      severity: "warning",
      message: "需要核对",
      related_ids: ["object/1"],
    },
  ],
});
equal(String(mappedPreview.objectCount), "2", "preview object count is mapped");
equal(String(mappedPreview.fieldCount), "5", "preview field count is mapped");
equal(mappedPreview.diagnostics[0].relatedIds[0], "object/1", "diagnostic IDs are mapped");

const importBody = importPreviewFormData([], 7);
equal(String(importBody.get("expected_revision")), "7", "preview uses the supplied revision");

const installedPreview = installPreviewForRevision(mappedPreview, 7, 7);
truthy(installedPreview, "current preview response is installed");
equal(String(installedPreview.sourceRevision), "7", "installed preview remembers source revision");
truthy(
  previewForCurrentRevision(installedPreview, 7),
  "preview remains usable at its source revision"
);
if (installPreviewForRevision(mappedPreview, 7, 8) !== null) {
  throw new Error("late preview response must not install after revision changes");
}
if (previewForCurrentRevision(installedPreview, 8) !== null) {
  throw new Error("preview is invalidated when its source revision is stale");
}

const enrichedVersion = mapVersionSummary({
  version: "1.0.0",
  published_at: "2026-08-26T00:00:00Z",
  actor: "admin",
  release_notes: "first release",
  revision: 5,
  active: true,
  counts: {
    concepts: 2,
    properties: 3,
    relations: 1,
    rules: 0,
    data_sources: 1,
    mappings: 5,
    temporal_policies: 1,
  },
  content_digest: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
});
equal(String(enrichedVersion.counts?.concepts), "2", "version counts are mapped");
equal(enrichedVersion.contentDigest?.slice(0, 12) ?? "", "0123456789ab", "version digest is mapped");

const legacyVersion = mapVersionSummary({
  version: "0.9.0",
  published_at: "2026-08-25T00:00:00Z",
  actor: "admin",
  release_notes: "legacy release",
  revision: null,
  active: false,
});
if (legacyVersion.counts !== null || legacyVersion.contentDigest !== null) {
  throw new Error("legacy versions use unavailable metadata markers");
}
