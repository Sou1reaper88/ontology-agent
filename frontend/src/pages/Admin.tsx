import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  message,
} from "antd";
import client from "../api/client";

function PermissionTable() {
  const [data, setData] = useState<any[]>([]);
  const [tables, setTables] = useState<{ table_name: string; table_comment: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  const fetchData = async () => {
    setLoading(true);
    try {
      const { data: d } = await client.get("/permissions");
      setData(d || []);
    } catch (e: any) {
      message.error(e.response?.data?.detail || "权限数据拉取失败");
    } finally {
      setLoading(false);
    }
  };

  const fetchTables = async () => {
    try {
      const { data: d } = await client.get("/sql/tables");
      setTables(d || []);
    } catch (e: any) {
      message.error(e.response?.data?.detail || "本体表列表拉取失败");
    }
  };

  useEffect(() => {
    fetchData();
    fetchTables();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onCreate = async (values: any) => {
    try {
      await client.post("/permissions", { ...values, can_query: true });
      message.success("创建成功");
      setModalOpen(false);
      form.resetFields();
      fetchData();
    } catch (e: any) {
      message.error(e.response?.data?.detail || "创建失败");
    }
  };

  const onDelete = async (id: number) => {
    try {
      await client.delete(`/permissions/${id}`);
      message.success("删除成功");
      fetchData();
    } catch (e: any) {
      message.error(e.response?.data?.detail || "删除失败");
    }
  };

  const tableOptions = tables.map((t) => ({
    label: t.table_comment ? `${t.table_name}（${t.table_comment}）` : t.table_name,
    value: t.table_name,
  }));

  return (
    <>
      <Button type="primary" style={{ marginBottom: 12 }} onClick={() => setModalOpen(true)}>
        新增
      </Button>
      <Table
        rowKey="id"
        dataSource={data}
        columns={[
          { title: "ID", dataIndex: "id", width: 60 },
          { title: "角色ID", dataIndex: "role_id", width: 80 },
          { title: "表名", dataIndex: "table_name" },
          { title: "中文表名", dataIndex: "ontology_object", ellipsis: true },
          {
            title: "查询权限",
            dataIndex: "can_query",
            width: 100,
            render: (v: boolean) =>
              v ? <Tag color="green">可查询</Tag> : <Tag color="red">禁止</Tag>,
          },
          {
            title: "操作",
            width: 90,
            render: (_: any, r: any) => (
              <Popconfirm title="确认删除？" onConfirm={() => onDelete(r.id)}>
                <Button size="small" danger>
                  删除
                </Button>
              </Popconfirm>
            ),
          },
        ]}
        loading={loading}
        pagination={{ pageSize: 10 }}
        size="small"
      />
      <Modal
        title="新增表权限"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} onFinish={onCreate} layout="vertical">
          <Form.Item name="role_id" label="角色ID" rules={[{ required: true, message: "请输入角色ID" }]}>
            <InputNumber style={{ width: "100%" }} min={1} />
          </Form.Item>
          <Form.Item name="table_name" label="表名（来自 ontology 库）" rules={[{ required: true, message: "请选择表" }]}>
            <Select
              showSearch
              options={tableOptions}
              placeholder="选择本体表"
              optionFilterProp="label"
              onChange={(v) => {
                const t = tables.find((x) => x.table_name === v);
                form.setFieldsValue({ ontology_object: t?.table_comment || "" });
              }}
            />
          </Form.Item>
          <Form.Item name="ontology_object" label="本体对象（中文表名）">
            <Input placeholder="选择表后自动填充中文表名，可手动改" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function AuditLogTable() {
  const [data, setData] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [action, setAction] = useState<string | undefined>();
  const [status, setStatus] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    try {
      const { data: d } = await client.get("/audit-logs", {
        params: { page, page_size: pageSize, action, status },
      });
      setData(d.items || []);
      setTotal(d.total || 0);
    } catch (e: any) {
      message.error(e.response?.data?.detail || "审计日志拉取失败");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, action, status]);

  const actionColor: Record<string, string> = {
    http_request: "blue",
    query_request: "purple",
    sql_execute: "cyan",
    permission_denied: "red",
  };
  const statusColor: Record<string, string> = {
    success: "green",
    denied: "orange",
    failed: "red",
  };
  const detailText = (d: any) => {
    if (!d) return "";
    if (d.path) return `${d.method || ""} ${d.path}`;
    if (d.request_text) return d.request_text;
    if (d.denied_tables) return `拒绝表: ${(d.denied_tables || []).join(", ")}`;
    if (d.sql) return `${String(d.sql).slice(0, 60)}${String(d.sql).length > 60 ? "…" : ""}`;
    return JSON.stringify(d).slice(0, 80);
  };

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Select
          placeholder="操作类型"
          allowClear
          style={{ width: 160 }}
          value={action}
          onChange={setAction}
          options={[
            { label: "HTTP 请求", value: "http_request" },
            { label: "取数请求", value: "query_request" },
            { label: "SQL 执行", value: "sql_execute" },
            { label: "权限拒绝", value: "permission_denied" },
          ]}
        />
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 120 }}
          value={status}
          onChange={setStatus}
          options={[
            { label: "成功", value: "success" },
            { label: "拒绝", value: "denied" },
            { label: "失败", value: "failed" },
          ]}
        />
      </Space>
      <Table
        rowKey="id"
        dataSource={data}
        columns={[
          {
            title: "时间",
            dataIndex: "created_at",
            width: 170,
            render: (v: string) => (v ? v.replace("T", " ").slice(0, 19) : ""),
          },
          { title: "用户", dataIndex: "username", width: 100 },
          {
            title: "操作",
            dataIndex: "action",
            width: 120,
            render: (v: string) => <Tag color={actionColor[v] || "default"}>{v}</Tag>,
          },
          { title: "详情", dataIndex: "detail", ellipsis: true, render: detailText },
          {
            title: "状态",
            dataIndex: "status",
            width: 80,
            render: (v: string) => <Tag color={statusColor[v] || "default"}>{v}</Tag>,
          },
          { title: "耗时(ms)", dataIndex: "duration_ms", width: 90 },
          { title: "IP", dataIndex: "ip", width: 120 },
        ]}
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
        size="small"
      />
    </div>
  );
}

