import { useMemo, useState } from "react";
import { Alert, Button, Card, Checkbox, Form, Input, List, Select, Space, Tag, Typography, message } from "antd";
import { apiErrorMessage, isDraftRevisionConflict, upsertRelation } from "./api";
import { validatedFormValues } from "./formValidation";
import { relationId } from "./relationId";
import { includesRelationSearch, relationMatchesSearch } from "./relationSearch";
import type { DraftObject, DraftRelation } from "./types";

interface RelationPanelProps {
  workspaceId: string;
  revision: number;
  objects: DraftObject[];
  relations: DraftRelation[];
  onChanged: () => Promise<void>;
  onConflict: () => Promise<void>;
}

interface RelationFormValues {
  sourceObjectId: string;
  sourceFieldId: string;
  targetObjectId: string;
  targetFieldId: string;
  label: string;
  cardinality: DraftRelation["cardinality"];
  confirmed: boolean;
}

const cardinalityOptions = [
  { value: "one_to_one", label: "一对一" },
  { value: "one_to_many", label: "一对多" },
  { value: "many_to_one", label: "多对一" },
  { value: "many_to_many", label: "多对多" },
] as const;

function objectLabel(item: DraftObject): string {
  return item.label ? `${item.label}（${item.physicalName}）` : item.physicalName;
}

function endpointLabel(objects: DraftObject[], objectId: string, fieldId: string): string {
  const object = objects.find((item) => item.id === objectId);
  const field = object?.fields.find((item) => item.id === fieldId);
  if (!object || !field) return "已删除对象或字段";
  return `${objectLabel(object)} · ${field.label ? `${field.label}（${field.physicalName}）` : field.physicalName}`;
}

