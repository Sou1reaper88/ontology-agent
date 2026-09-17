import {
  WORKBENCH_STAGES,
  initialWorkbenchStage,
  workbenchStageSummary,
} from "../src/features/ontology-package/workbenchModel";
import { diagnosticDestination } from "../src/features/ontology-package/diagnosticRouting";
import { isLatestRequest } from "../src/features/ontology-package/requestSequence";

const overview = {
  counts: {
    objects: 3,
    fields: 24,
    relations: 2,
    temporalPolicies: 1,
  },
  diagnostics: [
    { severity: "error" },
    { severity: "warning" },
    { severity: "warning" },
    { severity: "confirmation_required" },
  ],
  activeVersion: { version: "1.4.0" },
};

if (initialWorkbenchStage(0) !== "import") {
  throw new Error("empty draft must start from import");
}
if (initialWorkbenchStage(3) !== "objects") {
  throw new Error("populated draft must start from objects");
}

const stageOrder = WORKBENCH_STAGES.map((stage) => stage.key).join(",");
if (stageOrder !== "import,objects,relations,feedback,diagnostics,versions") {
  throw new Error(`unexpected stage order: ${stageOrder}`);
}

if (workbenchStageSummary("objects", overview, 5) !== "3 个对象 · 24 个字段") {
  throw new Error("objects summary must use asset counts");
}
if (workbenchStageSummary("feedback", overview, 5) !== "人工复盘 SQL 与口径") {
  throw new Error("feedback stage must describe manual review");
}
if (workbenchStageSummary("diagnostics", overview, 5) !== "1 个错误 · 1 项待确认") {
  throw new Error("diagnostics summary must group severity counts");
}
if (workbenchStageSummary("versions", overview, 5) !== "活动 1.4.0 · 共 5 个版本") {
  throw new Error("versions summary must expose active and history counts");
}

if (diagnosticDestination(["object-1", "field-1"], ["relation-1"]) !== "objects") {
  throw new Error("temporal-policy-only diagnostic must navigate to objects");
}
if (diagnosticDestination(["relation-1"], ["relation-1"]) !== "relations") {
  throw new Error("relation diagnostic must navigate to relations");
}

const firstRequest = 1;
const secondRequest = 2;
if (isLatestRequest(firstRequest, secondRequest)) {
  throw new Error("an older feedback request must not commit state");
}
if (!isLatestRequest(secondRequest, secondRequest)) {
  throw new Error("the latest feedback request must be allowed to commit state");
}
