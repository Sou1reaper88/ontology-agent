export type PresentationTone = "neutral" | "success" | "warning" | "danger";

export interface Presentation {
  label: string;
  description: string;
  tone: PresentationTone;
}

export function formatMetric(numerator: number, denominator: number): string {
  if (!denominator) return "暂无可评分案例";
  return `${numerator}/${denominator}（${((numerator / denominator) * 100).toFixed(1)}%）`;
}

export function scoreLabel(score: number | null | undefined): string {
  return score === null || score === undefined ? "不可评分" : `${score} 分`;
}

export function caseQueryParams(filters: EvaluationCaseFilters): Record<string, string | number | boolean> {
  const params: Record<string, string | number | boolean> = {
    path: filters.path,
    page: filters.page,
    page_size: filters.pageSize,
  };
  if (filters.strictPass !== undefined) params.strict_pass = filters.strictPass;
  if (filters.ontologyStatus) params.ontology_status = filters.ontologyStatus;
  if (filters.diagnosisCode) params.diagnosis_code = filters.diagnosisCode;
  if (filters.manualReview !== undefined) params.manual_review = filters.manualReview;
  return params;
}

export function dimensionDifferenceLabel(kind: "missing" | "extra" | "conflicts"): string {
  return { missing: "缺失", extra: "多余", conflicts: "冲突" }[kind];
}

const STATUS: Record<string, Presentation> = {
  pending: { label: "待开始", description: "任务已创建，尚未调用智能体", tone: "neutral" },
  running: { label: "评测中", description: "正在逐条生成并比较 SQL", tone: "warning" },
  completed: { label: "已完成", description: "所有案例均已进入终态", tone: "success" },
  failed: { label: "任务失败", description: "任务级错误阻止了继续处理", tone: "danger" },
  cancelled: { label: "已取消", description: "任务已安全停止", tone: "neutral" },
};

export function evaluationStatusPresentation(status: string): Presentation {
  return STATUS[status] || { label: status, description: "未知任务状态", tone: "neutral" };
}

const DIAGNOSES: Record<string, Presentation> = {
  ontology_no_match: {
    label: "对象概念未命中",
    description: "需求中的业务对象尚未被当前本体识别，优先补充对象名称、别名和描述。",
    tone: "warning",
  },
  ontology_ambiguous: {
    label: "对象概念存在歧义",
    description: "多个本体对象获得相同匹配结果，需要补充区分信息。",
    tone: "warning",
  },
  ontology_unsupported: {
    label: "本体映射不足",
    description: "对象已进入规划，但字段、关系或安全时间能力不足。",
    tone: "danger",
  },
  ontology_unavailable: {
    label: "本体服务不可用",
    description: "本体包或影子运行时没有正常加载。",
    tone: "danger",
  },
  partition_mismatch: {
    label: "账期或分区不一致",
    description: "候选 SQL 的分区字段、账期值或范围与真实 SQL 不同。",
    tone: "warning",
  },
  table_mismatch: {
    label: "物理表不一致",
    description: "候选 SQL 选择了错误、缺失或多余的物理表。",
    tone: "danger",
  },
  field_mismatch: {
    label: "输出字段不一致",
    description: "候选 SQL 的输出字段或表达式与真实 SQL 不同。",
    tone: "warning",
  },
  join_mismatch: {
    label: "关联关系不一致",
    description: "JOIN 类型、关系方向或关联键与真实 SQL 不同。",
    tone: "danger",
  },
  predicate_mismatch: {
    label: "业务过滤不一致",
    description: "过滤字段、运算符或业务口径值与真实 SQL 不同。",
    tone: "danger",
  },
  query_shape_mismatch: {
    label: "查询形态不一致",
    description: "聚合、分组、去重、排序或条数限制存在差异。",
    tone: "warning",
  },
  reference_parse_failed: {
    label: "真实 SQL 无法解析",
    description: "当前解析器不能可靠理解真实 SQL，本案例需要人工复核。",
    tone: "warning",
  },
  manual_review_required: {
    label: "需要人工复核",
    description: "当前静态评测无法给出可靠结论，不会按零分处理。",
    tone: "neutral",
  },
};

export function primaryDiagnosisPresentation(code: string | null | undefined): Presentation {
  if (!code) {
    return { label: "暂无失败归因", description: "案例尚未完成或全部匹配。", tone: "neutral" };
  }
  return DIAGNOSES[code] || { label: code, description: "查看案例结构差异。", tone: "neutral" };
}
import type { EvaluationCaseFilters } from "./types";
