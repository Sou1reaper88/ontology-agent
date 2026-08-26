import { useEffect, useRef, useState } from "react";
import { UploadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, List, Space, Tag, Upload, message } from "antd";
import type { UploadFile, UploadProps } from "antd";
import {
  apiErrorMessage,
  confirmImport,
  isDraftRevisionConflict,
  previewImport,
} from "./api";
import {
  installPreviewForRevision,
  previewForCurrentRevision,
} from "./importPreviewState";
import type { ImportPreview } from "./types";

interface ImportPanelProps {
  workspaceId: string;
  revision: number;
  onChanged: () => Promise<void>;
  onConflict: () => Promise<void>;
}

const severityColor: Record<ImportPreview["diagnostics"][number]["severity"], string> = {
  error: "red",
  warning: "gold",
  confirmation_required: "blue",
};

export default function ImportPanel({
  workspaceId,
  revision,
  onChanged,
  onConflict,
}: ImportPanelProps) {
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [previewState, setPreviewState] = useState<ReturnType<typeof installPreviewForRevision>>(null);
  const [previewing, setPreviewing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const currentRevisionRef = useRef(revision);

  if (currentRevisionRef.current !== revision) currentRevisionRef.current = revision;

  useEffect(() => {
    setPreviewState((current) => previewForCurrentRevision(current, revision));
    setConfirming(false);
  }, [revision]);

  const preview = previewForCurrentRevision(previewState, revision);

  const uploadProps: UploadProps = {
    accept: ".tsv,.txt,.xlsx",
    beforeUpload: () => false,
    fileList: files,
    multiple: true,
    onChange: ({ fileList }) => {
      setFiles(fileList);
      setPreviewState(null);
    },
  };

  const selectedFiles = (): NonNullable<UploadFile["originFileObj"]>[] =>
    files.reduce<NonNullable<UploadFile["originFileObj"]>[]>((selected, item) => {
      if (item.originFileObj) selected.push(item.originFileObj);
      return selected;
    }, []);

  const handlePreview = async () => {
    const uploads = selectedFiles();
    if (!uploads.length) {
      message.warning("请先选择要预览的文件");
      return;
    }
    const sourceRevision = currentRevisionRef.current;
    setPreviewing(true);
    try {
      const response = await previewImport(workspaceId, uploads, sourceRevision);
      const revisionBoundPreview = installPreviewForRevision(
        response,
        sourceRevision,
        currentRevisionRef.current
      );
      if (revisionBoundPreview) setPreviewState(revisionBoundPreview);
    } catch (error) {
      if (isDraftRevisionConflict(error)) {
        setPreviewState(null);
        await onConflict();
      } else {
        message.error(apiErrorMessage(error, "导入预览失败"));
      }
    } finally {
      setPreviewing(false);
    }
  };

  const handleConfirm = async () => {
    if (!preview?.preview.token || preview.preview.status !== "ready") return;
    const expectedRevision = currentRevisionRef.current;
    if (preview.sourceRevision !== expectedRevision) return;
    setConfirming(true);
    try {
      await confirmImport(workspaceId, preview.preview.token, expectedRevision);
      message.success("已导入到草稿");
      setPreviewState(null);
      setFiles([]);
      await onChanged();
    } catch (error) {
      if (isDraftRevisionConflict(error)) {
        setPreviewState(null);
        await onConflict();
      } else {
        message.error(apiErrorMessage(error, "确认导入失败"));
      }
    } finally {
      setConfirming(false);
    }
  };

  return (
    <Card title="导入草稿" bordered={false}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message="先预览，再明确确认写入草稿"
          description="预览不会修改草稿版本。仅就绪预览可确认导入。"
        />
        <Upload {...uploadProps}>
          <Button icon={<UploadOutlined />}>选择文件</Button>
        </Upload>
        <Button type="primary" onClick={handlePreview} loading={previewing}>
          预览导入
        </Button>
        {preview ? (
          <Card size="small" title={preview.preview.status === "ready" ? "预览就绪" : "预览被阻止"}>
            <Space direction="vertical" style={{ width: "100%" }}>
              <div>已选择 {files.length} 个文件</div>
              <div>
                将导入 {preview.preview.objectCount} 个对象、{preview.preview.fieldCount} 个字段
              </div>
              {preview.preview.diagnostics.length ? (
                <List
                  size="small"
                  dataSource={preview.preview.diagnostics}
                  renderItem={(item) => (
                    <List.Item>
                      <Tag color={severityColor[item.severity]}>{item.severity}</Tag>
                      {item.message}
                    </List.Item>
                  )}
                />
              ) : null}
              {preview.preview.status === "ready" && preview.preview.token ? (
                <Button type="primary" onClick={handleConfirm} loading={confirming}>
                  确认导入到草稿
                </Button>
              ) : null}
            </Space>
          </Card>
        ) : null}
      </Space>
    </Card>
  );
}
