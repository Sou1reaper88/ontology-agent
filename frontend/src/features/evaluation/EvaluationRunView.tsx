import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Modal,
  Pagination,
  Progress,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  message,
} from "antd";
import { useNavigate } from "react-router-dom";
import {
  deleteEvaluation,
  evaluationErrorMessage,
  fetchEvaluation,
  fetchEvaluationCase,
  listEvaluationCases,
} from "./api";
import type {
  CandidateEvaluation,
  DimensionResult,
  EvaluationCaseDetail,
  EvaluationCaseFilters,
  EvaluationCaseSummary,
  EvaluationRunSummary,
  MetricCount,
} from "./types";
import {
  caseQueryParams,
  dimensionDifferenceLabel,
  evaluationStatusPresentation,
  formatMetric,
  primaryDiagnosisPresentation,
  scoreLabel,
} from "./viewModel";

const DIMENSIONS = [
  ["tables", "物理表"],
  ["fields", "输出字段"],
  ["predicates", "过滤与口径"],
  ["joins", "关联关系"],
  ["partition", "分区与账期"],
  ["shape", "查询形态"],
] as const;

const dimensionStatus: Record<string, string> = {
  matched: "一致",
  partial: "部分一致",
  mismatched: "不一致",
  not_applicable: "不适用",
  unscorable: "不可评分",
};

function MetricCard({ label, metric }: { label: string; metric?: MetricCount }) {
  return (
    <article className="evaluation-metric-card">
      <span>{label}</span>
      <strong>{metric ? formatMetric(metric.numerator, metric.denominator) : "—"}</strong>
    </article>
  );
}

