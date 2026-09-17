export type DiagnosticDestination = "objects" | "relations";

export function diagnosticDestination(
  relatedIds: readonly string[],
  relationIds: readonly string[]
): DiagnosticDestination {
  const related = new Set(relatedIds);
  if (relationIds.some((id) => related.has(id))) return "relations";
  return "objects";
}
