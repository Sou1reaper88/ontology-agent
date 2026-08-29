import type { DraftObject } from "./types";

export function filterOntologyObjects(objects: DraftObject[], query: string): DraftObject[] {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return objects;
  return objects.filter((item) =>
    [item.label, item.physicalName, item.description]
      .filter((value): value is string => Boolean(value))
      .some((value) => value.toLocaleLowerCase().includes(normalized))
  );
}

export function selectedOntologyObject(
  objects: DraftObject[],
  objectId: string | null
): DraftObject | null {
  if (!objectId) return null;
  return objects.find((item) => item.id === objectId) ?? null;
}

export function withSelectedObject(
  params: URLSearchParams,
  objectId: string | null
): URLSearchParams {
  const next = new URLSearchParams(params);
  if (objectId) next.set("object", objectId);
  else next.delete("object");
  return next;
}
