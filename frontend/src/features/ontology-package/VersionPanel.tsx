import { useState } from "react";
import { Alert, Button, Card, Form, Input, Modal, Space, Table, Tag, Typography, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  apiErrorMessage,
  isDraftRevisionConflict,
  publishVersion,
  rollbackVersion,
} from "./api";
import type { DiagnosticDisposition, DraftDiagnostic, VersionSummary } from "./types";

interface VersionPanelProps {
  workspaceId: string;
  revision: number;
  versions: VersionSummary[];
  diagnostics: DraftDiagnostic[];
  dispositions: DiagnosticDisposition[];
  onChanged: () => Promise<void>;
  onConflict: () => Promise<void>;
}

interface PublishFormValues {
  version: string;
  releaseNotes: string;
}

interface RollbackRequest {
  version: string;
  reason: string;
}

function versionCounts(version: VersionSummary): string {
  if (!version.counts) return "不可用（旧版本）";
  return `对象 ${version.counts.concepts} · 字段 ${version.counts.properties} · 关系 ${version.counts.relations} · 时间策略 ${version.counts.temporalPolicies}`;
}

function digestPrefix(version: VersionSummary): string {
  return version.contentDigest ? `${version.contentDigest.slice(0, 12)}…` : "不可用（旧版本）";
}

export default function VersionPanel({
  workspaceId,
  revision,
  versions,
  diagnostics,
  dispositions,
  onChanged,
  onConflict,
}: VersionPanelProps) {
  const [form] = Form.useForm<PublishFormValues>();
  const [publishing, setPublishing] = useState(false);
  const [rollbackRequest, setRollbackRequest] = useState<RollbackRequest | null>(null);
  const [rollbackConfirmation, setRollbackConfirmation] = useState<RollbackRequest | null>(null);
  const [rollbackReason, setRollbackReason] = useState("");
  const [rollingBack, setRollingBack] = useState(false);
  const disposed = new Set(dispositions.map((item) => item.diagnosticId));
  const warnings = diagnostics.filter((item) => item.severity === "warning");
  const blocking = diagnostics.filter(
    (item) => item.severity === "error" || (item.severity === "confirmation_required" && !disposed.has(item.id))
  );

  const publish = async () => {
    const values = await form.validateFields();
    if (blocking.length) {
      message.error("请先处理错误和需要确认的诊断");
      return;
    }
    Modal.confirm({
      title: "确认发布版本",
      okText: "确认发布",
      cancelText: "取消",
      content: (
        <Space direction="vertical" size="small">
          <Typography.Text>版本：{values.version.trim()}</Typography.Text>
          <Typography.Text>草稿修订：{revision}</Typography.Text>
          <Typography.Text strong>发布前警告汇总</Typography.Text>
          {warnings.length ? warnings.map((item) => <Typography.Text key={item.id}>• {item.message}</Typography.Text>) : <Typography.Text type="secondary">当前没有警告</Typography.Text>}
        </Space>
      ),
      onOk: async () => {
        setPublishing(true);
        try {
          await publishVersion(workspaceId, values.version.trim(), values.releaseNotes.trim(), revision);
          message.success("版本已发布");
          form.resetFields();
          await onChanged();
        } catch (error) {
          if (isDraftRevisionConflict(error)) {
            await onConflict();
          } else {
            message.error(apiErrorMessage(error, "版本发布失败"));
          }
        } finally {
          setPublishing(false);
        }
      },
    });
  };

  const requestRollback = () => {
    const reason = rollbackReason.trim();
    if (!rollbackRequest || !reason) {
      message.error("请填写回滚原因");
      return;
    }
    setRollbackConfirmation({ ...rollbackRequest, reason });
    setRollbackRequest(null);
    setRollbackReason("");
  };

  const confirmRollback = async () => {
    if (!rollbackConfirmation) return;
    setRollingBack(true);
    try {
      await rollbackVersion(workspaceId, rollbackConfirmation.version, rollbackConfirmation.reason);
      message.success("已切换活动版本；草稿未被修改");
      setRollbackConfirmation(null);
      await onChanged();
    } catch (error) {
      message.error(apiErrorMessage(error, "版本回滚失败"));
    } finally {
      setRollingBack(false);
    }
  };

  const columns: ColumnsType<VersionSummary> = [
    {
      title: "版本",
      dataIndex: "version",
      render: (value: string, item) => <Space>{item.active ? <Tag color="green">活动</Tag> : null}<Typography.Text strong>{value}</Typography.Text></Space>,
    },
    { title: "统计", render: (_, item) => versionCounts(item) },
    { title: "内容摘要", render: (_, item) => <Typography.Text code>{digestPrefix(item)}</Typography.Text> },
    { title: "发布人", dataIndex: "actor" },
    { title: "发布时间", render: (_, item) => new Date(item.publishedAt).toLocaleString() },
    {
      title: "操作",
      render: (_, item) => (
        <Button disabled={item.active} onClick={() => setRollbackRequest({ version: item.version, reason: "" })}>
          回滚到此版本
        </Button>
      ),
    },
  ];

  return (
    <Card id="versions" title="版本发布与回滚" bordered={false}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message="已发布版本不可修改；回滚只切换活动版本"
          description="发布使用当前草稿修订；回滚需要原因和第二次确认，绝不会改写草稿。"
        />
        <Form form={form} layout="vertical">
          <Space wrap align="start">
            <Form.Item
              name="version"
              label="新版本号"
              rules={[
                { required: true, whitespace: true, message: "请填写版本号" },
                {
                  validator: (_, value) => versions.some((item) => item.version === value?.trim())
                    ? Promise.reject(new Error("该版本号已存在且不可复用"))
                    : Promise.resolve(),
                },
              ]}
            >
              <Input placeholder="例如 1.2.0" style={{ width: 180 }} />
            </Form.Item>
            <Form.Item name="releaseNotes" label="发布说明" rules={[{ required: true, whitespace: true, message: "请填写发布说明" }]}>
              <Input.TextArea rows={2} placeholder="说明本次发布内容" style={{ width: 360 }} />
            </Form.Item>
            <Button type="primary" loading={publishing} onClick={() => void publish()}>
              发布当前修订 {revision}
            </Button>
          </Space>
        </Form>
        <Table rowKey="version" columns={columns} dataSource={versions} pagination={false} locale={{ emptyText: "尚无已发布版本" }} />
      </Space>
      <Modal
        title={`回滚到 ${rollbackRequest?.version ?? ""}`}
        open={Boolean(rollbackRequest)}
        okText="继续确认"
        cancelText="取消"
        onOk={requestRollback}
        onCancel={() => {
          setRollbackRequest(null);
          setRollbackReason("");
        }}
      >
        <Typography.Paragraph>请填写回滚原因；下一步还会要求再次确认。</Typography.Paragraph>
        <Input.TextArea rows={3} value={rollbackReason} onChange={(event) => setRollbackReason(event.target.value)} placeholder="回滚原因" />
      </Modal>
      <Modal
        title="再次确认回滚"
        open={Boolean(rollbackConfirmation)}
        okText="确认回滚"
        okButtonProps={{ danger: true, loading: rollingBack }}
        cancelText="取消"
        onOk={() => void confirmRollback()}
        onCancel={() => setRollbackConfirmation(null)}
      >
        <Typography.Paragraph>
          即将切换活动版本到 {rollbackConfirmation?.version}。草稿不会被修改。
        </Typography.Paragraph>
        <Typography.Text type="secondary">原因：{rollbackConfirmation?.reason}</Typography.Text>
      </Modal>
    </Card>
  );
}
