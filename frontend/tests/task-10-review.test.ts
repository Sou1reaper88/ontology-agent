import { diagnosticDestination } from "../src/features/ontology-package/diagnosticRouting";
import { validatedFormValues } from "../src/features/ontology-package/formValidation";
import { relationId } from "../src/features/ontology-package/relationId";

declare const process: { exitCode: number };

function equal(actual: string, expected: string, label: string): void {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${expected}, received ${actual}`);
  }
}

const firstRawId = "relation/a--b--c";
const secondRawId = "relation/a--b--c";
equal(firstRawId, secondRawId, "adversarial endpoint pairs collide with raw concatenation");

const firstStableId = relationId("a--b", "c");
const secondStableId = relationId("a", "b--c");
if (firstStableId === secondStableId) {
  throw new Error("length-prefixed relation IDs must remain injective");
}
equal(firstStableId, relationId("a--b", "c"), "relation IDs are deterministic");

equal(
  diagnosticDestination(["relation/order-account"], ["relation/order-account"], []),
  "relations",
  "generic diagnostics route to a related relation"
);
equal(
  diagnosticDestination(
    ["object/order", "field/order-date"],
    [],
    [{ objectId: "object/order", partitionFieldId: "field/order-date" }]
  ),
  "temporal",
  "generic diagnostics route to the matching temporal policy"
);
equal(
  diagnosticDestination(["object/order"], [], []),
  "objects",
  "unmatched diagnostics route to the object editor"
);

async function verifyValidationHandling(): Promise<void> {
  const invalid = await validatedFormValues(async () => Promise.reject(new Error("invalid form")));
  if (invalid !== null) {
    throw new Error("rejected form validation must be handled without surfacing an API error");
  }
  const valid = await validatedFormValues(async () => ({ version: "1.2.0" }));
  equal(valid?.version ?? "", "1.2.0", "valid form values are retained");
}

void verifyValidationHandling().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
