/** Return a stable, injective relation identifier for two field identifiers. */
export function relationId(sourceFieldId: string, targetFieldId: string): string {
  return `relation/${sourceFieldId.length}:${sourceFieldId}--${targetFieldId.length}:${targetFieldId}`;
}