export default function RelationPanel({
  workspaceId,
  revision,
  objects,
  relations,
  onChanged,
  onConflict,
}: RelationPanelProps) {
  const [form] = Form.useForm<RelationFormValues>();
  const [saving, setSaving] = useState(false);
  const [relationSearch, setRelationSearch] = useState("");
  const sourceObjectId = Form.useWatch("sourceObjectId", form);
  const targetObjectId = Form.useWatch("targetObjectId", form);
  const sourceObject = useMemo(
    () => objects.find((item) => item.id === sourceObjectId),
    [objects, sourceObjectId]
  );
  const targetObject = useMemo(
    () => objects.find((item) => item.id === targetObjectId),
    [objects, targetObjectId]
  );
  const visibleRelations = useMemo(
    () => relations.filter((item) => relationMatchesSearch(relationSearch, objects, item)),
    [objects, relationSearch, relations]
  );

  const saveRelation = async () => {
    const values = await validatedFormValues(() => form.validateFields());
    if (!values) return;
    if (values.sourceObjectId === values.targetObjectId || values.sourceFieldId === values.targetFieldId) {
      message.error("源与目标必须是不同的对象和字段");
      return;
    }
    setSaving(true);
    try {
      await upsertRelation(
        workspaceId,
        relationId(values.sourceFieldId, values.targetFieldId),
        {
          label: values.label.trim(),
          sourceObjectId: values.sourceObjectId,
          sourceFieldId: values.sourceFieldId,
          targetObjectId: values.targetObjectId,
          targetFieldId: values.targetFieldId,
          cardinality: values.cardinality,
          status: "active",
          priority: 100,
          confirmed: values.confirmed,
        },
        revision
      );
      message.success("关系已保存");
      form.resetFields();
      await onChanged();
    } catch (error) {
      if (isDraftRevisionConflict(error)) {
        await onConflict();
      } else {
        message.error(apiErrorMessage(error, "关系保存失败"));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card id="relation-editor" title="关系编辑" bordered={false}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message="按源对象、源字段、目标对象、目标字段确认关联方向"
          description="保存前必须填写关系标签、基数，并明确确认关联方向与字段。"
        />
        <Form form={form} layout="vertical" initialValues={{ cardinality: "many_to_one" }}>
          <Space wrap align="start" style={{ width: "100%" }}>
            <Form.Item name="sourceObjectId" label="源对象" rules={[{ required: true, message: "请选择源对象" }]}>
              <Select
                style={{ minWidth: 210 }}
                placeholder="选择源对象"
                showSearch
                filterOption={(input, option) =>
                  includesRelationSearch(input, String(option?.label ?? ""))
                }
                options={objects.map((item) => ({ value: item.id, label: objectLabel(item) }))}
                onChange={() => form.setFieldValue("sourceFieldId", undefined)}
              />
            </Form.Item>
            <Form.Item name="sourceFieldId" label="源字段" rules={[{ required: true, message: "请选择源字段" }]}>
              <Select
                style={{ minWidth: 210 }}
                disabled={!sourceObject}
                placeholder="先选择源对象"
                showSearch
                filterOption={(input, option) =>
                  includesRelationSearch(input, String(option?.label ?? ""))
                }
                options={(sourceObject?.fields ?? []).map((item) => ({
                  value: item.id,
                  label: item.label ? `${item.label}（${item.physicalName}）` : item.physicalName,
                }))}
              />
            </Form.Item>
            <Form.Item name="targetObjectId" label="目标对象" rules={[{ required: true, message: "请选择目标对象" }]}>
              <Select
                style={{ minWidth: 210 }}
                placeholder="选择目标对象"
                showSearch
                filterOption={(input, option) =>
                  includesRelationSearch(input, String(option?.label ?? ""))
                }
                options={objects.map((item) => ({ value: item.id, label: objectLabel(item) }))}
                onChange={() => form.setFieldValue("targetFieldId", undefined)}
              />
            </Form.Item>
            <Form.Item name="targetFieldId" label="目标字段" rules={[{ required: true, message: "请选择目标字段" }]}>
              <Select
                style={{ minWidth: 210 }}
                disabled={!targetObject}
                placeholder="先选择目标对象"
                showSearch
                filterOption={(input, option) =>
                  includesRelationSearch(input, String(option?.label ?? ""))
                }
                options={(targetObject?.fields ?? []).map((item) => ({
                  value: item.id,
                  label: item.label ? `${item.label}（${item.physicalName}）` : item.physicalName,
                }))}
              />
            </Form.Item>
          </Space>
          <Space wrap align="start">
            <Form.Item name="label" label="关系标签" rules={[{ required: true, whitespace: true, message: "请填写关系标签" }]}>
              <Input
                style={{ width: 260 }}
                placeholder="例如：订单归属账户"
              />
            </Form.Item>
            <Form.Item name="cardinality" label="基数" rules={[{ required: true, message: "请选择关系基数" }]}>
              <Select style={{ width: 160 }} options={cardinalityOptions as unknown as { value: string; label: string }[]} />
            </Form.Item>
          </Space>
          <Form.Item
            name="confirmed"
            valuePropName="checked"
            rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error("请明确确认关联方向与字段")) }]}
          >
            <Checkbox>我已确认关联方向与字段</Checkbox>
          </Form.Item>
          <Button type="primary" loading={saving} onClick={() => void saveRelation()}>
            保存关系
          </Button>
        </Form>
        <Typography.Text strong>现有关系</Typography.Text>
        <Input.Search
          allowClear
          placeholder="搜索关系标签、对象或字段"
          value={relationSearch}
          onChange={(event) => setRelationSearch(event.target.value)}
        />
        <List
          size="small"
          locale={{
            emptyText: relations.length === 0 ? "尚未配置关系" : "未找到匹配关系",
          }}
          dataSource={visibleRelations}
          renderItem={(item) => (
            <List.Item>
              <Space wrap>
                <Typography.Text>{item.label || "未命名关系"}</Typography.Text>
                <Tag>{cardinalityOptions.find((option) => option.value === item.cardinality)?.label}</Tag>
                <Typography.Text type="secondary">
                  {endpointLabel(objects, item.sourceObjectId, item.sourceFieldId)} → {endpointLabel(objects, item.targetObjectId, item.targetFieldId)}
                </Typography.Text>
              </Space>
            </List.Item>
          )}
        />
      </Space>
    </Card>
  );
}
