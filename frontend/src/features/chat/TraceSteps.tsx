import { Collapse, Steps } from "antd";
import "./chat-components.css";

interface Props {
  steps: any[];
  generating?: boolean;
}

export function TraceSteps({ steps, generating }: Props) {
  const items = steps.map((step, index) => {
    let status: "wait" | "process" | "finish" | "error" = "finish";
    if (generating && index === steps.length - 1) status = "process";
    if (step.status === "error") status = "error";

    return {
      title: (
        <span className="trace-step-title">
          {step.label || step.node}
          {step.duration_ms != null ? (
            <span className="trace-duration"> · {step.duration_ms}ms</span>
          ) : null}
        </span>
      ),
      description: (
        <div className="trace-step-description">
          {step.summary || (status === "process" ? "执行中…" : "")}
          {step.node ? (
            <small>
              node: {step.node} · status: {step.status}
            </small>
          ) : null}
        </div>
      ),
      status,
    };
  });

  return (
    <Collapse
      className="trace-collapse"
      ghost
      size="small"
      items={[
        {
          key: "trace",
          label: (
            <span>
              处理过程摘要 · {steps.length} 步{generating ? " · 执行中" : ""}
            </span>
          ),
          children: (
            <>
              <p>展示处理说明与工具执行记录，不是内部推理原文。</p>
              <Steps size="small" direction="vertical" items={items} />
            </>
          ),
        },
      ]}
    />
  );
}
