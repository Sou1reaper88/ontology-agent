interface SqlPresentationMessage {
  sql: string | null;
  query_id: number | null;
  ontology_shadow: { status: string } | null;
  program: { program_id: string } | null;
}

export interface SqlPresentation {
  kind: "program" | "query";
  label: "取数程序" | "现有 SQL";
  showComparison: boolean;
  showSqlPanel: boolean;
  allowEdit: boolean;
  allowExecute: boolean;
}

const LEGACY_PROGRAM_SQL_HEADING = "## SQL 脚本";

export function getAssistantContent(content: string, isProgram: boolean): string {
  if (!isProgram) return content;
  const headingIndex = content.indexOf(LEGACY_PROGRAM_SQL_HEADING);
  return headingIndex >= 0 ? content.slice(0, headingIndex).trimEnd() : content;
}

export function getSqlPresentation(
  message: SqlPresentationMessage,
  isEditing: boolean
): SqlPresentation {
  const isProgram = message.program !== null;
  const hasSql = Boolean(message.sql);
  return {
    kind: isProgram ? "program" : "query",
    label: isProgram ? "取数程序" : "现有 SQL",
    showComparison:
      !isProgram && message.ontology_shadow !== null && !isEditing,
    showSqlPanel:
      hasSql &&
      (isProgram ||
        message.ontology_shadow?.status !== "generated" ||
        isEditing),
    allowEdit: hasSql && !isProgram,
    allowExecute: Boolean(message.query_id) && !isProgram && !isEditing,
  };
}
