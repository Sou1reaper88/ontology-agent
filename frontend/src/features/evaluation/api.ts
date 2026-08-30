import type { AxiosError } from "axios";
import client from "../../api/client";
import type {
  EvaluationCaseDetail,
  EvaluationCaseSummary,
  EvaluationRunSummary,
  ImportEvaluationInput,
} from "./types";

interface ApiErrorBody {
  detail?: { code?: string; message?: string; row_number?: number } | string;
}

export interface EvaluationCasePage {
  items: EvaluationCaseSummary[];
  total: number;
  page: number;
  page_size: number;
}

export const evaluationErrorMessage = (error: unknown, fallback: string): string => {
  const body = (error as AxiosError<ApiErrorBody>)?.response?.data;
  if (body && typeof body.detail === "object" && body.detail?.message) {
    const row = body.detail.row_number ? `（第 ${body.detail.row_number} 行）` : "";
    return `${body.detail.message}${row}`;
  }
  if (body && typeof body.detail === "string") return body.detail;
  return fallback;
};

export async function downloadEvaluationTemplate(): Promise<void> {
  const response = await client.get<Blob>("/evaluations/template", { responseType: "blob" });
  const disposition = String(response.headers["content-disposition"] || "");
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const fileName = match?.[1] || "sql-evaluation-template.xlsx";
  const url = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function importEvaluation(
  input: ImportEvaluationInput
): Promise<EvaluationRunSummary> {
  const form = new FormData();
  form.append("name", input.name);
  form.append("dialect", input.dialect);
  form.append("system_time", input.systemTime);
  form.append("file", input.file);
  const { data } = await client.post<EvaluationRunSummary>("/evaluations/import", form);
  return data;
}

export async function startEvaluation(runId: number): Promise<EvaluationRunSummary> {
  const { data } = await client.post<EvaluationRunSummary>(`/evaluations/${runId}/run`);
  return data;
}

export async function listEvaluations(): Promise<EvaluationRunSummary[]> {
  const { data } = await client.get<EvaluationRunSummary[]>("/evaluations");
  return data;
}

export async function fetchEvaluation(runId: number): Promise<EvaluationRunSummary> {
  const { data } = await client.get<EvaluationRunSummary>(`/evaluations/${runId}`);
  return data;
}

export async function deleteEvaluation(runId: number): Promise<void> {
  await client.delete(`/evaluations/${runId}`);
}

export async function listEvaluationCases(
  runId: number,
  params: Record<string, string | number | boolean | undefined>
): Promise<EvaluationCasePage> {
  const { data } = await client.get<EvaluationCasePage>(`/evaluations/${runId}/cases`, {
    params,
  });
  return data;
}

export async function fetchEvaluationCase(
  runId: number,
  caseId: number
): Promise<EvaluationCaseDetail> {
  const { data } = await client.get<EvaluationCaseDetail>(
    `/evaluations/${runId}/cases/${caseId}`
  );
  return data;
}
