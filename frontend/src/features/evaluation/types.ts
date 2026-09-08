export interface MetricCount {
  numerator: number;
  denominator: number;
  rate: number | null;
}

export interface CandidateSummary {
  total: number;
  scorable: number;
  strict_pass: MetricCount;
  manual_review: MetricCount;
  average_score: number | null;
  dimensions: Record<string, MetricCount>;
}

export interface EvaluationSummary {
  legacy: CandidateSummary;
  ontology: CandidateSummary;
  ontology_generation: MetricCount;
  ontology_no_match: MetricCount;
  diagnoses?: {
    legacy: Record<string, number>;
    ontology: Record<string, number>;
  };
}

export interface EvaluationRunSummary {
  id: number;
  name: string;
  dialect: string;
  system_time: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  total_cases: number;
  processed_cases: number;
  failed_cases: number;
  package_id: string | null;
  package_version: string | null;
  package_sha256: string | null;
  summary: EvaluationSummary | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ImportEvaluationInput {
  name: string;
  dialect: "hive";
  systemTime: string;
  file: File;
}

export interface DimensionResult {
  status: "matched" | "partial" | "mismatched" | "not_applicable" | "unscorable";
  score: number | null;
  missing: string[];
  extra: string[];
  conflicts: string[];
}

export interface CandidateEvaluation {
  score: number | null;
  strict_pass: boolean;
  manual_review: boolean;
  dimensions: Record<string, DimensionResult>;
  diagnosis_codes: string[];
}

export interface EvaluationCaseSummary {
  id: number;
  case_number: number;
  generation_status: string;
  ontology_status: string | null;
  legacy_score: number | null;
  legacy_strict_pass: boolean;
  ontology_score: number | null;
  ontology_strict_pass: boolean;
  primary_diagnosis: string | null;
  manual_review: boolean;
  duration_ms: number | null;
}

export interface EvaluationCaseDetail extends EvaluationCaseSummary {
  requirement: string;
  reference_sql: string;
  legacy_sql: string | null;
  ontology_sql: string | null;
  reference_structure: Record<string, unknown> | null;
  legacy_structure: Record<string, unknown> | null;
  ontology_structure: Record<string, unknown> | null;
  legacy_comparison: CandidateEvaluation | null;
  ontology_comparison: CandidateEvaluation | null;
  diagnosis_codes: { legacy?: string[]; ontology?: string[] } | null;
  ontology_evidence: Record<string, unknown> | null;
  temporal_decisions: Array<Record<string, unknown>> | null;
  error_code: string | null;
}

export interface EvaluationCaseFilters {
  path: "legacy" | "ontology";
  strictPass?: boolean;
  ontologyStatus?: string;
  diagnosisCode?: string;
  manualReview?: boolean;
  page: number;
  pageSize: number;
}
