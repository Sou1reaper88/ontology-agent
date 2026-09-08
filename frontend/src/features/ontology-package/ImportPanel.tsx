import { useEffect, useRef, useState } from "react";
import { DownOutlined, DownloadOutlined, UploadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Dropdown, List, Space, Tag, Upload, message } from "antd";
import type { MenuProps, UploadFile, UploadProps } from "antd";
import {
  apiErrorMessage,
  confirmImport,
  downloadImportTemplate,
  isDraftRevisionConflict,
  previewImport,
} from "./api";
import type { ImportTemplateVariant } from "./api";
import {
  installPreviewForRevision,
  previewForCurrentRevision,
} from "./importPreviewState";
import type { ImportPreview } from "./types";
import { metadataUploadValidationError } from "./uploadValidation";

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

const templateItems: MenuProps["items"] = [
  { key: "single", label: "单对象 XLSX 样例" },
  { key: "multiple", label: "多对象 XLSX 样例" },
];

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
  const [downloadingVariant, setDownloadingVariant] = useState<ImportTemplateVariant | null>(null);
  const currentRevisionRef = useRef(revision);

  if (currentRevisionRef.current !== revision) currentRevisionRef.current = revision;

  useEffect(() => {
    setPreviewState((current) => previewForCurrentRevision(current, revision));
    setConfirming(false);
  }, [revision]);

  const preview = previewForCurrentRevision(previewState, revision);

  const uploadProps: UploadProps = {
    accept: ".tsv,.txt,.xlsx",
    beforeUpload: (file) => {
      const validationError = metadataUploadValidationError(file);
      if (validationError) {
        message.error(validationError);
        return Upload.LIST_IGNORE;
      }
      return false;
    },
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

  const handleTemplateDownload = async (variant: ImportTemplateVariant) => {
    setDownloadingVariant(variant);
    let objectUrl: string | null = null;
    try {
      const downloaded = await downloadImportTemplate(workspaceId, variant);
      objectUrl = URL.createObjectURL(downloaded.blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = downloaded.fileName;
      document.body.appendChild(anchor);
      try {
        anchor.click();
      } finally {
        anchor.remove();
      }
      message.success(variant === "single" ? "单对象样例已下载" : "多对象样例已下载");
    } catch (error) {
      message.error(apiErrorMessage(error, "样例下载失败"));
    } finally {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setDownloadingVariant(null);
    }
  };

  return (
    <Card title="导入草稿" bordered={false}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message="支持无宏 XLSX、UTF-8 TSV/TXT；单文件不超过 20 MB"
          description={
            <Space direction="vertical" size={2}>
              <span>
                文件必须保留固定的 10 列。对象中文名称和状态每个对象至少填写一次；属性英文名、属性中文名和属性类型每行必填。
              </span>
              <span>对象描述和属性描述可以留空；是否主键、是否标题留空时按“否”处理。</span>
              <span>上传后先预览，只有就绪预览才可以确认写入草稿。</span>
            </Space>
          }
        />
        <Space wrap>
          <Upload {...uploadProps}>
            <Button icon={<UploadOutlined />}>选择文件</Button>
          </Upload>
          <Dropdown
            menu={{
              items: templateItems,
              onClick: ({ key }) => void handleTemplateDownload(key as ImportTemplateVariant),
            }}
            trigger={["click"]}
          >
            <Button
              icon={<DownloadOutlined />}
              loading={downloadingVariant !== null}
            >
              下载填写样例 <DownOutlined />
            </Button>
          </Dropdown>
        </Space>
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
