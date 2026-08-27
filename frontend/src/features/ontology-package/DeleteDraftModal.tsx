import { useEffect, useState } from "react";
import { Alert, Descriptions, Input, Modal, Skeleton, Space, Typography, message } from "antd";
import {
  apiErrorMessage,
  deleteDraftField,
  deleteDraftObject,
  fetchFieldDeleteImpact,
  fetchObjectDeleteImpact,
  isDraftRevisionConflict,
} from "./api";
import type { DraftDeleteImpact } from "./types";

export type DeleteTarget =
  | { kind: "object"; id: string; physicalName: string }
  | { kind: "field"; id: string; physicalName: string };

interface DeleteDraftModalProps {
  open: boolean;
  target: DeleteTarget | null;
  workspaceId: string;
  revision: number;
  onClose: () => void;
  onDeleted: (target: DeleteTarget) => Promise<void>;
  onConflict: () => Promise<void>;
}

export default function DeleteDraftModal({
  open,
  target,
  workspaceId,
  revision,
  onClose,
  onDeleted,
  onConflict,
}: DeleteDraftModalProps) {
  const [impact, setImpact] = useState<DraftDeleteImpact | null>(null);
  const [confirmationName, setConfirmationName] = useState("");
  const [loadingImpact, setLoadingImpact] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !target) return;
    let current = true;
    setImpact(null);
    setConfirmationName("");
    setLoadError(null);
    setLoadingImpact(true);

    const request =
      target.kind === "object"
        ? fetchObjectDeleteImpact(workspaceId, target.id)
        : fetchFieldDeleteImpact(workspaceId, target.id);

    void request
      .then(async (response) => {
        if (!current) return;
        if (response.revision !== revision) {
          onClose();
          await onConflict();
          return;
        }
        setImpact(response.impact);
      })
      .catch(async (error: unknown) => {
        if (!current) return;
        if (isDraftRevisionConflict(error)) {
          onClose();
          await onConflict();
          return;
        }
        const errorMessage = apiErrorMessage(error, "无法获取删除影响范围");
        setLoadError(errorMessage);
        message.error(errorMessage);
      })
      .finally(() => {
        if (current) setLoadingImpact(false);
      });

    return () => {
      current = false;
    };
  }, [onClose, onConflict, open, revision, target, workspaceId]);

  const confirmed = Boolean(impact) && confirmationName === impact?.physicalName;

  const confirmDelete = async () => {
    if (!target || !impact || !confirmed) return;
    setDeleting(true);
    try {
      if (target.kind === "object") {
        await deleteDraftObject(workspaceId, target.id, revision, confirmationName);
      } else {
        await deleteDraftField(workspaceId, target.id, revision, confirmationName);
      }
      message.success(target.kind === "object" ? "对象及其引用已删除" : "字段及其引用已删除");
      onClose();
      await onDeleted(target);
    } catch (error) {
      if (isDraftRevisionConflict(error)) {
        onClose();
        await onConflict();
      } else {
        message.error(apiErrorMessage(error, "删除失败"));
      }
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Modal
      title={target?.kind === "object" ? "删除草稿对象" : "删除草稿字段"}
      open={open && Boolean(target)}
      okText="确认级联删除"
      cancelText="取消"
      okButtonProps={{ danger: true, disabled: !confirmed || loadingImpact || Boolean(loadError) }}
      confirmLoading={deleting}
      cancelButtonProps={{ disabled: deleting }}
      onOk={() => void confirmDelete()}
      onCancel={onClose}
      destroyOnClose
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          message="此操作不可撤销"
          description="目标及其草稿关系、时间策略会在同一个修订中级联删除；已发布标识仍会被后端拒绝。"
        />
        {loadError ? <Alert type="error" showIcon message={loadError} /> : null}
        {loadingImpact ? (
          <Skeleton active paragraph={{ rows: 2 }} />
        ) : (
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="对象">{impact?.objectCount ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="字段">{impact?.fieldCount ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="关系">{impact?.relationCount ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="时间策略">
              {impact?.temporalPolicyCount ?? "-"}
            </Descriptions.Item>
          </Descriptions>
        )}
        <Typography.Text>
          请输入物理名称 <Typography.Text code>{impact?.physicalName ?? target?.physicalName}</Typography.Text>
          以确认删除：
        </Typography.Text>
        <Input
          value={confirmationName}
          disabled={!impact || deleting}
          placeholder={impact?.physicalName ?? "正在读取影响范围"}
          onChange={(event) => setConfirmationName(event.target.value)}
          aria-label="删除确认物理名称"
        />
      </Space>
    </Modal>
  );
}
