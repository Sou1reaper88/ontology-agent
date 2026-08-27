import { useEffect, useState } from "react";
import { Alert, Button, Card, InputNumber, Select, Space, Switch, Tag, Typography, message } from "antd";
import { apiErrorMessage, isDraftRevisionConflict, upsertTemporalPolicy } from "./api";
import type { DraftObject, DraftTemporalPolicy } from "./types";

interface TemporalPanelProps {
  workspaceId: string;
  revision: number;
  objects: DraftObject[];
  policies: DraftTemporalPolicy[];
  onChanged: () => Promise<void>;
  onConflict: () => Promise<void>;
}

export const strategyOptions = {
  day: [{ value: "t_minus_2", label: "系统日 T-2" }],
  month: [{ value: "previous_complete_month", label: "上一个完整月" }],
} as const;

function objectLabel(item: DraftObject): string {
  return item.label ? `${item.label}（${item.physicalName}）` : item.physicalName;
}

function emptyPolicy(objectId: string): DraftTemporalPolicy {
  return {
    objectId,
    partitionFieldId: "",
    grain: "day",
    defaultStrategy: "t_minus_2",
    allowQueryOverride: true,
    status: "active",
    priority: 100,
  };
}

export default function TemporalPanel({
  workspaceId,
  revision,
  objects,
  policies,
  onChanged,
  onConflict,
}: TemporalPanelProps) {
  const [drafts, setDrafts] = useState<Record<string, DraftTemporalPolicy>>({});
  const [savingObjectId, setSavingObjectId] = useState<string | null>(null);

  useEffect(() => {
    setDrafts(
      Object.fromEntries(
        objects.map((object) => [
          object.id,
          policies.find((policy) => policy.objectId === object.id) ?? emptyPolicy(object.id),
        ])
      )
    );
  }, [objects, policies]);

  const update = <K extends keyof DraftTemporalPolicy>(
    objectId: string,
    key: K,
    value: DraftTemporalPolicy[K]
  ) => {
    setDrafts((current) => ({
      ...current,
      [objectId]: { ...(current[objectId] ?? emptyPolicy(objectId)), [key]: value },
    }));
  };

  const changeGrain = (objectId: string, grain: DraftTemporalPolicy["grain"]) => {
    setDrafts((current) => ({
      ...current,
      [objectId]: {
        ...(current[objectId] ?? emptyPolicy(objectId)),
        grain,
        defaultStrategy: strategyOptions[grain][0].value,
      },
    }));
  };

  const save = async (object: DraftObject) => {
    const policy = drafts[object.id] ?? emptyPolicy(object.id);
    if (!policy.partitionFieldId) {
      message.error("请选择该对象拥有的分区字段");
      return;
    }
    setSavingObjectId(object.id);
    try {
      await upsertTemporalPolicy(workspaceId, policy, revision);
      message.success(`${objectLabel(object)} 的时间策略已保存`);
      await onChanged();
    } catch (error) {
      if (isDraftRevisionConflict(error)) {
        await onConflict();
      } else {
        message.error(apiErrorMessage(error, "时间策略保存失败"));
      }
    } finally {
      setSavingObjectId(null);
    }
  };

  return (
    <Card id="temporal-editor" title="对象时间策略" bordered={false}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message="每个对象独立配置一个时间策略"
          description="只可选择该对象拥有的分区字段；不存在全局默认策略。"
        />
        {objects.map((object) => {
          const policy = drafts[object.id] ?? emptyPolicy(object.id);
          return (
            <Card key={object.id} size="small" title={objectLabel(object)}>
              <Space wrap align="start">
                <div>
                  <Typography.Text type="secondary">分区字段</Typography.Text>
                  <Select
                    style={{ display: "block", width: 220, marginTop: 4 }}
                    value={policy.partitionFieldId || undefined}
                    placeholder="选择本对象字段"
                    options={object.fields.map((field) => ({
                      value: field.id,
                      label: field.label ? `${field.label}（${field.physicalName}）` : field.physicalName,
                    }))}
                    onChange={(value) => update(object.id, "partitionFieldId", value)}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">粒度</Typography.Text>
                  <Select
                    style={{ display: "block", width: 120, marginTop: 4 }}
                    value={policy.grain}
                    options={[
                      { value: "day", label: "日" },
                      { value: "month", label: "月" },
                    ]}
                    onChange={(value: DraftTemporalPolicy["grain"]) => changeGrain(object.id, value)}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">默认算法</Typography.Text>
                  <Select
                    style={{ display: "block", width: 180, marginTop: 4 }}
                    value={policy.defaultStrategy}
                    options={[...strategyOptions[policy.grain]]}
                    onChange={(value) => update(object.id, "defaultStrategy", value)}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">状态</Typography.Text>
                  <Select
                    style={{ display: "block", width: 110, marginTop: 4 }}
                    value={policy.status}
                    options={[
                      { value: "active", label: "启用" },
                      { value: "inactive", label: "停用" },
                    ]}
                    onChange={(value) => update(object.id, "status", value)}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">优先级</Typography.Text>
                  <InputNumber
                    min={0}
                    style={{ display: "block", width: 110, marginTop: 4 }}
                    value={policy.priority}
                    onChange={(value) => update(object.id, "priority", value ?? 100)}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">查询可覆盖</Typography.Text>
                  <Switch
                    style={{ display: "block", marginTop: 8 }}
                    checked={policy.allowQueryOverride}
                    checkedChildren="允许"
                    unCheckedChildren="不允许"
                    onChange={(value) => update(object.id, "allowQueryOverride", value)}
                  />
                </div>
                <Button type="primary" loading={savingObjectId === object.id} onClick={() => void save(object)}>
                  保存此对象策略
                </Button>
              </Space>
              <div style={{ marginTop: 12 }}>
                <Tag color={policy.grain === "day" ? "blue" : "purple"}>
                  {policy.grain === "day" ? "日粒度仅支持系统日 T-2" : "月粒度仅支持上一个完整月"}
                </Tag>
              </div>
            </Card>
          );
        })}
      </Space>
    </Card>
  );
}
