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

export interface DraftDiagnostic {
  id: string;
  code: string;
  severity: DiagnosticSeverity;
  message: string;
  relatedIds: string[];
}

export interface VersionSummary {
  version: string;
  publishedAt: string;
  actor: string;
  releaseNotes: string;
  revision: number | null;
  active: boolean;
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
