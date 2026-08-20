import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Button, Card, Result as AntResult, Spin, Table, message } from "antd";
import client from "../api/client";

export default function Result() {
  const { queryId } = useParams();
  const [columns, setColumns] = useState<any[]>([]);
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string>("pending");
  const [error, setError] = useState<string | null>(null);
  const fetchedRef = useRef(false);

  useEffect(() => {
    fetchedRef.current = false;
    setStatus("pending");
    setError(null);
    pollStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryId]);

  const fetchResult = async () => {
    setLoading(true);
    try {
      const { data } = await client.get(`/execute/result/${queryId}`);
      const cols: any[] = (data.columns || []).map((c: string) => ({
        title: c,
        dataIndex: c,
        key: c,
        ellipsis: true,
      }));
      setColumns(cols);
      setRows(
        (data.rows || []).map((r: any[], i: number) =>
          Object.fromEntries((data.columns as string[]).map((c, j) => [c, r[j]]))
        )
      );
    } catch (e: any) {
      message.error(e.response?.data?.detail || "结果拉取失败");
    } finally {
      setLoading(false);
    }
  };

  const pollStatus = async () => {
    try {
      const { data } = await client.get(`/execute/${queryId}`);
      setStatus(data.status);
      if (data.status === "success") {
        if (!fetchedRef.current) {
          fetchedRef.current = true;
          fetchResult();
        }
        return;
      }
      if (data.status === "failed") {
        setError("执行失败，请返回对话重新尝试");
        return;
      }
      // pending / running：继续轮询
      setTimeout(pollStatus, 1000);
    } catch (e) {
      // 查询异常，稍后重试
      setTimeout(pollStatus, 1500);
    }
  };

  const exportCsv = () => {
    const header = columns.map((c) => c.title).join(",");
    const body = rows
      .map((r) => columns.map((c) => r[c.dataIndex] ?? "").join(","))
      .join("\n");
    const blob = new Blob([`\uFEFF${header}\n${body}`], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `result_${queryId}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (status !== "success") {
    return (
      <Card title={`取数结果 #${queryId}`}>
        {status === "failed" ? (
          <AntResult status="error" title="执行失败" subTitle={error} />
        ) : (
          <div style={{ textAlign: "center", padding: 48 }}>
            <Spin size="large" />
            <p style={{ marginTop: 16, color: "#999" }}>
              {status === "pending" ? "任务排队中…" : "正在执行…"}
            </p>
          </div>
        )}
      </Card>
    );
  }

  return (
    <Card
      title={`取数结果 #${queryId}`}
      extra={
        <Button onClick={exportCsv} disabled={rows.length === 0}>
          导出 CSV
        </Button>
      }
    >
      <Table
        dataSource={rows}
        columns={columns}
        rowKey={(_, i) => String(i)}
        loading={loading}
        pagination={{ pageSize: 20 }}
        scroll={{ x: true }}
        size="small"
      />
    </Card>
  );
}
