import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Upload,
  message,
} from "antd";
import { UploadOutlined } from "@ant-design/icons";
import client from "../api/client";

function RelationTable() {
  const [data, setData] = useState<any[]>([]);
  const [tables, setTables] = useState<{ table_name: string; table_comment: string }[]>([]);
  const [sourceFields, setSourceFields] = useState<{ label: string; value: string }[]>([]);
  const [targetFields, setTargetFields] = useState<{ label: string; value: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  const loadFields = async (table: string, isSource: boolean) => {
    try {
      const { data } = await client.get("/sql/columns", { params: { table } });
      const opts = (data || []).map((c: any) => ({
        label: c.comment ? `${c.field}（${c.comment}）` : c.field,
        value: c.field,
      }));
      if (isSource) setSourceFields(opts);
      else setTargetFields(opts);
    } catch (e: any) {
      message.error("字段列表加载失败");
    }
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      const { data: d } = await client.get("/ontology/relations");
      setData(d || []);
    } catch (e: any) {
      message.error(e.response?.data?.detail || "关系拉取失败");
    } finally {
      setLoading(false);
    }
  };
  const fetchTables = async () => {
    try {
      const { data: d } = await client.get("/sql/tables");
      setTables(d || []);
    } catch (e: any) {
      message.error(e.response?.data?.detail || "表列表拉取失败");
    }
  };
  useEffect(() => {
    fetchData();
    fetchTables();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onCreate = async (values: any) => {
    try {
      await client.post("/ontology/relations", values);
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
      await client.delete(`/ontology/relations/${id}`);
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
        新增关系
      </Button>
      <Table
        rowKey="id"
        dataSource={data}
        columns={[
          { title: "源表", dataIndex: "source_table" },
          { title: "源字段", dataIndex: "source_field" },
          { title: "目标表", dataIndex: "target_table" },
          { title: "目标字段", dataIndex: "target_field" },
          { title: "关系类型", dataIndex: "relation_type", width: 100 },
          { title: "描述", dataIndex: "relation_label", ellipsis: true },
          {
            title: "操作",
            width: 90,
            render: (_: any, r: any) => (
              <Popconfirm title="确认删除？" onConfirm={() => onDelete(r.id)}>
                <Button size="small" danger>删除</Button>
              </Popconfirm>
            ),
          },
        ]}
        loading={loading}
        pagination={{ pageSize: 10 }}
        size="small"
      />
      <Modal
        title="新增关系定义"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} onFinish={onCreate} layout="vertical">
          <Form.Item name="source_table" label="源表" rules={[{ required: true, message: "请选择源表" }]}>
            <Select
              showSearch
              options={tableOptions}
              optionFilterProp="label"
              placeholder="选择源表"
              onChange={(v) => {
                loadFields(v, true);
                form.setFieldsValue({ source_field: undefined });
              }}
            />
          </Form.Item>
          <Form.Item name="source_field" label="源关联字段" rules={[{ required: true, message: "请选择源字段" }]}>
            <Select showSearch options={sourceFields} optionFilterProp="label" placeholder="选择源关联字段" />
          </Form.Item>
          <Form.Item name="target_table" label="目标表" rules={[{ required: true, message: "请选择目标表" }]}>
            <Select
              showSearch
              options={tableOptions}
              optionFilterProp="label"
              placeholder="选择目标表"
              onChange={(v) => {
                loadFields(v, false);
                form.setFieldsValue({ target_field: undefined });
              }}
            />
          </Form.Item>
          <Form.Item name="target_field" label="目标关联字段" rules={[{ required: true, message: "请选择目标字段" }]}>
            <Select showSearch options={targetFields} optionFilterProp="label" placeholder="选择目标关联字段" />
          </Form.Item>
          <Form.Item name="relation_type" label="关系类型">
            <Input placeholder="如 一对多 / 多对一" />
          </Form.Item>
          <Form.Item name="relation_label" label="关系描述">
            <Input placeholder="如 用户月表按号码关联投诉表" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function LogicalDefTable() {
  const [data, setData] = useState<any[]>([]);
  const [tables, setTables] = useState<{ table_name: string; table_comment: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  const fetchData = async () => {
    setLoading(true);
    try {
      const { data: d } = await client.get("/ontology/logical-defs");
      setData(d || []);
    } catch (e: any) {
      message.error(e.response?.data?.detail || "逻辑定义拉取失败");
    } finally {
      setLoading(false);
    }
  };
  const fetchTables = async () => {
    try {
      const { data: d } = await client.get("/sql/tables");
      setTables(d || []);
    } catch (e: any) {
      message.error(e.response?.data?.detail || "表列表拉取失败");
    }
  };
  useEffect(() => {
    fetchData();
    fetchTables();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onCreate = async (values: any) => {
    try {
      await client.post("/ontology/logical-defs", values);
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
      await client.delete(`/ontology/logical-defs/${id}`);
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
        新增口径
      </Button>
      <Table
        rowKey="id"
        dataSource={data}
        columns={[
          { title: "口径名", dataIndex: "def_name", width: 140 },
          { title: "适用表", dataIndex: "table_name", width: 220 },
          { title: "口径描述", dataIndex: "def_desc", ellipsis: true },
          { title: "条件片段", dataIndex: "def_condition", ellipsis: true },
          {
            title: "操作",
            width: 90,
            render: (_: any, r: any) => (
              <Popconfirm title="确认删除？" onConfirm={() => onDelete(r.id)}>
                <Button size="small" danger>删除</Button>
              </Popconfirm>
            ),
          },
        ]}
        loading={loading}
        pagination={{ pageSize: 10 }}
        size="small"
      />
      <Modal
        title="新增逻辑定义"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} onFinish={onCreate} layout="vertical">
          <Form.Item name="def_name" label="口径名" rules={[{ required: true, message: "请输入口径名" }]}>
            <Input placeholder="如 沉默用户" />
          </Form.Item>
          <Form.Item name="table_name" label="适用表" rules={[{ required: true, message: "请选择表" }]}>
            <Select showSearch options={tableOptions} optionFilterProp="label" placeholder="选择适用表" />
          </Form.Item>
          <Form.Item name="def_desc" label="口径描述" rules={[{ required: true, message: "请输入口径描述" }]}>
            <Input.TextArea rows={2} placeholder="如 当月无通话次数且无GPRS流量" />
          </Form.Item>
          <Form.Item name="def_condition" label="精确条件片段（可选）">
            <Input.TextArea
              rows={3}
              placeholder={
                "用自然语言描述业务口径即可，LLM 会结合账期理解执行。如：\n" +
                "在账期开始至结束期间未订购策划610000149732的服务；查询D_CRM_INS_OFFER_D与D_CRM_INS_OFFER_H_D两表，使用最近分区p_day；有效订购=生效日期不晚于账期结束日且失效日期晚于账期开始日\n" +
                "可选精确控制：{p_mon} {开始} {结束} {月末分区}；场景标记 {A:当前生效} {B:时间段} {C:新增}"
              }
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function ObjectDefPanel() {
  const [objects, setObjects] = useState<any[]>([]);
  const [selected, setSelected] = useState<any | null>(null);
  const [tableComment, setTableComment] = useState("");
  const [tableDesc, setTableDesc] = useState("");
  const [fields, setFields] = useState<any[]>([]);
  const [editingField, setEditingField] = useState<string | null>(null); // 行内编辑的字段
  const [editDesc, setEditDesc] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);

  const fetchObjects = async () => {
    try {
      const { data: d } = await client.get("/ontology/objects");
      setObjects(d || []);
      if (selected) {
        const cur = (d || []).find((o: any) => o.table_name === selected.table_name);
        if (cur) selectObj(cur);
      }
    } catch (e: any) {
      message.error("对象定义拉取失败");
    }
  };

  const selectObj = async (obj: any) => {
    setSelected(obj);
    setTableComment(obj.table_comment || "");
    setTableDesc(obj.table_desc || "");
    try {
      const { data: meta } = await client.get("/ontology/field-meta", {
        params: { table: obj.table_name },
      });
      const metaMap: Record<string, string> = {};
      (meta || []).forEach((r: any) => {
        metaMap[r.field_name] = r.field_desc || "";
      });
      setFields(
        (obj.columns || []).map((c: any) => ({
          field: c.name,
          type: c.type,
          comment: c.comment || "",
          is_partition: !!c.is_partition,
          desc: metaMap[c.name] || "",
        }))
      );
    } catch (e: any) {
      message.error("字段加载失败");
    }
  };

  useEffect(() => {
    fetchObjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveTableComment = async () => {
    if (!selected) return;
    try {
      await client.patch(`/ontology/objects/${selected.table_name}`, {
        table_comment: tableComment,
      });
      message.success("表中文名已保存");
      fetchObjects();
    } catch (e: any) {
      message.error(e.response?.data?.detail || "保存失败");
    }
  };

  const saveTableDesc = async () => {
    if (!selected) return;
    try {
      await client.patch(`/ontology/objects/${selected.table_name}/desc`, {
        table_desc: tableDesc,
      });
      message.success("表描述已保存");
      fetchObjects();
    } catch (e: any) {
      message.error(e.response?.data?.detail || "保存失败");
    }
  };

  // 字段描述行内编辑：点击描述直接编辑，回车/失焦保存（前台可视、所见即所得）
  const openEditDesc = (f: any) => {
    setEditingField(f.field);
    setEditDesc(f.desc);
  };

  const saveDesc = async (field: string) => {
    if (!selected || !field) return;
    try {
      await client.post("/ontology/field-meta", {
        table_name: selected.table_name,
        field_name: field,
        field_desc: editDesc,
      });
      message.success(`字段 ${field} 描述已保存`);
      setEditingField(null);
      fetchObjects(); // 刷新后描述直接可见
    } catch (e: any) {
      message.error(e.response?.data?.detail || "保存失败");
    }
  };

  const doImport = async () => {
    if (!importText.trim() && !importFile) {
      message.warning("请粘贴 TSV 文本或上传 Excel");
      return;
    }
    setImporting(true);
    try {
      const fd = new FormData();
      if (importFile) fd.append("file", importFile);
      else fd.append("text", importText);
      const { data } = await client.post("/ontology/import-field-meta", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      message.success(
        `导入成功：${data.imported} 条字段描述，${data.table_comments_updated} 个表注释已更新`
      );
      setImportOpen(false);
      setImportText("");
      setImportFile(null);
      fetchObjects();
    } catch (e: any) {
      message.error(e.response?.data?.detail || "导入失败");
    } finally {
      setImporting(false);
    }
  };

  return (
    <Row gutter={16}>
      <Col span={5}>
        <Space style={{ marginBottom: 12 }}>
          <Button type="primary" onClick={() => setImportOpen(true)}>
            批量导入
          </Button>
        </Space>
        <List
          size="small"
          bordered
          dataSource={objects}
          style={{ maxHeight: 620, overflow: "auto" }}
          renderItem={(o: any) => (
            <List.Item
              onClick={() => selectObj(o)}
              style={{
                cursor: "pointer",
                background: selected?.table_name === o.table_name ? "#e6f4ff" : undefined,
                paddingLeft: 12,
              }}
            >
              <List.Item.Meta
                title={<span style={{ fontSize: 13 }}>{o.table_name}</span>}
                description={
                  <span style={{ fontSize: 12 }}>
                    {o.table_comment || "（未填描述）"} · {o.columns?.length || 0} 字段
                  </span>
                }
              />
            </List.Item>
          )}
        />
      </Col>
      <Col span={19}>
        {selected ? (
          <>
            <Card
              size="small"
              title={`对象定义 · ${selected.table_name}`}
              style={{ marginBottom: 16 }}
            >
              <Space direction="vertical" style={{ width: "100%", marginBottom: 12 }}>
                <Space wrap>
                  <span>表中文名：</span>
                  <Input
                    style={{ width: 300 }}
                    value={tableComment}
                    onChange={(e) => setTableComment(e.target.value)}
                    placeholder="如 用户统一视图月表"
                  />
                  <Button type="primary" onClick={saveTableComment}>
                    保存中文名
                  </Button>
                </Space>
                <Space wrap align="start">
                  <span>表描述：</span>
                  <Input.TextArea
                    rows={2}
                    style={{ width: 420 }}
                    value={tableDesc}
                    onChange={(e) => setTableDesc(e.target.value)}
                    placeholder="如 记录用户每月通话/流量使用情况，用于沉默用户识别"
                  />
                  <Button type="primary" onClick={saveTableDesc}>
                    保存表描述
                  </Button>
                </Space>
              </Space>
              <Table
                rowKey="field"
                dataSource={fields}
                size="small"
                pagination={false}
                scroll={{ y: 380 }}
                columns={[
                  {
                    title: "物理字段名",
                    dataIndex: "field",
                    width: 220,
                    render: (v: string, r: any) => (
                      <span>
                        {v}
                        {r.is_partition ? (
                          <Tag color="blue" style={{ marginLeft: 6 }}>
                            分区
                          </Tag>
                        ) : null}
                      </span>
                    ),
                  },
                  {
                    title: "中文字段名",
                    dataIndex: "comment",
                    width: 180,
                    render: (v: string) =>
                      v || <span style={{ color: "#999" }}>（未填）</span>,
                  },
                  {
                    title: "字段描述",
                    dataIndex: "desc",
                    render: (v: string, r: any) =>
                      editingField === r.field ? (
                        <Space size={4}>
                          <Input
                            size="small"
                            style={{ width: 280 }}
                            autoFocus
                            value={editDesc}
                            onChange={(e) => setEditDesc(e.target.value)}
                            onPressEnter={() => saveDesc(r.field)}
                            placeholder="输入字段描述（保存后旧描述失效，新描述生效）"
                          />
                          <Button
                            size="small"
                            type="primary"
                            onClick={() => saveDesc(r.field)}
                          >
                            确认
                          </Button>
                          <Button size="small" onClick={() => setEditingField(null)}>
                            取消
                          </Button>
                        </Space>
                      ) : (
                        <span
                          style={{
                            cursor: "pointer",
                            color: v ? undefined : "#999",
                            display: "block",
                          }}
                          title="点击编辑字段描述"
                          onClick={() => openEditDesc(r)}
                        >
                          {v || "（未填，点击填写）"}
                        </span>
                      ),
                  },
                ]}
              />
            </Card>
          </>
        ) : (
          <Card>
            <Empty description="从左侧选择一个对象（表）查看/维护定义" />
          </Card>
        )}
      </Col>
      <Modal
        title="批量导入字段描述"
        open={importOpen}
        onCancel={() => {
          setImportOpen(false);
          setImportText("");
          setImportFile(null);
        }}
        onOk={doImport}
        confirmLoading={importing}
        width={640}
      >
        <p style={{ marginBottom: 8 }}>粘贴 TSV 文本（数智本体文档导出格式）：</p>
        <Input.TextArea
          rows={8}
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          placeholder={
            "对象英文名称\t对象中文名称\t对象描述\t状态\t属性英文名\t属性中文名\t属性类型\t属性描述\t是否主键\t是否标题\n" +
            "D_XXX\t中文表名\t\t启用\t字段名\t中文名\tstring\t字段描述\t\t"
          }
        />
        <Divider>或</Divider>
        <Upload
          beforeUpload={(f) => {
            setImportFile(f);
            return false;
          }}
          maxCount={1}
          fileList={[]}
        >
          <Button icon={<UploadOutlined />}>上传 Excel（对象信息 sheet）</Button>
        </Upload>
        {importFile && <div style={{ marginTop: 8 }}>已选文件：{importFile.name}</div>}
      </Modal>
    </Row>
  );
}


export default function Ontology() {
  return (
    <Card title="本体定义">
      <Tabs
        items={[
          {
            key: "objects",
            label: "对象定义",
            children: <ObjectDefPanel />,
          },
          {
            key: "relations",
            label: "关系定义",
            children: <RelationTable />,
          },
          {
            key: "logical-defs",
            label: "逻辑定义",
            children: <LogicalDefTable />,
          },
        ]}
      />
    </Card>
  );
}
