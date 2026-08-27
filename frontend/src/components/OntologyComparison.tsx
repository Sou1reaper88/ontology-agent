import { CopyOutlined, EditOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Descriptions, Row, Space, Tag, Typography } from "antd";

const { Text } = Typography;

export interface TemporalEvidence {
  partition_field: string;
  grain: "day" | "month";
  policy_source: "ontology";
  system_time: string;
  user_time: string | null;
  source: "explicit_absolute" | "explicit_relative" | "ontology_default";
  default_strategy: "t_minus_2" | "previous_complete_month";
  resolved_start: string;
  resolved_end: string;
  safety_status: "bounded";
  explanation: string;
}

export interface OntologyShadowResult {
  status:
    | "generated"
    | "no_match"
    | "ambiguous"
    | "unsupported"
    | "unavailable"
    | "clarification_required";
  ontology_sql: string | null;
  summary: string;
  diff: {
    changed: boolean;
    legacy_tables: string[];
    ontology_tables: string[];
  };
  evidence: {
    concepts: string[];
    properties: string[];
    relations: string[];
    rules: string[];
    data_sources: string[];
    mappings: string[];
  };
  package: {
    package_id: string;
    version: string;
    sha256: string;
  } | null;
  temporal_decisions?: TemporalEvidence[];
  temporal_decision?: TemporalEvidence | null;
}

interface Props {
  legacySql: string | null;
  result: OntologyShadowResult;
  onEditLegacy: () => void;
  onCopyOntology: (sql: string) => void;
}

const statusTitles: Record<Exclude<OntologyShadowResult["status"], "generated">, string> = {
  no_match: "本体未命中",
  ambiguous: "本体匹配有歧义",
  unsupported: "本体映射暂不支持",
  unavailable: "本体影子链路不可用",
  clarification_required: "业务账期需要确认",
};

const sourceLabels: Record<TemporalEvidence["source"], string> = {
  explicit_absolute: "用户明确指定",
  explicit_relative: "用户相对时间",
  ontology_default: "本体默认推算",
};

const strategyLabels: Record<TemporalEvidence["default_strategy"], string> = {
  t_minus_2: "T-2",
  previous_complete_month: "上一个完整自然月",
};

function SqlBlock({ sql }: { sql: string }) {
  return (
    <pre
      style={{
        margin: "10px 0 0",
        minHeight: 92,
        whiteSpace: "pre-wrap",
        overflowWrap: "anywhere",
        background: "#141414",
        color: "#d4d4d4",
        borderRadius: 6,
        padding: 10,
        fontSize: 12,
      }}
    >
      {sql}
    </pre>
  );
}

function EvidenceTags({ label, values }: { label: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <Space size={[4, 4]} wrap>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {label}
      </Text>
      {values.map((value) => (
        <Tag key={`${label}-${value}`}>{value}</Tag>
      ))}
    </Space>
  );
}

export function OntologyComparison({
  legacySql,
  result,
  onEditLegacy,
  onCopyOntology,
}: Props) {
  const temporalDecisions =
    result.temporal_decisions ?? (result.temporal_decision ? [result.temporal_decision] : []);
  if (result.status !== "generated" || !result.ontology_sql) {
    return (
      <Alert
        style={{ marginTop: 10 }}
        type={
          result.status === "unavailable" || result.status === "clarification_required"
            ? "warning"
            : "info"
        }
        showIcon
        message={
          result.status === "generated" ? "本体 SQL 未生成" : statusTitles[result.status]
        }
        description={result.summary}
      />
    );
  }

  return (
    <div style={{ marginTop: 10 }}>
      <Alert
        type={result.diff.changed ? "success" : "info"}
        showIcon
        message={result.summary}
        description={
          result.diff.changed
            ? `表映射：${result.diff.legacy_tables.join("、") || "未识别"} → ${
                result.diff.ontology_tables.join("、") || "未识别"
              }`
            : "两条 SQL 规范化后内容相同"
        }
      />
      <Row gutter={[10, 10]} style={{ marginTop: 10 }}>
        <Col xs={24} xl={12}>
          <Card
            size="small"
            title="现有 Agent SQL"
            extra={<Tag>可执行</Tag>}
            style={{ height: "100%" }}
          >
            <SqlBlock sql={legacySql || "未生成 SQL"} />
            {legacySql && (
              <Button size="small" icon={<EditOutlined />} onClick={onEditLegacy}>
                编辑现有 SQL
              </Button>
            )}
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card
            size="small"
            title="本体驱动 SQL"
            extra={<Tag color="purple">影子预览</Tag>}
            style={{ height: "100%", borderColor: "#b37feb" }}
          >
            <SqlBlock sql={result.ontology_sql} />
            <Space direction="vertical" size={6} style={{ width: "100%" }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                影子预览，不会自动执行
              </Text>
              <Button
                size="small"
                icon={<CopyOutlined />}
                onClick={() => onCopyOntology(result.ontology_sql!)}
              >
                复制本体 SQL
              </Button>
            </Space>
          </Card>
        </Col>
      </Row>
      {temporalDecisions.map((decision, index) => (
        <Card
          key={`${decision.partition_field}-${index}`}
          size="small"
          title={temporalDecisions.length > 1 ? `业务账期决策 ${index + 1}` : "业务账期决策"}
          extra={<Tag color="green">已添加有界分区约束</Tag>}
          style={{ marginTop: 10, borderColor: "#95de64" }}
        >
          <Descriptions size="small" column={{ xs: 1, sm: 2, xl: 4 }}>
            <Descriptions.Item label="分区字段">
              <Text code>{decision.partition_field}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="分区粒度">
              {decision.grain === "month" ? "月" : "日"}
            </Descriptions.Item>
            <Descriptions.Item label="策略来源">
              {sourceLabels[decision.source]}
            </Descriptions.Item>
            <Descriptions.Item label="系统时间">
              {decision.system_time}
            </Descriptions.Item>
            <Descriptions.Item label="用户时间">
              {decision.user_time || "未指定"}
            </Descriptions.Item>
            <Descriptions.Item label="默认算法">
              {strategyLabels[decision.default_strategy]}
            </Descriptions.Item>
            <Descriptions.Item label="最终账期">
              <Text strong>
                {decision.resolved_start === decision.resolved_end
                  ? decision.resolved_start
                  : `${decision.resolved_start} 至 ${decision.resolved_end}`}
              </Text>
            </Descriptions.Item>
            <Descriptions.Item label="安全状态">
              <Tag color="green">有界</Tag>
            </Descriptions.Item>
          </Descriptions>
          <Text type="secondary">{decision.explanation}</Text>
        </Card>
      ))}
      <Card
        size="small"
        title="本体依据"
        extra={
          result.package && (
            <Tag color="blue">
              {result.package.package_id}@{result.package.version} · {result.package.sha256}
            </Tag>
          )
        }
        style={{ marginTop: 10, background: "#fafafa" }}
      >
        <Space direction="vertical" size={6}>
          <EvidenceTags label="概念" values={result.evidence.concepts} />
          <EvidenceTags label="属性" values={result.evidence.properties} />
          <EvidenceTags label="关系" values={result.evidence.relations || []} />
          <EvidenceTags label="规则" values={result.evidence.rules} />
          <EvidenceTags label="数据源" values={result.evidence.data_sources} />
          <EvidenceTags label="映射" values={result.evidence.mappings} />
        </Space>
      </Card>
    </div>
  );
}
