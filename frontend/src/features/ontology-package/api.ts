import type { AxiosError } from "axios";
import client from "../../api/client";
import type {
  DraftDiagnostic,
  DraftField,
  DraftObject,
  DraftWriteResult,
  ImportPreview,
  VersionSummary,
  WorkspaceOverview,
} from "./types";

interface ApiEnvelope<T> {
  data: T;
  revision: number;
}

interface ApiDiagnostic {
  id: string;
  code: string;
  severity: DraftDiagnostic["severity"];
  message: string;
  related_ids: string[];
}

interface ApiField {
  id: string;
  physical_name: string;
  label: string | null;
  description: string | null;
  xsd_type: string;
  primary_key: boolean;
  title: boolean;
  aliases: string[];
  status: DraftField["status"];
  priority: number;
}

interface ApiObject {
  id: string;
  physical_name: string;
  label: string | null;
  description: string | null;
  fields: ApiField[];
  status: DraftObject["status"];
  priority: number;
}

interface ApiVersionSummary {
  version: string;
  published_at: string;
  actor: string;
  release_notes: string;
  revision: number | null;
  active: boolean;
}

interface ApiOverview {
  workspace_id: string;
  display_name: string;
  active_version: ApiVersionSummary | null;
  counts: {
    objects: number;
    fields: number;
    relations: number;
    temporal_policies: number;
  };
  objects: ApiObject[];
  diagnostics: ApiDiagnostic[];
}

export interface ImportPreviewResponse {
  status: ImportPreview["status"];
  token: string | null;
  object_count: number;
  field_count: number;
  diagnostics: ApiDiagnostic[];
}

interface ApiErrorBody {
  code?: string;
}

const basePath = "/ontology-packages";

export const stableSegment = (id: string): string => encodeURIComponent(id);

export const workspacePath = (workspaceId: string): string =>
  `${basePath}/workspaces/${stableSegment(workspaceId)}`;

export const objectPath = (workspaceId: string, objectId: string): string =>
  `${workspacePath(workspaceId)}/objects/${stableSegment(objectId)}`;

export const fieldPath = (workspaceId: string, fieldId: string): string =>
  `${workspacePath(workspaceId)}/fields/${stableSegment(fieldId)}`;

const diagnostic = (value: ApiDiagnostic): DraftDiagnostic => ({
  id: value.id,
  code: value.code,
  severity: value.severity,
  message: value.message,
  relatedIds: value.related_ids,
});

const field = (value: ApiField): DraftField => ({
  id: value.id,
  physicalName: value.physical_name,
  label: value.label,
  description: value.description,
  xsdType: value.xsd_type,
  primaryKey: value.primary_key,
  title: value.title,
  aliases: value.aliases,
  status: value.status,
  priority: value.priority,
});

const object = (value: ApiObject): DraftObject => ({
  id: value.id,
  physicalName: value.physical_name,
  label: value.label,
  description: value.description,
  fields: value.fields.map(field),
  status: value.status,
  priority: value.priority,
});

const version = (value: ApiVersionSummary): VersionSummary => ({
  version: value.version,
  publishedAt: value.published_at,
  actor: value.actor,
  releaseNotes: value.release_notes,
  revision: value.revision,
  active: value.active,
});

export async function fetchWorkspaceOverview(workspaceId: string): Promise<WorkspaceOverview> {
  const response = await client.get<ApiEnvelope<ApiOverview>>(workspacePath(workspaceId));
  const { data, revision } = response.data;
  return {
    workspaceId: data.workspace_id,
    displayName: data.display_name,
    revision,
    activeVersion: data.active_version ? version(data.active_version) : null,
    counts: {
      objects: data.counts.objects,
      fields: data.counts.fields,
      relations: data.counts.relations,
      temporalPolicies: data.counts.temporal_policies,
    },
    objects: data.objects.map(object),
    diagnostics: data.diagnostics.map(diagnostic),
  };
}

export async function previewImport(
  workspaceId: string,
  files: Blob[],
  expectedRevision: number
): Promise<ImportPreview> {
  const response = await client.post<ApiEnvelope<ImportPreviewResponse>>(
    `${workspacePath(workspaceId)}/imports/preview`,
    importPreviewFormData(files, expectedRevision)
  );
  return mapImportPreview(response.data.data);
}

export function importPreviewFormData(files: Blob[], expectedRevision: number): FormData {
  const body = new FormData();
  body.append("expected_revision", String(expectedRevision));
  files.forEach((file) => body.append("files", file));
  return body;
}

export function mapImportPreview(preview: ImportPreviewResponse): ImportPreview {
  return {
    status: preview.status,
    token: preview.token,
    objectCount: preview.object_count,
    fieldCount: preview.field_count,
    diagnostics: preview.diagnostics.map(diagnostic),
  };
}

export async function confirmImport(
  workspaceId: string,
  token: string,
  expectedRevision: number
): Promise<DraftWriteResult> {
  const response = await client.post<ApiEnvelope<unknown>>(
    `${workspacePath(workspaceId)}/imports/${stableSegment(token)}/confirm`,
    { expected_revision: expectedRevision }
  );
  return { revision: response.data.revision };
}

export async function updateObject(
  workspaceId: string,
  objectId: string,
  changes: { label: string; description: string },
  expectedRevision: number
): Promise<DraftWriteResult> {
  const response = await client.patch<ApiEnvelope<unknown>>(objectPath(workspaceId, objectId), {
    ...changes,
    expected_revision: expectedRevision,
  });
  return { revision: response.data.revision };
}

export async function updateField(
  workspaceId: string,
  fieldId: string,
  changes: { label: string; description: string },
  expectedRevision: number
): Promise<DraftWriteResult> {
  const response = await client.patch<ApiEnvelope<unknown>>(fieldPath(workspaceId, fieldId), {
    ...changes,
    expected_revision: expectedRevision,
  });
  return { revision: response.data.revision };
}

export function isDraftRevisionConflict(error: unknown): boolean {
  return (error as AxiosError<ApiErrorBody>)?.response?.data?.code === "draft_revision_conflict";
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  const body = (error as AxiosError<{ message?: string }>)?.response?.data;
  return body?.message || fallback;
}