function CrudTable({ path, columns }: { path: string; columns: any[] }) {
  const [data, setData] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  const fetchData = async () => {
    setLoading(true);
    try {
      const { data } = await client.get(path);
      setData(data || []);
    } catch (e: any) {
      message.error(e.response?.data?.detail || "数据拉取失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  const onCreate = async (values: any) => {
    try {
      await client.post(path, values);
      message.success("创建成功");
      setModalOpen(false);
      form.resetFields();
      fetchData();
    } catch (e: any) {
      message.error(e.response?.data?.detail || "创建失败");
    }
  };

  const onDelete = async (id: number) => {
    try {
      await client.delete(`${path}/${id}`);
      message.success("删除成功");
      fetchData();
    } catch (e: any) {
      message.error(e.response?.data?.detail || "删除失败");
    }
  };

  const formColumns = columns.filter(
    (c) => c.dataIndex !== "id" && c.dataIndex !== "created_at"
  );

  return (
    <>
      <Button type="primary" style={{ marginBottom: 12 }} onClick={() => setModalOpen(true)}>
        新增
      </Button>
      <Table
        rowKey="id"
        dataSource={data}
        columns={[
          ...columns,
          {
            title: "操作",
            width: 90,
            render: (_: any, r: any) => (
              <Popconfirm title="确认删除？" onConfirm={() => onDelete(r.id)}>
                <Button size="small" danger>
                  删除
                </Button>
              </Popconfirm>
            ),
          },
        ]}
        loading={loading}
        pagination={{ pageSize: 10 }}
        size="small"
      />
      <Modal
        title="新增"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} onFinish={onCreate} layout="vertical">
          {formColumns.map((c) => (
            <Form.Item
              key={c.dataIndex}
              name={c.dataIndex}
              label={c.title}
              rules={[{ required: true, message: `请输入${c.title}` }]}
            >
              <Input />
            </Form.Item>
          ))}
        </Form>
      </Modal>
    </>
  );
}

export default function Admin() {
  return (
    <Card title="管理后台">
      <Tabs
        items={[
          {
            key: "users",
            label: "用户",
            children: (
              <CrudTable
                path="/users"
                columns={[
                  { title: "ID", dataIndex: "id", width: 60 },
                  { title: "用户名", dataIndex: "username" },
                  { title: "显示名", dataIndex: "display_name" },
                  { title: "角色ID", dataIndex: "role_id", width: 80 },
                  { title: "状态", dataIndex: "status", width: 70 },
                ]}
              />
            ),
          },
          {
            key: "roles",
            label: "角色",
            children: (
              <CrudTable
                path="/roles"
                columns={[
                  { title: "ID", dataIndex: "id", width: 60 },
                  { title: "名称", dataIndex: "name" },
                  { title: "描述", dataIndex: "description" },
                ]}
              />
            ),
          },
          {
            key: "permissions",
            label: "表权限",
            children: <PermissionTable />,
          },
          {
            key: "audit",
            label: "审计日志",
            children: <AuditLogTable />,
          },
        ]}
      />
    </Card>
  );
}
