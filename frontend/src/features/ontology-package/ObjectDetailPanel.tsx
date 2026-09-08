import { useEffect, useMemo, useState } from "react";
import { ArrowLeftOutlined, EditOutlined } from "@ant-design/icons";
import { Button, Empty, Input, Space, Table, Tag, Typography, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { apiErrorMessage, isDraftRevisionConflict, updateField, updateObject } from "./api";
import DeleteDraftModal from "./DeleteDraftModal";
import type { DeleteTarget } from "./DeleteDraftModal";
import type { DraftField, DraftObject } from "./types";

interface ObjectDetailPanelProps {
  workspaceId: string;
  revision: number;
  object: DraftObject;
  onChanged: () => Promise<void>;
  onConflict: () => Promise<void>;
  onBack: () => void;
}

interface FieldDraft {
  label: string;
  description: string;
}

export default function ObjectDetailPanel({
  workspaceId,
  revision,
  object,
  onChanged,
  onConflict,
  onBack,
}: ObjectDetailPanelProps) {
  const [editing, setEditing] = useState(false);
  const [fieldQuery, setFieldQuery] = useState("");
  const [objectLabel, setObjectLabel] = useState("");
  const [objectDescription, setObjectDescription] = useState("");
  const [fieldDrafts, setFieldDrafts] = useState<Record<string, FieldDraft>>({});
  const [savingObject, setSavingObject] = useState(false);
  const [savingFieldId, setSavingFieldId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);

  const resetDrafts = () => {
    setObjectLabel(object.label ?? "");
    setObjectDescription(object.description ?? "");
    setFieldDrafts(
      Object.fromEntries(
        object.fields.map((field) => [
          field.id,
          { label: field.label ?? "", description: field.description ?? "" },
        ])
      )
    );
  };

  useEffect(() => {
    resetDrafts();
  }, [object]);

  const visibleFields = useMemo(() => {
    const query = fieldQuery.trim().toLocaleLowerCase();
    if (!query) return object.fields;
    return object.fields.filter((field) =>
      [field.physicalName, field.label, field.description]
        .filter((value): value is string => Boolean(value))
        .some((value) => value.toLocaleLowerCase().includes(query))
    );
  }, [fieldQuery, object.fields]);

  const saveObject = async () => {
    setSavingObject(true);
    try {
      await updateObject(
        workspaceId,
        object.id,
        { label: objectLabel, description: objectDescription },
        revision
      );
      message.success("对象说明已保存");
      await onChanged();
    } catch (error) {
      if (isDraftRevisionConflict(error)) await onConflict();
      else message.error(apiErrorMessage(error, "对象保存失败"));
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

  const saveField = async (field: DraftField) => {
    const draft = fieldDrafts[field.id] ?? { label: "", description: "" };
    setSavingFieldId(field.id);
    try {
      await updateField(workspaceId, field.id, draft, revision);
      message.success("字段说明已保存");
      await onChanged();
    } catch (error) {
      if (isDraftRevisionConflict(error)) await onConflict();
      else message.error(apiErrorMessage(error, "字段保存失败"));
    } finally {
      setSavingFieldId(null);
    }
  };

  const exitEditing = () => {
    resetDrafts();
    setEditing(false);
  };

  const handleDeleted = async (target: DeleteTarget) => {
    setDeleteTarget(null);
    if (target.kind === "object") onBack();
    await onChanged();
  };

  const columns: ColumnsType<DraftField> = [
    {
      title: "物理字段名",
      dataIndex: "physicalName",
      width: 190,
      render: (value: string, field) => (
        <Space size={5} wrap>
          <Typography.Text code>{value}</Typography.Text>
          {field.primaryKey ? <Tag color="blue">主键</Tag> : null}
          {field.title ? <Tag>标题字段</Tag> : null}
        </Space>
      ),
    },
    { title: "类型", dataIndex: "xsdType", width: 135 },
    {
      title: "字段中文名",
      width: 220,
      render: (_, field) =>
        editing ? (
          <Input
            value={fieldDrafts[field.id]?.label ?? ""}
            onChange={(event) => changeField(field.id, "label", event.target.value)}
            aria-label={`${field.physicalName} 中文名`}
          />
        ) : (
          <span>{field.label || "—"}</span>
        ),
    },
    {
      title: "字段描述",
      width: 420,
      render: (_, field) =>
        editing ? (
          <Input.TextArea
            autoSize={{ minRows: 2, maxRows: 5 }}
            value={fieldDrafts[field.id]?.description ?? ""}
            onChange={(event) => changeField(field.id, "description", event.target.value)}
            aria-label={`${field.physicalName} 描述`}
          />
        ) : (
          <span className="ontology-object-detail__field-description">
            {field.description || "尚未填写字段描述"}
          </span>
        ),
    },
    ...(editing
      ? [
          {
            title: "操作",
            width: 140,
            fixed: "right" as const,
            render: (_: unknown, field: DraftField) => (
              <Space size={2}>
                <Button
                  type="link"
                  size="small"
                  loading={savingFieldId === field.id}
                  onClick={() => void saveField(field)}
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
                      id: field.id,
                      physicalName: field.physicalName,
                    })
                  }
                >
                  删除
                </Button>
              </Space>
            ),
          },
        ]
      : []),
  ];

  return (
    <article className={`ontology-object-detail${editing ? " is-editing" : ""}`}>
      <div className="ontology-object-detail__breadcrumb">
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={onBack}>
          返回对象列表
        </Button>
        <span>对象与字段 / {object.label || object.physicalName}</span>
      </div>

      <header className="ontology-object-detail__header">
        <div className="ontology-object-detail__title">
          <span>ONTOLOGY OBJECT</span>
          {editing ? (
            <Input
              size="large"
              value={objectLabel}
              onChange={(event) => setObjectLabel(event.target.value)}
              aria-label="对象中文名"
            />
          ) : (
            <h3>{object.label || object.physicalName}</h3>
          )}
          <code>{object.physicalName}</code>
        </div>
        <Space wrap>
          {editing ? (
            <>
              <Button onClick={exitEditing}>退出编辑</Button>
              <Button
                danger
                onClick={() =>
                  setDeleteTarget({
                    kind: "object",
                    id: object.id,
                    physicalName: object.physicalName,
                  })
                }
              >
                删除对象
              </Button>
              <Button type="primary" loading={savingObject} onClick={() => void saveObject()}>
                保存对象信息
              </Button>
            </>
          ) : (
            <Button type="primary" icon={<EditOutlined />} onClick={() => setEditing(true)}>
              编辑对象与字段
            </Button>
          )}
        </Space>
      </header>

      <section className="ontology-object-detail__overview" aria-label="对象信息">
        <div>
          <span>对象状态</span>
          <strong>{object.status === "active" ? "启用" : "停用"}</strong>
        </div>
        <div>
          <span>字段数量</span>
          <strong className="tabular-nums">{object.fields.length}</strong>
        </div>
        <div className="ontology-object-detail__description">
          <span>对象描述</span>
          {editing ? (
            <Input.TextArea
              rows={4}
              value={objectDescription}
              onChange={(event) => setObjectDescription(event.target.value)}
              placeholder="填写对象描述"
            />
          ) : (
            <p>{object.description || "尚未填写对象描述"}</p>
          )}
        </div>
      </section>

      <section className="ontology-object-detail__fields">
        <div className="ontology-object-detail__fields-heading">
          <div>
            <span>字段目录</span>
            <strong>字段定义与业务说明</strong>
          </div>
          <Input.Search
            allowClear
            placeholder="搜索字段名或描述"
            value={fieldQuery}
            onChange={(event) => setFieldQuery(event.target.value)}
            aria-label="搜索当前对象字段"
          />
        </div>
        {visibleFields.length ? (
          <Table
            rowKey="id"
            columns={columns}
            dataSource={visibleFields}
            pagination={{ pageSize: 8, showSizeChanger: false }}
            scroll={{ x: editing ? 1105 : 965 }}
            tableLayout="fixed"
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的字段" />
        )}
      </section>

      <DeleteDraftModal
        open={Boolean(deleteTarget)}
        target={deleteTarget}
        workspaceId={workspaceId}
        revision={revision}
        onClose={() => setDeleteTarget(null)}
        onDeleted={handleDeleted}
        onConflict={onConflict}
      />
    </article>
  );
}
