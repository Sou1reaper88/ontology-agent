import type { DraftObject, DraftRelation } from "./types";

const MISSING_ENDPOINT = "已删除对象或字段";

function normalized(value: string | null | undefined): string {
  return (value ?? "").trim().toLocaleLowerCase();
}

export function includesRelationSearch(
  search: string,
  ...values: Array<string | null | undefined>
): boolean {
  const query = normalized(search);
  if (!query) return true;
  return values.some((value) => normalized(value).includes(query));
}

function endpointValues(
  objects: DraftObject[],
  objectId: string,
  fieldId: string
): string[] {
  const object = objects.find((item) => item.id === objectId);
  const field = object?.fields.find((item) => item.id === fieldId);
  if (!object || !field) return [MISSING_ENDPOINT];
  return [object.label ?? "", object.physicalName, field.label ?? "", field.physicalName];
}

export function relationMatchesSearch(
  search: string,
  objects: DraftObject[],
  relation: DraftRelation
): boolean {
  return includesRelationSearch(
    search,
    relation.label,
    ...endpointValues(objects, relation.sourceObjectId, relation.sourceFieldId),
    ...endpointValues(objects, relation.targetObjectId, relation.targetFieldId)
  );
}
