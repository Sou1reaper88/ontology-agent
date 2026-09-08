import type { OntologyStatus } from "./types";

export interface OntologyStatusPresentation {
  title: string;
  description: string;
  tone: "success" | "neutral" | "warning";
}

const presentations: Record<OntologyStatus, OntologyStatusPresentation> = {
  generated: {
    title: "本体已参与生成",
    description: "SQL 已使用当前本体包中的语义与物理映射。",
    tone: "success",
  },
  no_match: {
    title: "本体未命中",
    description: "未找到可用于本次需求的本体对象或属性。",
    tone: "neutral",
  },
  ambiguous: {
    title: "本体匹配有歧义",
    description: "存在多个候选语义，当前无法唯一选择。",
    tone: "warning",
  },
  unsupported: {
    title: "当前能力暂不支持",
    description: "已识别语义，但当前映射或编译能力无法完成生成。",
    tone: "neutral",
  },
  unavailable: {
    title: "本体链路不可用",
    description: "本体影子链路当前无法提供结果。",
    tone: "warning",
  },
  clarification_required: {
    title: "业务账期需要确认",
    description: "需求中存在冲突或不完整的业务账期信息。",
    tone: "warning",
  },
};

export function ontologyStatusPresentation(
  status: OntologyStatus
): OntologyStatusPresentation {
  return presentations[status];
}
