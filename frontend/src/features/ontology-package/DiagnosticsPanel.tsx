import { useMemo, useState } from "react";
import { Alert, Button, Card, Input, List, Modal, Select, Space, Tag, Typography, message } from "antd";
import {
  apiErrorMessage,
  isDraftRevisionConflict,
  resolveDiagnostic,
  validateWorkspace,
} from "./api";
import type { DiagnosticDisposition, DraftDiagnostic, DraftObject } from "./types";

interface DiagnosticsPanelProps {
  workspaceId: string;
  revision: number;
  diagnostics: DraftDiagnostic[];
  dispositions: DiagnosticDisposition[];
  objects: DraftObject[];
  onChanged: () => Promise<void>;
  onConflict: () => Promise<void>;
  onNavigate: (target: "objects" | "relations" | "temporal") => void;
}

const severityLabels = {
  error: "错误",
  warning: "警告",
  confirmation_required: "需要确认",
} as const;

const severityColors = {
  error: "red",
  warning: "gold",
  confirmation_required: "blue",
} as const;

function objectLabel(item: DraftObject): string {
  return item.label ? `${item.label}（${item.physicalName}）` : item.physicalName;
}

function relatedToObject(diagnostic: DraftDiagnostic, object: DraftObject): boolean {
  return diagnostic.relatedIds.some(
    (id) => id === object.id || object.fields.some((field) => field.id === id)
  );
}

function destination(diagnostic: DraftDiagnostic): "objects" | "relations" | "temporal" {
  if (diagnostic.code.includes("relation")) return "relations";
  if (diagnostic.code.includes("temporal") || diagnostic.code.includes("partition")) return "temporal";
  return "objects";
}

export default function DiagnosticsPanel({
  workspaceId,
  revision,
  diagnostics,
  dispositions,
  objects,
  onChanged,
  onConflict,
  onNavigate,
}: DiagnosticsPanelProps) {
  const [severity, setSeverity] = useState<"all" | DraftDiagnostic["severity"]>("all");
  const [objectId, setObjectId] = useState<string | "all">("all");
  const [disposition, setDisposition] = useState<"all" | "open" | DiagnosticDisposition["status"]>("all");
  const [validating, setValidating] = useState(false);
  const [selected, setSelected] = useState<DraftDiagnostic | null>(null);
  const [explanation, setExplanation] = useState("");
  const [dispositionStatus, setDispositionStatus] = useState<DiagnosticDisposition["status"]>("resolved");
  const [resolving, setResolving] = useState(false);
  const dispositionsByDiagnostic = useMemo(
    () => new Map(dispositions.map((item) => [item.diagnosticId, item])),
    [dispositions]
  );
  const visible = diagnostics.filter((item) => {
    const currentDisposition = dispositionsByDiagnostic.get(item.id);
    return (
      (severity === "all" || item.severity === severity) &&
      (objectId === "all" ||
        objects.some((object) => object.id === objectId && relatedToObject(item, object))) &&
      (disposition === "all" ||
        (disposition === "open" ? !currentDisposition : currentDisposition?.status === disposition))
    );
  });

  const runValidation = async () => {
    setValidating(true);
    try {
      const result = await validateWorkspace(workspaceId);
      message.info(`验证完成：${result.diagnostics.length} 项诊断`);
      await onChanged();
    } catch (error) {
      message.error(apiErrorMessage(error, "验证失败"));
    } finally {
      setValidating(false);
    }
  };

  const resolve = async () => {
    if (!selected || !explanation.trim()) {
      message.error("请填写处置说明");
      return;
    }
    setResolving(true);
    try {
      await resolveDiagnostic(workspaceId, selected.id, explanation.trim(), dispositionStatus, revision);
      message.success("已记录诊断处置");
      setSelected(null);
      setExplanation("");
      setDispositionStatus("resolved");
      await onChanged();
    } catch (error) {
      if (isDraftRevisionConflict(error)) {
        setSelected(null);
        setExplanation("");
        setDispositionStatus("resolved");
        await onConflict();
      } else {
        message.error(apiErrorMessage(error, "诊断处置失败"));
      }
    } finally {
      setResolving(false);
    }
  };

  return (
    <Card id="diagnostics" title="诊断中心" bordered={false}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message="错误需修正后才能发布；警告会在发布确认中完整列出"
          description="需要确认的诊断可修正元数据，或记录明确且非空的处置说明。"
        />
        <Space wrap>
          <Select
            value={severity}
            style={{ width: 130 }}
            onChange={setSeverity}
            options={[
              { value: "all", label: "全部严重程度" },
              ...Object.entries(severityLabels).map(([value, label]) => ({ value, label })),
            ]}
          />
          <Select
            value={objectId}
            style={{ width: 220 }}
            onChange={setObjectId}
            options={[
              { value: "all", label: "全部对象" },
              ...objects.map((item) => ({ value: item.id, label: objectLabel(item) })),
            ]}
          />
          <Select
            value={disposition}
            style={{ width: 160 }}
            onChange={setDisposition}
            options={[
              { value: "all", label: "全部处置状态" },
              { value: "open", label: "未处置" },
              { value: "resolved", label: "已处置" },
              { value: "dismissed", label: "已忽略" },
            ]}
          />
          <Button loading={validating} onClick={() => void runValidation()}>
            执行验证
          </Button>
        </Space>
        <List
          bordered
          locale={{ emptyText: "没有符合筛选条件的诊断" }}
          dataSource={visible}
          renderItem={(item) => {
            const currentDisposition = dispositionsByDiagnostic.get(item.id);
            return (
              <List.Item
                actions={[
                  <Button key="navigate" type="link" onClick={() => onNavigate(destination(item))}>
                    修正元数据
                  </Button>,
                  item.severity === "confirmation_required" && !currentDisposition ? (
                    <Button key="dispose" type="link" onClick={() => setSelected(item)}>
                      记录处置
                    </Button>
                  ) : null,
                ].filter(Boolean)}
              >
                <List.Item.Meta
                  title={
                    <Space wrap>
                      <Tag color={severityColors[item.severity]}>{severityLabels[item.severity]}</Tag>
                      {currentDisposition ? <Tag color="green">{currentDisposition.status === "resolved" ? "已处置" : "已忽略"}</Tag> : null}
                      <Typography.Text>{item.message}</Typography.Text>
                    </Space>
                  }
                />
              </List.Item>
            );
          }}
        />
      </Space>
      <Modal
        title="记录诊断处置"
        open={Boolean(selected)}
        okText="确认处置"
        cancelText="取消"
        okButtonProps={{ disabled: !explanation.trim(), loading: resolving }}
        onOk={() => void resolve()}
        onCancel={() => {
          setSelected(null);
          setExplanation("");
          setDispositionStatus("resolved");
        }}
      >
        <Typography.Paragraph>
          {selected?.message}
        </Typography.Paragraph>
        <Input.TextArea
          autoFocus
          rows={4}
          value={explanation}
          placeholder="请填写明确的处置依据"
          onChange={(event) => setExplanation(event.target.value)}
        />
        <Select
          aria-label="处置状态"
          style={{ marginTop: 12, width: "100%" }}
          value={dispositionStatus}
          options={[
            { value: "resolved", label: "已处置" },
            { value: "dismissed", label: "已忽略" },
          ]}
          onChange={setDispositionStatus}
        />
      </Modal>
    </Card>
  );
}
