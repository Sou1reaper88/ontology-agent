export type DiagnosticDestination = "objects" | "relations" | "temporal";

export interface TemporalPolicyOwner {
  objectId: string;
  partitionFieldId: string;
}

export function diagnosticDestination(
  relatedIds: readonly string[],
  relationIds: readonly string[],
  temporalPolicies: readonly TemporalPolicyOwner[]
): DiagnosticDestination {
  const related = new Set(relatedIds);
  if (relationIds.some((id) => related.has(id))) return "relations";
  if (
    temporalPolicies.some(
      (policy) => related.has(policy.objectId) && related.has(policy.partitionFieldId)
    )
  ) {
    return "temporal";
  }
  return "objects";
}
