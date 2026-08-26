import {
  fieldPath,
  importPreviewFormData,
  mapImportPreview,
  objectPath,
  workspacePath,
} from "../src/features/ontology-package/api";
import {
  installPreviewForRevision,
  previewForCurrentRevision,
} from "../src/features/ontology-package/importPreviewState";

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
