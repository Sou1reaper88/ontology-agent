import {
  includesRelationSearch,
  relationMatchesSearch,
} from "../src/features/ontology-package/relationSearch";
import type { DraftObject, DraftRelation } from "../src/features/ontology-package/types";

function assert(value: unknown, label: string): asserts value {
  if (!value) throw new Error(label);
}

const objects: DraftObject[] = [
  {
    id: "object/customer",
    physicalName: "D_CUSTOMER_M",
    label: "客户主表",
    description: null,
    status: "active",
    priority: 100,
    fields: [
      {
        id: "field/customer-id",
        physicalName: "CUSTOMER_KEY",
        label: "客户编号",
        description: null,
        xsdType: "string",
        primaryKey: true,
        title: true,
        aliases: [],
        status: "active",
        priority: 100,
      },
    ],
  },
  {
    id: "object/order",
    physicalName: "D_ORDER_D",
    label: "订单明细",
    description: null,
    status: "active",
    priority: 100,
    fields: [
      {
        id: "field/order-customer-id",
        physicalName: "CUSTOMER_ID",
        label: "订单客户编号",
        description: null,
        xsdType: "string",
        primaryKey: false,
        title: false,
        aliases: [],
        status: "active",
        priority: 100,
      },
    ],
  },
];

const relation: DraftRelation = {
  id: "relation/customer-order",
  label: "订单归属客户",
  sourceObjectId: "object/order",
  sourceFieldId: "field/order-customer-id",
  targetObjectId: "object/customer",
  targetFieldId: "field/customer-id",
  cardinality: "many_to_one",
  status: "active",
  priority: 100,
  confirmed: true,
};

assert(includesRelationSearch(" customer ", "CUSTOMER_ID"), "physical name is case-insensitive");
assert(includesRelationSearch("客户", "客户主表", "D_CUSTOMER_M"), "Chinese label matches");
assert(relationMatchesSearch("订单归属", objects, relation), "relation label matches");
assert(relationMatchesSearch("d_order_d", objects, relation), "source object matches");
assert(relationMatchesSearch("d_customer_m", objects, relation), "target object matches");
assert(relationMatchesSearch("订单客户编号", objects, relation), "source field matches");
assert(relationMatchesSearch("customer_key", objects, relation), "target field matches");
assert(relationMatchesSearch("   ", objects, relation), "blank search returns all relations");
assert(!relationMatchesSearch("不存在", objects, relation), "unmatched relation is rejected");

const missingEndpoint = { ...relation, sourceObjectId: "object/missing" };
assert(
  relationMatchesSearch("已删除对象或字段", objects, missingEndpoint),
  "missing endpoint remains searchable"
);
