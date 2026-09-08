import { activeNavigationKey } from "../src/components/navigation";
import {
  caseQueryParams,
  dimensionDifferenceLabel,
  evaluationStatusPresentation,
  formatMetric,
  primaryDiagnosisPresentation,
  scoreLabel,
} from "../src/features/evaluation/viewModel";

if (formatMetric(3, 7) !== "3/7（42.9%）") {
  throw new Error("metric must include numerator, denominator and percentage");
}
if (formatMetric(0, 0) !== "暂无可评分案例") {
  throw new Error("zero denominator must not be rendered as zero percent");
}
if (primaryDiagnosisPresentation("ontology_no_match").label !== "对象概念未命中") {
  throw new Error("ontology failure must be actionable");
}
if (primaryDiagnosisPresentation("partition_mismatch").tone !== "warning") {
  throw new Error("partition mismatch must use warning presentation");
}
if (evaluationStatusPresentation("running").label !== "评测中") {
  throw new Error("running status must be explicit");
}
if (evaluationStatusPresentation("failed").tone !== "danger") {
  throw new Error("failed task must use danger presentation");
}
if (scoreLabel(null) !== "不可评分" || scoreLabel(0) !== "0 分") {
  throw new Error("unscorable must not be rendered as zero");
}
if (activeNavigationKey("/evaluation/12") !== "evaluation") {
  throw new Error("evaluation details must keep navigation selected");
}
const params = caseQueryParams({
  path: "ontology",
  strictPass: false,
  ontologyStatus: "",
  diagnosisCode: "field_mismatch",
  manualReview: undefined,
  page: 2,
  pageSize: 20,
});
if (
  params.strict_pass !== false ||
  params.diagnosis_code !== "field_mismatch" ||
  "ontology_status" in params ||
  params.page !== 2
) {
  throw new Error("case filters must preserve false and omit empty values");
}
if (dimensionDifferenceLabel("missing") !== "缺失") {
  throw new Error("dimension differences must use clear Chinese labels");
}
