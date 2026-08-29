import {
  filterOntologyObjects,
  selectedOntologyObject,
  withSelectedObject,
} from "../src/features/ontology-package/objectNavigation";
import type { DraftObject } from "../src/features/ontology-package/types";

const object = (
  id: string,
  physicalName: string,
  label: string,
  description: string
): DraftObject => ({
  id,
  physicalName,
  label,
  description,
  fields: [],
  status: "active",
  priority: 100,
});

const objects = [
  object("urn:table/customer", "D_CUSTOMER", "客户主表", "客户基础信息"),
  object("urn:table/order", "F_ORDER", "订单明细", "交易订单事实"),
];

if (filterOntologyObjects(objects, " 客户 ").map((item) => item.id).join() !== objects[0].id) {
  throw new Error("Chinese label search must ignore surrounding whitespace");
}
if (filterOntologyObjects(objects, "f_order")[0]?.id !== objects[1].id) {
  throw new Error("physical name search must be case-insensitive");
}
if (filterOntologyObjects(objects, "交易订单")[0]?.id !== objects[1].id) {
  throw new Error("description search must be supported");
}
if (selectedOntologyObject(objects, objects[0].id)?.physicalName !== "D_CUSTOMER") {
  throw new Error("valid object selection must resolve");
}
if (selectedOntologyObject(objects, "missing") !== null) {
  throw new Error("stale object selection must not resolve");
}

const original = new URLSearchParams("stage=objects");
const selected = withSelectedObject(original, "urn:table/customer?a=1");
if (selected.get("object") !== "urn:table/customer?a=1" || selected.get("stage") !== "objects") {
  throw new Error("selection must preserve unrelated query parameters");
}
if (original.has("object")) {
  throw new Error("selection must not mutate caller parameters");
}
const cleared = withSelectedObject(selected, null);
if (cleared.has("object") || cleared.get("stage") !== "objects") {
  throw new Error("back navigation must only remove object selection");
}
