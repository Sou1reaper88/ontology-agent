import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Upload,
  message,
} from "antd";
import type { UploadFile } from "antd";
import { useNavigate } from "react-router-dom";
import {
  downloadEvaluationTemplate,
  evaluationErrorMessage,
  importEvaluation,
  listEvaluations,
  startEvaluation,
} from "./api";
import type { EvaluationRunSummary } from "./types";
import { evaluationStatusPresentation, formatMetric, scoreLabel } from "./viewModel";
import "./evaluation.css";

interface FormValues {
  name: string;
  dialect: "hive";
  systemTime: string;
}

const localDate = (): string => {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
};

const metric = (run: EvaluationRunSummary, path: "legacy" | "ontology") => {
  const value = run.summary?.[path];
  return value ? formatMetric(value.strict_pass.numerator, value.strict_pass.denominator) : "—";
};

export default function EvaluationCenter() {
  const navigate = useNavigate();
  const [form] = Form.useForm<FormValues>();
  const [runs, setRuns] = useState<EvaluationRunSummary[]>([]);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setRuns(await listEvaluations());
    } catch (error) {
      message.error(evaluationErrorMessage(error, "评测任务加载失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const hasRunning = runs.some((run) => run.status === "running");
  useEffect(() => {
    if (!hasRunning) return;
    const timer = window.setInterval(() => void refresh(), 1500);
    return () => window.clearInterval(timer);
  }, [hasRunning, refresh]);

  const columns = useMemo(
    () => [
      {
        title: "评测任务",
        dataIndex: "name",
        render: (_: string, run: EvaluationRunSummary) => (
          <button className="evaluation-run-link" onClick={() => navigate(`/evaluation/${run.id}`)}>
            <strong>{run.name}</strong>
            <span>{run.dialect.toUpperCase()} · 基准时间 {run.system_time}</span>
          </button>
        ),
      },
      {
        title: "状态",
        width: 130,
        render: (_: unknown, run: EvaluationRunSummary) => {
          const status = evaluationStatusPresentation(run.status);
          return <Tag data-tone={status.tone}>{status.label}</Tag>;
        },
      },
      {
        title: "进度",
        width: 180,
        render: (_: unknown, run: EvaluationRunSummary) => (
          <div className="evaluation-progress-cell">
            <Progress
              percent={run.total_cases ? Math.round((run.processed_cases / run.total_cases) * 100) : 0}
              showInfo={false}
              size="small"
            />
            <span>{run.processed_cases}/{run.total_cases}</span>
          </div>
        ),
      },
      { title: "Legacy 严格通过", width: 150, render: (_: unknown, run: EvaluationRunSummary) => metric(run, "legacy") },
      { title: "本体严格通过", width: 150, render: (_: unknown, run: EvaluationRunSummary) => metric(run, "ontology") },
      { title: "本体平均分", width: 120, render: (_: unknown, run: EvaluationRunSummary) => scoreLabel(run.summary?.ontology.average_score) },
      { title: "本体版本", width: 140, render: (_: unknown, run: EvaluationRunSummary) => run.package_version || "尚未锁定" },
    ],
    [navigate]
  );

  const submit = async (values: FormValues) => {
    const file = files[0]?.originFileObj;
    if (!file) {
      message.warning("请选择已填写的 .xlsx 测试集");
      return;
    }
    setSubmitting(true);
    try {
      const run = await importEvaluation({ ...values, file });
      await startEvaluation(run.id);
      message.success(`已创建 ${run.total_cases} 条案例的评测任务`);
      navigate(`/evaluation/${run.id}`);
    } catch (error) {
      message.error(evaluationErrorMessage(error, "评测任务创建失败"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="evaluation-workbench">
      <header className="evaluation-hero">
        <div>
          <span className="evaluation-eyebrow">EVALUATION CONTROL</span>
          <h1>SQL 评测中心</h1>
          <p>用真实 SQL 建立可复现基线，定位本体、关系、口径与账期问题。</p>
        </div>
        <div className="evaluation-hero-note">
          <strong>静态结构评测</strong>
          <span>不会连接数据库，也不会执行任何 SQL</span>
        </div>
      </header>

      <div className="evaluation-grid">
        <Card className="evaluation-create-card" bordered={false}>
          <div className="evaluation-section-heading">
            <span>NEW BASELINE</span>
            <h2>创建评测任务</h2>
          </div>
          <Alert
            type="info"
            showIcon
            message="每条需求会调用一次现有智能体，可能产生模型额度消耗。"
          />
          <Form<FormValues>
            form={form}
            layout="vertical"
            initialValues={{ dialect: "hive", systemTime: localDate() }}
            onFinish={submit}
          >
            <Form.Item name="name" label="任务名称" rules={[{ required: true, message: "请填写任务名称" }]}>
              <Input placeholder="例如：本体包 1.0 首轮基线" maxLength={128} />
            </Form.Item>
            <div className="evaluation-form-row">
              <Form.Item name="dialect" label="SQL 方言" rules={[{ required: true }]}>
                <Select options={[{ label: "Hive SQL", value: "hive" }]} />
              </Form.Item>
              <Form.Item
                name="systemTime"
                label="评测基准时间"
                rules={[{ required: true, message: "请选择基准时间" }]}
              >
                <Input type="date" />
              </Form.Item>
            </div>
            <Form.Item label="测试集文件" required>
              <Upload.Dragger
                accept=".xlsx"
                maxCount={1}
                fileList={files}
                beforeUpload={() => false}
                onChange={({ fileList }) => setFiles(fileList.slice(-1))}
                onRemove={() => { setFiles([]); return true; }}
              >
                <p className="ant-upload-text">选择或拖入已填写的 Excel 测试集</p>
                <p className="ant-upload-hint">仅识别“需求原文”和“真实SQL”两个必填列</p>
              </Upload.Dragger>
            </Form.Item>
            <Space wrap>
              <Button type="primary" htmlType="submit" loading={submitting}>
                创建并开始评测
              </Button>
              <Button onClick={() => void downloadEvaluationTemplate()}>
                下载空白模板
              </Button>
            </Space>
          </Form>
        </Card>

        <Card className="evaluation-guide-card" bordered={false}>
          <span className="evaluation-eyebrow">READ THE SIGNAL</span>
          <h2>先看生成率，再看正确率</h2>
          <ol>
            <li><strong>本体生成率</strong><span>判断需求是否命中当前本体覆盖范围。</span></li>
            <li><strong>严格通过率</strong><span>六个关键结构维度必须全部一致。</span></li>
            <li><strong>失败归因</strong><span>决定下一步补对象、字段、关系、账期还是编译器。</span></li>
          </ol>
        </Card>
      </div>

      <Card className="evaluation-runs" bordered={false}>
        <div className="evaluation-section-heading evaluation-section-heading--row">
          <div><span>RUN HISTORY</span><h2>评测任务</h2></div>
          <Button onClick={() => void refresh()} loading={loading}>刷新</Button>
        </div>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={runs}
          loading={loading}
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          scroll={{ x: 1080 }}
          locale={{ emptyText: "还没有评测任务，先上传测试集建立第一条基线" }}
        />
      </Card>
    </section>
  );
}
