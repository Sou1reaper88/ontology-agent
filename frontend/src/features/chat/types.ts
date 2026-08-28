export interface TemporalEvidence {
  partition_field: string;
  grain: "day" | "month";
  policy_source: "ontology";
  system_time: string;
  user_time: string | null;
  source: "explicit_absolute" | "explicit_relative" | "ontology_default";
  default_strategy: "t_minus_2" | "previous_complete_month";
  resolved_start: string;
  resolved_end: string;
  safety_status: "bounded";
  explanation: string;
}

export type OntologyStatus =
  | "generated"
  | "no_match"
  | "ambiguous"
  | "unsupported"
  | "unavailable"
  | "clarification_required";

export interface OntologyShadowResult {
  status: OntologyStatus;
  ontology_sql: string | null;
  summary: string;
  diff: {
    changed: boolean;
    legacy_tables: string[];
    ontology_tables: string[];
  };
  evidence: {
    concepts: string[];
    properties: string[];
    relations: string[];
    rules: string[];
    data_sources: string[];
    mappings: string[];
  };
  package: {
    package_id: string;
    version: string;
    sha256: string;
  } | null;
  temporal_decisions?: TemporalEvidence[];
  temporal_decision?: TemporalEvidence | null;
}

export interface ConversationItem {
  id: number;
  title: string;
  context: string | null;
  last_message: string | null;
  updated_at: string;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  sql: string | null;
  query_id: number | null;
  trace: any[] | null;
  steps: any[] | null;
  generating: boolean;
  error: string | null;
  ontology_shadow: OntologyShadowResult | null;
  created_at: string;
}

export interface EditingSql {
  msgId: number;
  sql: string;
}
