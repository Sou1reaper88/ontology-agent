import { useEffect, useState } from "react";
import { Button, Card, Input, Select, Space, Table, message } from "antd";
import client from "../api/client";

interface DatabaseItem {
  name: string;
  comment: string;
}

export default function DataQuery() {
  const [databases, setDatabases] = useState<DatabaseItem[]>([]);
  const [database, setDatabase] = useState<string>("ontology");
  const [sql, setSql] = useState("SHOW TABLES;");
  const [columns, setColumns] = useState<any[]>([]);
  const [rows, setRows] = useState<any[]>([]);
  const [resultType, setResultType] = useState<"result" | "ok" | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchDatabases = async () => {
    try {
      const { data } = await client.get("/sql/databases");
      const dbs: DatabaseItem[] = data || [];
      setDatabases(dbs);
      if (dbs.length && !dbs.some((d) => d.name === database)) {
        setDatabase(dbs[0].name);
      }
    } catch (e: any) {
      message.error("数据库列表拉取失败");
    }
  };

  useEffect(() => {
    fetchDatabases();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = async (sqlText?: string) => {
    const q = (sqlText ?? sql).trim();
    if (!q) return;
    setLoading(true);
    setResultType(null);
    try {
      const { data } = await client.post("/sql/execute", { sql: q, database });
      if (data.type === "result") {
        const cols: string[] = data.columns || [];
        setColumns(
          cols.map((c) => ({ title: c, dataIndex: c, key: c, ellipsis: true }))
        );
        setRows(
          (data.rows || []).map((r: any[], i: number) =>
            Object.fromEntries(cols.map((c, j) => [c, r[j]]))
          )
        );
        setResultType("result");
      } else {
        setColumns([]);
        setRows([]);
        setResultType("ok");
        message.success(data.message || "执行成功");
      }
    } catch (e: any) {
      message.error(e.response?.data?.detail || "执行失败");
    } finally {
      setLoading(false);
    }
  };

  const dbOptions = databases.map((d) => ({
    label: d.comment ? `${d.name}（${d.comment}）` : d.name,
    value: d.name,
  }));

  return (
    <Card title="数据查询">
      <Space style={{ marginBottom: 12 }}>
        <span>数据库：</span>
        <Select
          style={{ width: 260 }}
          showSearch
          value={database}
          onChange={setDatabase}
          options={dbOptions}
          optionFilterProp="label"
          placeholder="选择数据库"
        />
      </Space>
      <Input.TextArea
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        rows={8}
        style={{ fontFamily: "monospace", marginBottom: 12 }}
        placeholder={`输入 SQL，例如：\nSHOW TABLES;\nDESC d_bbzx_dw_product_m;\nCREATE TABLE d_xxx (id VARCHAR(255) COMMENT '编号') COMMENT='中文表名';`}
      />
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" loading={loading} onClick={() => run()}>
          执行
        </Button>
        <Button onClick={() => setSql("SHOW TABLES;")}>查看所有表</Button>
        <Button onClick={() => setSql("SHOW FULL TABLES;")}>查看表类型</Button>
      </Space>
      {resultType === "result" && (
        <Table
          dataSource={rows}
          columns={columns}
          rowKey={(_, i) => String(i)}
          pagination={{ pageSize: 20 }}
          size="small"
          scroll={{ x: true }}
        />
      )}
    </Card>
  );
}
