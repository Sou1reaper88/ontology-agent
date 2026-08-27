export type DiagnosticSeverity = "error" | "warning" | "confirmation_required";

export interface DraftField {
  id: string;
  physicalName: string;
  label: string | null;
  description: string | null;
  xsdType: string;
  primaryKey: boolean;
  title: boolean;
  aliases: string[];
  status: "active" | "inactive";
  priority: number;
}

export interface DraftObject {
  id: string;
  physicalName: string;
  label: string | null;
  description: string | null;
  fields: DraftField[];
  status: "active" | "inactive";
  priority: number;
}

export interface DraftRelation {
  id: string;
  label: string;
  sourceObjectId: string;
  sourceFieldId: string;
  targetObjectId: string;
  targetFieldId: string;
  cardinality: "one_to_one" | "one_to_many" | "many_to_one" | "many_to_many";
  status: "active" | "inactive";
  priority: number;
  confirmed: boolean;
}

export interface DraftTemporalPolicy {
  objectId: string;
  partitionFieldId: string;
  grain: "day" | "month";
  defaultStrategy: "t_minus_2" | "previous_complete_month";
  allowQueryOverride: boolean;
  status: "active" | "inactive";
  priority: number;
}

export interface DraftDiagnostic {
  id: string;
  code: string;
  severity: DiagnosticSeverity;
  message: string;
  relatedIds: string[];
}

export interface DiagnosticDisposition {
  diagnosticId: string;
  status: "resolved" | "dismissed";
  note: string | null;
  actor: string;
  resolvedAt: string;
}

export interface VersionSummary {
  version: string;
  publishedAt: string;
  actor: string;
  releaseNotes: string;
  revision: number | null;
  counts: VersionCounts | null;
  contentDigest: string | null;
  active: boolean;
}

export interface VersionCounts {
  concepts: number;
  properties: number;
  relations: number;
  rules: number;
  dataSources: number;
  mappings: number;
  temporalPolicies: number;
}

export interface WorkspaceOverview {
  workspaceId: string;
  displayName: string;
  revision: number;
  activeVersion: VersionSummary | null;
  counts: {
    objects: number;
    fields: number;
    relations: number;
    temporalPolicies: number;
  };
  objects: DraftObject[];
  relations: DraftRelation[];
  temporalPolicies: DraftTemporalPolicy[];
  dispositions: DiagnosticDisposition[];
  diagnostics: DraftDiagnostic[];
}

export interface ImportPreview {
  status: "ready" | "blocked";
  token: string | null;
  objectCount: number;
  fieldCount: number;
  diagnostics: DraftDiagnostic[];
}

export interface DraftWriteResult {
  revision: number;
}
