import { activeNavigationKey } from "../src/components/navigation";

function equal(actual: string, expected: string, label: string): void {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${expected}, received ${actual}`);
  }
}

equal(activeNavigationKey("/chat"), "chat", "chat route");
equal(activeNavigationKey("/ontology"), "ontology", "ontology route");
equal(activeNavigationKey("/query"), "query", "query route");
equal(activeNavigationKey("/result/query-17"), "query", "result belongs to query");
equal(activeNavigationKey("/admin"), "admin", "admin route");
equal(activeNavigationKey("/unknown"), "", "unknown route");
