import {
  fieldPath,
  objectPath,
  workspacePath,
} from "../src/features/ontology-package/api";

function equal(actual: string, expected: string, label: string): void {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${expected}, received ${actual}`);
  }
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
