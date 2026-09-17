import { useEffect, useRef, useState } from "react";
import { Button, Card, Descriptions, Modal, Select, Space, Table, Tag, Typography, message } from "antd";
import { useNavigate } from "react-router-dom";
import { apiErrorMessage, fetchFeedbackRecords } from "./api";
import { canOpenFeedbackConversation, isLatestRequest } from "./requestSequence";
import type { FeedbackRecord } from "./types";

type FeedbackFilter = "all" | FeedbackRecord["status"];

const statusLabels = {
  correct: "结果正确",
  needs_revision: "需要修改",
} as const;

const statusColors = {
  correct: "green",
  needs_revision: "gold",
} as const;

export default function FeedbackPanel() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<FeedbackFilter>("all");
  const [records, setRecords] = useState<FeedbackRecord[]>([]);
  const [selected, setSelected] = useState<FeedbackRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const latestRequestId = useRef(0);
  const currentUsername = localStorage.getItem("username");

  useEffect(() => {
    const requestId = latestRequestId.current + 1;
    latestRequestId.current = requestId;
    const load = async () => {
      setLoading(true);
      try {
        const nextRecords = await fetchFeedbackRecords(status === "all" ? undefined : status);
        if (isLatestRequest(requestId, latestRequestId.current)) {
          setRecords(nextRecords);
        }
      } catch (error) {
        if (isLatestRequest(requestId, latestRequestId.current)) {
          message.error(apiErrorMessage(error, "反馈记录加载失败"));
        }
      } finally {
        if (isLatestRequest(requestId, latestRequestId.current)) {
          setLoading(false);
        }
      }
    };
    void load();
  }, [status]);

  return (
    <Card
      id="feedback-review"
      title="反馈记录"
      bordered={false}
      extra={
        <Select
          aria-label="反馈状态"
          value={status}
          style={{ width: 140 }}
          onChange={setStatus}
          options={[
            { value: "all", label: "全部状态" },
            { value: "correct", label: statusLabels.correct },
            { value: "needs_revision", label: statusLabels.needs_revision },
          ]}
        />
      }
    >
      <Table<FeedbackRecord>
        rowKey="id"
        loading={loading}
        dataSource={records}
        pagination={{ pageSize: 10 }}
        scroll={{ x: 900 }}
        columns={[
          {
            title: "状态",
            dataIndex: "status",
            width: 110,
            render: (value: FeedbackRecord["status"]) => (
              <Tag color={statusColors[value]}>{statusLabels[value]}</Tag>
            ),
          },
          {
            title: "会话 / 消息",
            width: 150,
            render: (_, row) => `C-${row.conversationId} / M-${row.messageId}`,
          },
          {
            title: "请求",
            dataIndex: "requestText",
            render: (value: string) => (
              <Typography.Text ellipsis={{ tooltip: value }} style={{ maxWidth: 320 }}>
                {value || "—"}
              </Typography.Text>
            ),
          },
          {
            title: "本体版本",
            dataIndex: "ontologyVersion",
            width: 120,
            render: (value: string | null) => value ?? "—",
          },
          { title: "反馈人", dataIndex: "username", width: 120 },
          {
            title: "更新时间",
            dataIndex: "updatedAt",
            width: 180,
            render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
          },
          {
            title: "操作",
            width: 80,
            fixed: "right",
            render: (_, row) => (
              <Button type="link" onClick={() => setSelected(row)}>
                详情
              </Button>
            ),
          },
        ]}
      />

      <Modal
        title="反馈详情"
        open={Boolean(selected)}
        width={760}
        onCancel={() => setSelected(null)}
        footer={selected ? [
          <Button
            key="conversation"
            type="primary"
            disabled={!canOpenFeedbackConversation(selected.username, currentUsername)}
            title={selected.username === currentUsername ? undefined : "仅反馈人可查看完整会话"}
            onClick={() => navigate(`/chat?conversation=${selected.conversationId}`)}
          >
            查看原会话
          </Button>,
          <Button key="close" onClick={() => setSelected(null)}>
            关闭
          </Button>,
        ] : null}
      >
        {selected ? (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Descriptions size="small" column={2}>
              <Descriptions.Item label="状态">
                <Tag color={statusColors[selected.status]}>{statusLabels[selected.status]}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="标识">
                C-{selected.conversationId} / M-{selected.messageId}
              </Descriptions.Item>
              <Descriptions.Item label="请求" span={2}>
                {selected.requestText || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="补充口径" span={2}>
                {selected.note || "—"}
              </Descriptions.Item>
            </Descriptions>
            <div>
              <Typography.Text strong>生成 SQL</Typography.Text>
              <Typography.Paragraph><pre>{selected.generatedSql}</pre></Typography.Paragraph>
            </div>
            <div>
              <Typography.Text strong>最终 SQL</Typography.Text>
              <Typography.Paragraph><pre>{selected.finalSql || "—"}</pre></Typography.Paragraph>
            </div>
          </Space>
        ) : null}
      </Modal>
    </Card>
  );
}
