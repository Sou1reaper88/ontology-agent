import { Alert, Card, Space, Table, Tag, Typography } from "antd";
import type { DraftObject, DraftTemporalPolicy } from "./types";

interface TemporalPanelProps {
  objects: DraftObject[];
  policies: DraftTemporalPolicy[];
}

export default function TemporalPanel({ objects, policies }: TemporalPanelProps) {
  const rows = objects.map((object) => {
    const policy = policies.find((item) => item.objectId === object.id);
    const field = object.fields.find((item) => item.id === policy?.partitionFieldId);
    const suffix = object.physicalName.toUpperCase();
    const expectedField = suffix.endsWith("_D") ? "P_DAY" : suffix.endsWith("_M") ? "P_MON" : null;
    return { ...object, policy, field, expectedField };
  });

  return (
    <Card id="temporal-editor" title="自动账期" bordered={false}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Alert type="info" showIcon message="无需逐表配置，按表名后缀自动识别"
          description="_D 表使用 P_DAY，默认系统日期前两天（YYYYMMDD）；_M 表使用 P_MON，默认上一个完整自然月（YYYYMM）。需求明确指定账期时优先使用指定值。表名与字段名不区分大小写。" />
        <Typography.Text type="secondary">
          例如系统日期为 2026-08-24：默认 P_DAY = 20260822，P_MON = 202607。
          以下展示当前草稿；取数仍使用已发布版本的表字段定义，并自动应用同一规则。
        </Typography.Text>
        <Table rowKey="id" dataSource={rows} pagination={{ pageSize: 10 }} scroll={{ x: 800 }}
          columns={[
            { title: "对象", dataIndex: "physicalName", render: (name, row) => (
              <Space direction="vertical" size={0}>
                <Typography.Text code>{name}</Typography.Text>
                {row.label && <Typography.Text type="secondary">{row.label}</Typography.Text>}
              </Space>
            ) },
            { title: "分区字段", render: (_, row) => row.field?.physicalName ?? row.expectedField ?? "—" },
            { title: "默认账期", render: (_, row) => row.policy
              ? row.policy.grain === "day" ? "系统日期 − 2 天" : "上一个完整自然月"
              : "—" },
            { title: "识别状态", render: (_, row) => row.status === "inactive"
              ? <Tag>对象已停用</Tag>
              : row.policy ? <Tag color="green">{row.expectedField ? "自动应用" : "兼容原有策略"}</Tag>
              : row.expectedField ? <Tag color="red">缺少唯一启用的 {row.expectedField} 字段</Tag>
              : <Tag>非 _D / _M 表，不自动推断</Tag> },
          ]} />
      </Space>
    </Card>
  );
}
