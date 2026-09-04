export type WorkbenchStage =
  | "import"
  | "objects"
  | "relations"
  | "temporal"
  | "diagnostics"
  | "versions";

export interface WorkbenchStageDefinition {
  key: WorkbenchStage;
  number: string;
  title: string;
  description: string;
}

export const WORKBENCH_STAGES: readonly WorkbenchStageDefinition[] = [
  { key: "import", number: "01", title: "导入元数据", description: "载入对象与字段定义" },
  { key: "objects", number: "02", title: "对象与字段", description: "校准业务语义说明" },
  { key: "relations", number: "03", title: "关系", description: "确认跨对象关联路径" },
  { key: "temporal", number: "04", title: "自动账期", description: "按表名识别分区与默认账期" },
  { key: "diagnostics", number: "05", title: "诊断", description: "处理质量与一致性问题" },
  { key: "versions", number: "06", title: "发布版本", description: "固化并切换活动版本" },
];

interface WorkbenchSummaryInput {
  counts: {
    objects: number;
    fields: number;
    relations: number;
    temporalPolicies: number;
  };
  diagnostics: Array<{ severity: string }>;
  activeVersion?: { version: string } | null;
}

export function initialWorkbenchStage(objectCount: number): WorkbenchStage {
  return objectCount === 0 ? "import" : "objects";
}

export function workbenchStageSummary(
  stage: WorkbenchStage,
  overview: WorkbenchSummaryInput,
  versionCount: number
): string {
  const { counts } = overview;
  switch (stage) {
    case "import":
      return counts.objects === 0 ? "等待导入首批元数据" : `草稿含 ${counts.objects} 个对象`;
    case "objects":
      return `${counts.objects} 个对象 · ${counts.fields} 个字段`;
    case "relations":
      return `${counts.relations} 条已定义关系`;
    case "temporal":
      return `${counts.temporalPolicies} 项时间策略`;
    case "diagnostics": {
      const severityCount = (severity: string) =>
        overview.diagnostics.filter((item) => item.severity === severity).length;
      const pending = severityCount("confirmation_required");
      return `${severityCount("error")} 个错误${pending ? ` · ${pending} 项待确认` : ""}`;
    }
    case "versions":
      return `活动 ${overview.activeVersion?.version ?? "未发布"} · 共 ${versionCount} 个版本`;
  }
}