function SqlPanel({ title, sql }: { title: string; sql: string | null }) {
  const copy = async () => {
    if (!sql) return;
    await navigator.clipboard.writeText(sql);
    message.success(`已复制${title}`);
  };
  return (
    <section className="evaluation-sql-panel">
      <header><strong>{title}</strong>{sql ? <Button type="text" onClick={() => void copy()}>复制</Button> : null}</header>
      {sql ? <pre>{sql}</pre> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未生成 SQL" />}
    </section>
  );
}

function DimensionDetails({ comparison }: { comparison: CandidateEvaluation | null }) {
  if (!comparison) return <Empty description="暂无结构比较" />;
  return (
    <div className="evaluation-dimension-details">
      {DIMENSIONS.map(([key, label]) => {
        const result: DimensionResult | undefined = comparison.dimensions[key];
        if (!result) return null;
        return (
          <article key={key}>
            <header><strong>{label}</strong><Tag>{dimensionStatus[result.status] || result.status}</Tag></header>
            {(["missing", "extra", "conflicts"] as const).map((kind) =>
              result[kind]?.length ? (
                <div className="evaluation-difference" key={kind}>
                  <span>{dimensionDifferenceLabel(kind)}</span>
                  <code>{result[kind].join("\n")}</code>
                </div>
              ) : null
            )}
          </article>
        );
      })}
    </div>
  );
}

function CaseDrawer({ runId, detail, onClose }: { runId: number; detail: EvaluationCaseDetail | null; onClose: () => void }) {
  const diagnosis = primaryDiagnosisPresentation(detail?.primary_diagnosis);
  return (
    <Drawer
      title={detail ? `案例 #${detail.case_number}` : "案例详情"}
      open={Boolean(detail)}
      onClose={onClose}
      width="min(1180px, 96vw)"
      destroyOnClose
    >
      {detail ? (
        <div className="evaluation-case-detail" data-run-id={runId}>
          <section className="evaluation-diagnosis-banner" data-tone={diagnosis.tone}>
            <strong>{diagnosis.label}</strong><span>{diagnosis.description}</span>
          </section>
          <Descriptions size="small" column={{ xs: 1, md: 3 }} bordered>
            <Descriptions.Item label="需求原文" span={3}>{detail.requirement}</Descriptions.Item>
            <Descriptions.Item label="Legacy 得分">{scoreLabel(detail.legacy_score)}</Descriptions.Item>
            <Descriptions.Item label="本体得分">{scoreLabel(detail.ontology_score)}</Descriptions.Item>
            <Descriptions.Item label="本体状态">{detail.ontology_status || "—"}</Descriptions.Item>
          </Descriptions>
          <Tabs
            className="evaluation-sql-tabs"
            items={[
              { key: "reference", label: "真实 SQL", children: <SqlPanel title="真实 SQL" sql={detail.reference_sql} /> },
              { key: "legacy", label: "Legacy SQL", children: <SqlPanel title="Legacy SQL" sql={detail.legacy_sql} /> },
              { key: "ontology", label: "本体 SQL", children: <SqlPanel title="本体 SQL" sql={detail.ontology_sql} /> },
            ]}
          />
          <div className="evaluation-comparison-grid">
            <Card title="Legacy 结构差异" size="small"><DimensionDetails comparison={detail.legacy_comparison} /></Card>
            <Card title="本体结构差异" size="small"><DimensionDetails comparison={detail.ontology_comparison} /></Card>
          </div>
          <Card title="本体依据与时间决策" size="small">
            <pre className="evaluation-json-evidence">{JSON.stringify({ evidence: detail.ontology_evidence, temporal_decisions: detail.temporal_decisions }, null, 2)}</pre>
          </Card>
        </div>
      ) : null}
    </Drawer>
  );
}

export default function EvaluationRunView({ runId }: { runId: number }) {
  const navigate = useNavigate();
  const [run, setRun] = useState<EvaluationRunSummary | null>(null);
  const [cases, setCases] = useState<EvaluationCaseSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<EvaluationCaseDetail | null>(null);
  const [filters, setFilters] = useState<EvaluationCaseFilters>({ path: "ontology", page: 1, pageSize: 20 });

  const refreshRun = useCallback(async () => {
    try { setRun(await fetchEvaluation(runId)); }
    catch (error) { message.error(evaluationErrorMessage(error, "评测任务加载失败")); }
    finally { setLoading(false); }
  }, [runId]);

  const refreshCases = useCallback(async () => {
    try {
      const page = await listEvaluationCases(runId, caseQueryParams(filters));
      setCases(page.items); setTotal(page.total);
    } catch (error) { message.error(evaluationErrorMessage(error, "评测案例加载失败")); }
  }, [filters, runId]);

  useEffect(() => { void refreshRun(); }, [refreshRun]);
  useEffect(() => { void refreshCases(); }, [refreshCases]);
  useEffect(() => {
    if (run?.status !== "running") return;
    const timer = window.setInterval(() => { void refreshRun(); void refreshCases(); }, 1500);
    return () => window.clearInterval(timer);
  }, [refreshCases, refreshRun, run?.status]);

  const diagnosisRows = useMemo(
    () => Object.entries(run?.summary?.diagnoses?.ontology || {}).sort((a, b) => b[1] - a[1]),
    [run?.summary?.diagnoses?.ontology]
  );

  if (loading && !run) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;
  if (!run) return <Empty description="评测任务不存在或无权访问" />;
  const status = evaluationStatusPresentation(run.status);
  const progress = run.total_cases ? Math.round((run.processed_cases / run.total_cases) * 100) : 0;

  const remove = () => Modal.confirm({
    title: "删除评测任务？",
    content: "会同时删除需求原文、真实 SQL、Legacy SQL 和本体 SQL，且无法恢复。",
    okText: "确认删除",
    okButtonProps: { danger: true },
    cancelText: "取消",
    onOk: async () => {
      try { await deleteEvaluation(run.id); message.success("评测任务已删除"); navigate("/evaluation"); }
      catch (error) { message.error(evaluationErrorMessage(error, "删除失败")); }
    },
  });

  const columns = [
    { title: "案例", dataIndex: "case_number", width: 80, render: (value: number) => `#${value}` },
    { title: "Legacy", width: 130, render: (_: unknown, item: EvaluationCaseSummary) => <span>{scoreLabel(item.legacy_score)} {item.legacy_strict_pass ? <Tag color="success">通过</Tag> : null}</span> },
    { title: "本体状态", dataIndex: "ontology_status", width: 140, render: (value: string | null) => value || "未运行" },
    { title: "本体", width: 130, render: (_: unknown, item: EvaluationCaseSummary) => <span>{scoreLabel(item.ontology_score)} {item.ontology_strict_pass ? <Tag color="success">通过</Tag> : null}</span> },
    { title: "主失败原因", render: (_: unknown, item: EvaluationCaseSummary) => primaryDiagnosisPresentation(item.primary_diagnosis).label },
    { title: "复核", width: 90, render: (_: unknown, item: EvaluationCaseSummary) => item.manual_review ? <Tag>人工复核</Tag> : "—" },
    { title: "耗时", dataIndex: "duration_ms", width: 90, render: (value: number | null) => value === null ? "—" : `${value} ms` },
    { title: "", width: 80, render: (_: unknown, item: EvaluationCaseSummary) => <Button type="link" onClick={async () => {
      try { setDetail(await fetchEvaluationCase(runId, item.id)); }
      catch (error) { message.error(evaluationErrorMessage(error, "案例详情加载失败")); }
    }}>详情</Button> },
  ];

  return (
    <section className="evaluation-workbench">
      <header className="evaluation-run-hero">
        <Button className="evaluation-back" type="text" onClick={() => navigate("/evaluation")}>← 返回评测任务</Button>
        <div className="evaluation-run-title">
          <div><span className="evaluation-eyebrow">EVALUATION RUN #{run.id}</span><h1>{run.name}</h1><p>{run.dialect.toUpperCase()} · 基准时间 {run.system_time} · 本体版本 {run.package_version || "尚未锁定"}</p></div>
          <Space><Tag data-tone={status.tone}>{status.label}</Tag><Button danger onClick={remove}>删除任务</Button></Space>
        </div>
        <div className="evaluation-run-progress"><Progress percent={progress} showInfo={false} /><span>{run.processed_cases}/{run.total_cases} 条案例</span></div>
      </header>

      <div className="evaluation-metric-grid">
        <MetricCard label="本体生成率" metric={run.summary?.ontology_generation} />
        <MetricCard label="Legacy 严格通过" metric={run.summary?.legacy.strict_pass} />
        <MetricCard label="本体严格通过" metric={run.summary?.ontology.strict_pass} />
        <article className="evaluation-metric-card"><span>本体平均分</span><strong>{scoreLabel(run.summary?.ontology.average_score)}</strong></article>
      </div>

      <div className="evaluation-analysis-grid">
        <Card title="六维正确率" bordered={false}>
          <Table
            rowKey="key"
            size="small"
            pagination={false}
            dataSource={DIMENSIONS.map(([key, label]) => ({ key, label, legacy: run.summary?.legacy.dimensions[key], ontology: run.summary?.ontology.dimensions[key] }))}
            columns={[
              { title: "维度", dataIndex: "label" },
              { title: "Legacy", dataIndex: "legacy", render: (value?: MetricCount) => value ? formatMetric(value.numerator, value.denominator) : "—" },
              { title: "本体", dataIndex: "ontology", render: (value?: MetricCount) => value ? formatMetric(value.numerator, value.denominator) : "—" },
            ]}
          />
        </Card>
        <Card title="本体失败分布" bordered={false}>
          {diagnosisRows.length ? <div className="evaluation-diagnosis-list">{diagnosisRows.map(([code, count]) => {
            const item = primaryDiagnosisPresentation(code); const percent = run.total_cases ? Math.round((count / run.total_cases) * 100) : 0;
            return <article key={code}><div><strong>{item.label}</strong><span>{count} 条</span></div><Progress percent={percent} showInfo={false} size="small" /></article>;
          })}</div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无失败归因" />}
        </Card>
      </div>

      <Card className="evaluation-case-card" bordered={false}>
        <div className="evaluation-case-toolbar">
          <div><span className="evaluation-eyebrow">CASE EXPLORER</span><h2>案例明细</h2></div>
          <Space wrap>
            <Select value={filters.path} style={{ width: 120 }} onChange={(path) => setFilters((old) => ({ ...old, path, page: 1 }))} options={[{ label: "本体路径", value: "ontology" }, { label: "Legacy 路径", value: "legacy" }]} />
            <Select allowClear placeholder="严格通过" style={{ width: 125 }} onChange={(strictPass) => setFilters((old) => ({ ...old, strictPass, page: 1 }))} options={[{ label: "通过", value: true }, { label: "未通过", value: false }]} />
            <Select allowClear placeholder="本体状态" style={{ width: 150 }} onChange={(ontologyStatus) => setFilters((old) => ({ ...old, ontologyStatus, page: 1 }))} options={["generated", "no_match", "ambiguous", "unsupported", "unavailable"].map((value) => ({ label: value, value }))} />
            <Select allowClear placeholder="人工复核" style={{ width: 130 }} onChange={(manualReview) => setFilters((old) => ({ ...old, manualReview, page: 1 }))} options={[{ label: "需要复核", value: true }, { label: "无需复核", value: false }]} />
          </Space>
        </div>
        <Table rowKey="id" columns={columns} dataSource={cases} pagination={false} scroll={{ x: 980 }} locale={{ emptyText: "没有符合条件的案例" }} />
        <Pagination current={filters.page} pageSize={filters.pageSize} total={total} showSizeChanger onChange={(page, pageSize) => setFilters((old) => ({ ...old, page, pageSize }))} />
      </Card>
      <CaseDrawer runId={runId} detail={detail} onClose={() => setDetail(null)} />
    </section>
  );
}
