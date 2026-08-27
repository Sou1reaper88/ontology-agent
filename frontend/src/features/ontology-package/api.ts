import type { AxiosError } from "axios";
import client from "../../api/client";
import type {
  DraftDiagnostic,
  DiagnosticDisposition,
  DraftField,
  DraftObject,
  DraftRelation,
  DraftTemporalPolicy,
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

interface ApiRelation {
  id: string;
  label: string;
  source_object_id: string;
  source_field_id: string;
  target_object_id: string;
  target_field_id: string;
  cardinality: DraftRelation["cardinality"];
  status: DraftRelation["status"];
  priority: number;
  confirmed: boolean;
}

interface ApiTemporalPolicy {
  object_id: string;
  partition_field_id: string;
  grain: DraftTemporalPolicy["grain"];
  default_strategy: DraftTemporalPolicy["defaultStrategy"];
  allow_query_override: boolean;
  status: DraftTemporalPolicy["status"];
  priority: number;
}

interface ApiDiagnosticDisposition {
  diagnostic_id: string;
  status: DiagnosticDisposition["status"];
  note: string | null;
  actor: string;
  resolved_at: string;
}

interface ApiVersionCounts {
  concepts: number;
  properties: number;
  relations: number;
  rules: number;
  data_sources: number;
  mappings: number;
  temporal_policies: number;
}

interface ApiVersionSummary {
  version: string;
  published_at: string;
  actor: string;
  release_notes: string;
  revision: number | null;
  counts?: ApiVersionCounts | null;
  content_digest?: string | null;
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
  relations: ApiRelation[];
  temporal_policies: ApiTemporalPolicy[];
  dispositions: ApiDiagnosticDisposition[];
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

export type ImportTemplateVariant = "single" | "multiple";

export interface DownloadedTemplate {
  blob: Blob;
  fileName: string;
}

export const stableSegment = (id: string): string => encodeURIComponent(id);

export const workspacePath = (workspaceId: string): string =>
  `${basePath}/workspaces/${stableSegment(workspaceId)}`;

export const objectPath = (workspaceId: string, objectId: string): string =>
  `${workspacePath(workspaceId)}/objects/${stableSegment(objectId)}`;

export const fieldPath = (workspaceId: string, fieldId: string): string =>
  `${workspacePath(workspaceId)}/fields/${stableSegment(fieldId)}`;

export const relationPath = (workspaceId: string, relationId: string): string =>
  `${workspacePath(workspaceId)}/relations/${stableSegment(relationId)}`;

export const temporalPolicyPath = (workspaceId: string, objectId: string): string =>
  `${workspacePath(workspaceId)}/temporal-policies/${stableSegment(objectId)}`;

export const diagnosticResolutionPath = (workspaceId: string, diagnosticId: string): string =>
  `${workspacePath(workspaceId)}/diagnostics/${stableSegment(diagnosticId)}/resolve`;

export const versionsPath = (workspaceId: string): string => `${workspacePath(workspaceId)}/versions`;

export const importTemplatePath = (
  workspaceId: string,
  variant: ImportTemplateVariant
): string => `${workspacePath(workspaceId)}/imports/template?variant=${variant}`;

export function safeAttachmentFileName(
  contentDisposition: string | undefined,
  fallback: string
): string {
  const match = /filename="?([^";]+)"?/i.exec(contentDisposition ?? "");
  const candidate = match?.[1]?.trim();
  if (
    !candidate ||
    candidate.includes("..") ||
    candidate.includes("/") ||
    candidate.includes("\\") ||
    !/^[A-Za-z0-9][A-Za-z0-9._-]*\.xlsx$/i.test(candidate)
  ) {
    return fallback;
  }
  return candidate;
}

export const diagnosticResolutionPayload = (
  explanation: string,
  status: "resolved" | "dismissed",
  expectedRevision: number
) => ({ explanation, status, expected_revision: expectedRevision });

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

const relation = (value: ApiRelation): DraftRelation => ({
  id: value.id,
  label: value.label,
  sourceObjectId: value.source_object_id,
  sourceFieldId: value.source_field_id,
  targetObjectId: value.target_object_id,
  targetFieldId: value.target_field_id,
  cardinality: value.cardinality,
  status: value.status,
  priority: value.priority,
  confirmed: value.confirmed,
});

const temporalPolicy = (value: ApiTemporalPolicy): DraftTemporalPolicy => ({
  objectId: value.object_id,
  partitionFieldId: value.partition_field_id,
  grain: value.grain,
  defaultStrategy: value.default_strategy,
  allowQueryOverride: value.allow_query_override,
  status: value.status,
  priority: value.priority,
});

const disposition = (value: ApiDiagnosticDisposition): DiagnosticDisposition => ({
  diagnosticId: value.diagnostic_id,
  status: value.status,
  note: value.note,
  actor: value.actor,
  resolvedAt: value.resolved_at,
});

