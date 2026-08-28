import type { OntologyShadowResult, TemporalEvidence } from "./types";
import { ontologyStatusPresentation } from "./ontologyPresentation";
import "./chat-components.css";

interface Props {
  result: OntologyShadowResult | null;
}

const sourceLabels: Record<TemporalEvidence["source"], string> = {
  explicit_absolute: "用户明确指定",
  explicit_relative: "用户相对时间",
  ontology_default: "本体默认推算",
};

const strategyLabels: Record<TemporalEvidence["default_strategy"], string> = {
  t_minus_2: "T-2",
  previous_complete_month: "上一个完整自然月",
};

function EvidenceGroup({ label, values }: { label: string; values: string[] }) {
  if (!values.length) return null;

  return (
    <section className="evidence-group">
      <h4>{label}</h4>
      <div className="evidence-values">
        {values.map((value) => (
          <code key={`${label}-${value}`}>{value}</code>
        ))}
      </div>
    </section>
  );
}

function TemporalDecision({ decision, index }: { decision: TemporalEvidence; index: number }) {
  const resolved =
    decision.resolved_start === decision.resolved_end
      ? decision.resolved_start
      : `${decision.resolved_start} 至 ${decision.resolved_end}`;

  return (
    <article className="temporal-decision">
      <header>
        <span>账期决策 {index + 1}</span>
        <strong>{resolved}</strong>
      </header>
      <dl>
        <div>
          <dt>分区字段</dt>
          <dd>
            <code>{decision.partition_field}</code>
          </dd>
        </div>
        <div>
          <dt>粒度</dt>
          <dd>{decision.grain === "month" ? "月" : "日"}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>{sourceLabels[decision.source]}</dd>
        </div>
        <div>
          <dt>算法</dt>
          <dd>{strategyLabels[decision.default_strategy]}</dd>
        </div>
        <div>
          <dt>系统时间</dt>
          <dd>{decision.system_time}</dd>
        </div>
        <div>
          <dt>用户时间</dt>
          <dd>{decision.user_time || "未指定"}</dd>
        </div>
      </dl>
      <p>{decision.explanation}</p>
    </article>
  );
}

export function OntologyEvidencePanel({ result }: Props) {
  if (!result) {
    return (
      <div className="evidence-empty">
        <span className="evidence-empty-mark" aria-hidden="true" />
        <h3>等待本体结果</h3>
        <p>选择一条带本体结果的智能体回答，在这里核对口径、账期和映射依据。</p>
      </div>
    );
  }

  const presentation = ontologyStatusPresentation(result.status);
  const temporalDecisions =
    result.temporal_decisions ??
    (result.temporal_decision ? [result.temporal_decision] : []);

  return (
    <div className="evidence-panel-content">
      <header className="evidence-status" data-tone={presentation.tone}>
        <span className="evidence-status-label">当前本体状态</span>
        <h3>{presentation.title}</h3>
        <p>{result.summary || presentation.description}</p>
      </header>

      {temporalDecisions.length ? (
        <section className="evidence-section">
          <div className="evidence-section-heading">
            <span>业务账期</span>
            <small>有界分区约束</small>
          </div>
          <div className="temporal-list">
            {temporalDecisions.map((decision, index) => (
              <TemporalDecision
                key={`${decision.partition_field}-${index}`}
                decision={decision}
                index={index}
              />
            ))}
          </div>
        </section>
      ) : null}

      {result.status === "generated" ? (
        <section className="evidence-section">
          <div className="evidence-section-heading">
            <span>语义依据</span>
            <small>来自当前本体快照</small>
          </div>
          <EvidenceGroup label="概念" values={result.evidence.concepts} />
          <EvidenceGroup label="属性" values={result.evidence.properties} />
          <EvidenceGroup label="关系" values={result.evidence.relations || []} />
          <EvidenceGroup label="规则" values={result.evidence.rules} />
          <EvidenceGroup label="数据源" values={result.evidence.data_sources} />
          <EvidenceGroup label="映射" values={result.evidence.mappings} />
        </section>
      ) : null}

      {result.package ? (
        <section className="evidence-package">
          <span>本体包</span>
          <strong>
            {result.package.package_id}@{result.package.version}
          </strong>
          <code title={result.package.sha256}>{result.package.sha256}</code>
        </section>
      ) : null}
    </div>
  );
}
