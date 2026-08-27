import { useEffect, useMemo, useState } from "react";
import { Button, Drawer, Empty, Input, List, Space, Table, Tag, Typography, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  apiErrorMessage,
  isDraftRevisionConflict,
  updateField,
  updateObject,
} from "./api";
import type { DraftField, DraftObject } from "./types";
import DeleteDraftModal from "./DeleteDraftModal";
import type { DeleteTarget } from "./DeleteDraftModal";

interface ObjectPanelProps {
  workspaceId: string;
  revision: number;
  objects: DraftObject[];
  onChanged: () => Promise<void>;
  onConflict: () => Promise<void>;
}

interface FieldDraft {
  label: string;
  description: string;
}

export default function ObjectPanel({
  workspaceId,
  revision,
  objects,
  onChanged,
  onConflict,
}: ObjectPanelProps) {
  const [objectSearch, setObjectSearch] = useState("");
  const [fieldSearch, setFieldSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [objectLabel, setObjectLabel] = useState("");
  const [objectDescription, setObjectDescription] = useState("");
  const [fieldDrafts, setFieldDrafts] = useState<Record<string, FieldDraft>>({});
  const [savingObject, setSavingObject] = useState(false);
  const [savingFieldId, setSavingFieldId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);

  const selected = objects.find((item) => item.id === selectedId) ?? null;
  const visibleObjects = useMemo(() => {
    const query = objectSearch.trim().toLocaleLowerCase();
    if (!query) return objects;
    return objects.filter((item) =>
      [item.physicalName, item.label, item.description]
        .filter(Boolean)
        .some((value) => value!.toLocaleLowerCase().includes(query))
    );
  }, [objectSearch, objects]);
  const visibleFields = useMemo(() => {
    const query = fieldSearch.trim().toLocaleLowerCase();
    if (!selected || !query) return selected?.fields ?? [];
    return selected.fields.filter((item) =>
      [item.physicalName, item.label, item.description]
        .filter(Boolean)
        .some((value) => value!.toLocaleLowerCase().includes(query))
    );
  }, [fieldSearch, selected]);

  useEffect(() => {
    if (!selected) return;
    setObjectLabel(selected.label ?? "");
    setObjectDescription(selected.description ?? "");
    setFieldDrafts(
      Object.fromEntries(
        selected.fields.map((item) => [
          item.id,
          { label: item.label ?? "", description: item.description ?? "" },
        ])
      )
    );
  }, [selected]);

  const saveObject = async () => {
    if (!selected) return;
    setSavingObject(true);
    try {
      await updateObject(
        workspaceId,
        selected.id,
        { label: objectLabel, description: objectDescription },
        revision
      );
      message.success("对象说明已保存");
      await onChanged();
    } catch (error) {
      if (isDraftRevisionConflict(error)) {
        await onConflict();
      } else {
        message.error(apiErrorMessage(error, "对象保存失败"));
      }
    } finally {
      setSavingObject(false);
    }
  };

  const changeField = (fieldId: string, key: keyof FieldDraft, value: string) => {
    setFieldDrafts((current) => ({
      ...current,
      [fieldId]: { ...current[fieldId], [key]: value },
    }));
  };

  const saveField = async (item: DraftField) => {
    const draft = fieldDrafts[item.id] ?? {
      label: item.label ?? "",
      description: item.description ?? "",
    };
    setSavingFieldId(item.id);
    try {
      await updateField(workspaceId, item.id, draft, revision);
      message.success("字段说明已保存");
      await onChanged();
    } catch (error) {
      if (isDraftRevisionConflict(error)) {
        await onConflict();
      } else {
        message.error(apiErrorMessage(error, "字段保存失败"));
      }
    } finally {
      setSavingFieldId(null);
    }
  };

  const handleDeleted = async (target: DeleteTarget) => {
    setDeleteTarget(null);
    if (target.kind === "object") {
      setSelectedId(null);
      setDrawerOpen(false);
    }
    await onChanged();
  };

  const columns: ColumnsType<DraftField> = [
    {
      title: "字段",
      dataIndex: "physicalName",
      width: 180,
      render: (value: string, item) => (
        <Space size={4} wrap>
          <Typography.Text code>{value}</Typography.Text>
          {item.primaryKey ? <Tag color="blue">主键</Tag> : null}
        </Space>
      ),
    },
    { title: "类型", dataIndex: "xsdType", width: 130 },
    {
      title: "标签",
      width: 220,
      render: (_, item) => (
        <Input
          value={fieldDrafts[item.id]?.label ?? item.label ?? ""}
          onChange={(event) => changeField(item.id, "label", event.target.value)}
          aria-label={`${item.physicalName} 标签`}
        />
      ),
    },
    {
      title: "描述",
      render: (_, item) => (
        <Input.TextArea
          autoSize={{ minRows: 1, maxRows: 3 }}
          value={fieldDrafts[item.id]?.description ?? item.description ?? ""}
          onChange={(event) => changeField(item.id, "description", event.target.value)}
          aria-label={`${item.physicalName} 描述`}
        />
      ),
    },
    {
      title: "操作",
      width: 140,
      render: (_, item) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            loading={savingFieldId === item.id}
            onClick={() => saveField(item)}
          >
            保存
          </Button>
          <Button
            type="link"
            danger
            size="small"
            onClick={() =>
              setDeleteTarget({
                kind: "field",
                id: item.id,
                physicalName: item.physicalName,
              })
            }
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div id="object-editor" style={{ display: "grid", gridTemplateColumns: "minmax(250px, 0.8fr) minmax(0, 2fr)", gap: 16 }}>
      <div>
        <Input.Search
          allowClear
          placeholder="搜索对象名称或说明"
          value={objectSearch}
          onChange={(event) => setObjectSearch(event.target.value)}
          style={{ marginBottom: 12 }}
        />
        <List
          bordered
          dataSource={visibleObjects}
          locale={{ emptyText: "没有匹配的对象" }}
          renderItem={(item) => (
            <List.Item
              style={{ cursor: "pointer", background: selectedId === item.id ? "#e6f4ff" : undefined }}
              onClick={() => setSelectedId(item.id)}
            >
              <List.Item.Meta
                title={item.label || item.physicalName}
                description={`${item.physicalName} · ${item.fields.length} 个字段`}
              />
            </List.Item>
          )}
        />
      </div>
      <div>
        {selected ? (
          <>
            <Space direction="vertical" size="middle" style={{ width: "100%", marginBottom: 16 }}>
              <Space wrap>
                <Typography.Title level={4} style={{ margin: 0 }}>
                  {selected.label || selected.physicalName}
                </Typography.Title>
                <Button onClick={() => setDrawerOpen(true)}>编辑对象</Button>
              </Space>
              <Input.Search
                allowClear
                placeholder="搜索当前对象的字段"
                value={fieldSearch}
                onChange={(event) => setFieldSearch(event.target.value)}
              />
            </Space>
            <Table rowKey="id" columns={columns} dataSource={visibleFields} pagination={{ pageSize: 8 }} />
          </>
        ) : (
          <Empty description="从左侧选择对象以查看字段" />
        )}
      </div>
      <Drawer
        title={selected ? `编辑对象 · ${selected.physicalName}` : "编辑对象"}
        open={drawerOpen && Boolean(selected)}
        onClose={() => setDrawerOpen(false)}
        width={520}
        extra={
          <Space>
            <Button
              danger
              onClick={() =>
                selected &&
                setDeleteTarget({
                  kind: "object",
                  id: selected.id,
                  physicalName: selected.physicalName,
                })
              }
            >
              删除对象
            </Button>
            <Button type="primary" loading={savingObject} onClick={saveObject}>
              保存对象
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Typography.Text type="secondary">物理名称：{selected?.physicalName}</Typography.Text>
          <Input
            addonBefore="对象标签"
            value={objectLabel}
            onChange={(event) => setObjectLabel(event.target.value)}
          />
          <Input.TextArea
            rows={5}
            placeholder="对象描述"
            value={objectDescription}
            onChange={(event) => setObjectDescription(event.target.value)}
          />
        </Space>
      </Drawer>
      <DeleteDraftModal
        open={Boolean(deleteTarget)}
        target={deleteTarget}
        workspaceId={workspaceId}
        revision={revision}
        onClose={() => setDeleteTarget(null)}
        onDeleted={handleDeleted}
        onConflict={onConflict}
      />
    </div>
  );
}