export const mapVersionSummary = (value: ApiVersionSummary): VersionSummary => ({
  version: value.version,
  publishedAt: value.published_at,
  actor: value.actor,
  releaseNotes: value.release_notes,
  revision: value.revision,
  counts: value.counts
    ? {
        concepts: value.counts.concepts,
        properties: value.counts.properties,
        relations: value.counts.relations,
        rules: value.counts.rules,
        dataSources: value.counts.data_sources,
        mappings: value.counts.mappings,
        temporalPolicies: value.counts.temporal_policies,
      }
    : null,
  contentDigest: value.content_digest ?? null,
  active: value.active,
});

export async function fetchWorkspaceOverview(workspaceId: string): Promise<WorkspaceOverview> {
  const response = await client.get<ApiEnvelope<ApiOverview>>(workspacePath(workspaceId));
  const { data, revision } = response.data;
  return {
    workspaceId: data.workspace_id,
    displayName: data.display_name,
    revision,
    activeVersion: data.active_version ? mapVersionSummary(data.active_version) : null,
    counts: {
      objects: data.counts.objects,
      fields: data.counts.fields,
      relations: data.counts.relations,
      temporalPolicies: data.counts.temporal_policies,
    },
    objects: data.objects.map(object),
    relations: data.relations.map(relation),
    temporalPolicies: data.temporal_policies.map(temporalPolicy),
    dispositions: data.dispositions.map(disposition),
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

export async function downloadImportTemplate(
  workspaceId: string,
  variant: ImportTemplateVariant
): Promise<DownloadedTemplate> {
  const fallback = `ontology-import-${variant}.xlsx`;
  const response = await client.get<Blob>(importTemplatePath(workspaceId, variant), {
    responseType: "blob",
  });
  return {
    blob: response.data,
    fileName: safeAttachmentFileName(response.headers["content-disposition"], fallback),
  };
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

export async function upsertRelation(
  workspaceId: string,
  relationId: string,
  changes: Omit<DraftRelation, "id">,
  expectedRevision: number
): Promise<DraftWriteResult> {
  const response = await client.put<ApiEnvelope<unknown>>(relationPath(workspaceId, relationId), {
    label: changes.label,
    source_object_id: changes.sourceObjectId,
    source_field_id: changes.sourceFieldId,
    target_object_id: changes.targetObjectId,
    target_field_id: changes.targetFieldId,
    cardinality: changes.cardinality,
    status: changes.status,
    priority: changes.priority,
    confirmed: changes.confirmed,
    expected_revision: expectedRevision,
  });
  return { revision: response.data.revision };
}

export async function upsertTemporalPolicy(
  workspaceId: string,
  policy: DraftTemporalPolicy,
  expectedRevision: number
): Promise<DraftWriteResult> {
  const response = await client.put<ApiEnvelope<unknown>>(
    temporalPolicyPath(workspaceId, policy.objectId),
    {
      partition_field_id: policy.partitionFieldId,
      grain: policy.grain,
      default_strategy: policy.defaultStrategy,
      allow_query_override: policy.allowQueryOverride,
      status: policy.status,
      priority: policy.priority,
      expected_revision: expectedRevision,
    }
  );
  return { revision: response.data.revision };
}

export async function resolveDiagnostic(
  workspaceId: string,
  diagnosticId: string,
  explanation: string,
  status: "resolved" | "dismissed",
  expectedRevision: number
): Promise<DraftWriteResult> {
  const response = await client.post<ApiEnvelope<unknown>>(
    diagnosticResolutionPath(workspaceId, diagnosticId),
    diagnosticResolutionPayload(explanation, status, expectedRevision)
  );
  return { revision: response.data.revision };
}

export async function validateWorkspace(
  workspaceId: string
): Promise<{ diagnostics: DraftDiagnostic[]; revision: number }> {
  const response = await client.post<ApiEnvelope<{ diagnostics: ApiDiagnostic[] }>>(
    `${workspacePath(workspaceId)}/validate`
  );
  return { diagnostics: response.data.data.diagnostics.map(diagnostic), revision: response.data.revision };
}

export async function fetchVersions(workspaceId: string): Promise<VersionSummary[]> {
  const response = await client.get<ApiEnvelope<ApiVersionSummary[]>>(versionsPath(workspaceId));
  return response.data.data.map(mapVersionSummary);
}

export async function publishVersion(
  workspaceId: string,
  version: string,
  releaseNotes: string,
  expectedRevision: number
): Promise<VersionSummary> {
  const response = await client.post<ApiEnvelope<ApiVersionSummary>>(versionsPath(workspaceId), {
    version,
    release_notes: releaseNotes,
    expected_revision: expectedRevision,
  });
  return mapVersionSummary(response.data.data);
}

export async function rollbackVersion(
  workspaceId: string,
  version: string,
  reason: string
): Promise<VersionSummary> {
  const response = await client.post<ApiEnvelope<ApiVersionSummary>>(
    `${versionsPath(workspaceId)}/${stableSegment(version)}/rollback`,
    { reason }
  );
  return mapVersionSummary(response.data.data);
}

export function isDraftRevisionConflict(error: unknown): boolean {
  return (error as AxiosError<ApiErrorBody>)?.response?.data?.code === "draft_revision_conflict";
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  const body = (error as AxiosError<{ message?: string }>)?.response?.data;
  return body?.message || fallback;
}
