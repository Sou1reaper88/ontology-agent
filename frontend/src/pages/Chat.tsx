import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Checkbox,
  Empty,
  Input,
  Layout,
  List,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Steps,
  Typography,
  message,
} from "antd";
import {
  PlusOutlined,
  SendOutlined,
  SettingOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  CopyOutlined,
  EditOutlined,
  ClearOutlined,
} from "@ant-design/icons";
import client from "../api/client";

const { Sider, Content } = Layout;
const { Text, Paragraph } = Typography;

interface ConvItem {
  id: number;
  title: string;
  context: string | null;
  last_message: string | null;
  updated_at: string;
}

interface Msg {
  id: number;
  role: "user" | "assistant";
  content: string;
  sql: string | null;
  query_id: number | null;
  trace: any[] | null; // 历史消息的完整链路步骤（完成态）
  steps: any[] | null; // 实时轮询中的链路步骤（增量）
  generating: boolean; // 生成中占位
  error: string | null;
  created_at: string;
}

// 生成链路步骤条：实时滚动展示每步（检索→映射→生成→校验→输出）
function TraceSteps({ steps, generating }: { steps: any[]; generating?: boolean }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const items = steps.map((s: any, i: number) => {
    let status: "wait" | "process" | "finish" | "error" = "finish";
    if (generating && i === steps.length - 1) status = "process";
    if (s.status === "error") status = "error";
    return {
      title: (
        <span style={{ fontSize: 13 }}>
          {s.label || s.node}
          {s.duration_ms != null && (
            <span style={{ color: "#999", fontWeight: 400 }}> · {s.duration_ms}ms</span>
          )}
        </span>
      ),
      description: (
        <div style={{ fontSize: 12 }}>
          {s.summary || (status === "process" ? "执行中…" : "")}
          {expanded === i && (
            <div style={{ marginTop: 4, color: "#999" }}>
              node: {s.node} · status: {s.status}
            </div>
          )}
        </div>
      ),
      status,
    };
  });
  return (
    <div
      style={{
        margin: "8px 0",
        background: "#fff",
        borderRadius: 6,
        border: "1px solid #f0f0f0",
        padding: "6px 10px",
      }}
    >
      <div
        style={{ fontSize: 12, color: "#666", marginBottom: 4, cursor: "pointer" }}
        onClick={() => setExpanded(expanded === -1 ? null : -1)}
      >
        生成链路{generating ? "（生成中…）" : ""} {steps.length} 步
      </div>
      <Steps size="small" direction="vertical" items={items} />
    </div>
  );
}

export default function Chat() {
  const navigate = useNavigate();
  const [convs, setConvs] = useState<ConvItem[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [isNewDraft, setIsNewDraft] = useState(false); // 未保存的新对话草稿态（首条消息发送后才落库）
  const [messages, setMessages] = useState<Msg[]>([]);
  const [context, setContext] = useState<string>("");
  const [input, setInput] = useState("");
  const [loadingList, setLoadingList] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState(false);
  const [sending, setSending] = useState(false);
  const [ctxOpen, setCtxOpen] = useState(false);
  const [ctxDraft, setCtxDraft] = useState("");
  const [editing, setEditing] = useState<{ msgId: number; sql: string } | null>(null); // SQL 编辑态
  const [executingId, setExecutingId] = useState<number | null>(null); // 正在执行的消息 id
  const [selectMode, setSelectMode] = useState(false); // 批量选择模式
  const [selectedIds, setSelectedIds] = useState<number[]>([]); // 批量选中的对话 id
  const [clearing, setClearing] = useState(false); // 清空中
  const [batchDeleting, setBatchDeleting] = useState(false); // 批量删除中
  const listRef = useRef<HTMLDivElement>(null);

  const loadConvs = useCallback(async () => {
    setLoadingList(true);
    try {
      const { data } = await client.get("/conversations");
      setConvs(data || []);
    } catch (e: any) {
      message.error(e.response?.data?.detail || "对话列表加载失败");
    } finally {
      setLoadingList(false);
    }
  }, []);

  const loadMessages = useCallback(async (id: number) => {
    setLoadingMsg(true);
    try {
      const { data } = await client.get(`/conversations/${id}`);
      setMessages(
        (data.messages || []).map((m: any) => ({
          ...m,
          steps: m.trace || null,
          generating: false,
          error: null,
        }))
      );
      setContext(data.context || "");
    } catch (e: any) {
      message.error(e.response?.data?.detail || "对话加载失败");
    } finally {
      setLoadingMsg(false);
    }
  }, []);

  useEffect(() => {
    loadConvs();
  }, [loadConvs]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: 99999 });
  }, [messages]);

  const openConv = (id: number) => {
    setIsNewDraft(false);
    setActiveId(id);
    loadMessages(id);
  };

  const newConv = () => {
    // 仅进入草稿态：不落库，发送第一条消息时才真正创建对话
    setIsNewDraft(true);
    setActiveId(null);
    setMessages([]);
    setContext("");
  };

  const send = async () => {
    const content = input.trim();
    if (!content || sending) return;
    setSending(true);
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: -Date.now(), role: "user", content, sql: null, query_id: null, trace: null, steps: null, generating: false, error: null, created_at: "" },
    ]);
    try {
      // 草稿态：首条消息先创建对话（标题取首条消息前 20 字），再发消息
      let convId = activeId;
      if (!convId && isNewDraft) {
        const { data: created } = await client.post("/conversations", {
          title: content.slice(0, 20),
        });
        convId = created.id;
        setIsNewDraft(false);
      }
      if (!convId) throw new Error("对话未就绪");
      // 异步生成：立即返回 generating，随后轮询链路步骤
      const { data } = await client.post(`/conversations/${convId}/messages`, {
        content,
        system_time: new Date().toISOString().slice(0, 10),
      });
      setActiveId(convId);
      setMessages((prev) => [
        ...prev, // 保留乐观添加的 user 消息（id 为负数），仅追加 assistant 占位
        {
          id: data.message_id,
          role: "assistant",
          content: "",
          sql: null,
          query_id: null,
          trace: null,
          steps: [],
          generating: true,
          error: null,
          created_at: "",
        },
      ]);
      pollMessage(convId, data.message_id);
    } catch (e: any) {
      setMessages((prev) => prev.filter((m) => m.id > 0));
      message.error(e.response?.data?.detail || "消息发送失败");
    } finally {
      setSending(false);
    }
  };

  const pollMessage = (convId: number, msgId: number) => {
    const timer = window.setInterval(async () => {
      try {
        const { data } = await client.get(`/conversations/messages/${msgId}/status`);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === msgId
              ? {
                  ...m,
                  steps: data.steps || [],
                  generating: data.status === "generating",
                  error: data.error || null,
                }
              : m
          )
        );
        if (data.status === "success") {
          window.clearInterval(timer);
          // 重新拉取对话详情，拿到最终内容/SQL/链路 trace
          const detail = await client.get(`/conversations/${convId}`);
          setMessages(detail.data.messages || []);
          loadConvs();
        } else if (data.status === "failed") {
          window.clearInterval(timer);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === msgId
                ? { ...m, content: data.error || "生成失败", generating: false, error: data.error || null }
                : m
            )
          );
          loadConvs();
        }
      } catch {
        window.clearInterval(timer);
      }
    }, 800);
  };

  const saveContext = async () => {
    if (!activeId) return;
    try {
      await client.patch(`/conversations/${activeId}`, { context: ctxDraft });
      setContext(ctxDraft);
      setCtxOpen(false);
      message.success("上下文已保存");
      loadConvs();
    } catch (e: any) {
      message.error(e.response?.data?.detail || "保存失败");
    }
  };

  const removeConv = async (id: number) => {
    try {
      await client.delete(`/conversations/${id}`);
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
        setContext("");
      }
      loadConvs();
    } catch (e: any) {
      message.error(e.response?.data?.detail || "删除失败");
    }
  };

  const enterSelectMode = () => {
    setSelectMode(true);
    setSelectedIds([]);
  };

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelectedIds([]);
  };

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const selectAll = () => {
    setSelectedIds((prev) =>
      prev.length === convs.length ? [] : convs.map((c) => c.id)
    );
  };

  // 删除选中对话后，若当前打开的对话被删则清空主区域
  const afterDeleted = (ids: number[]) => {
    if (activeId != null && ids.includes(activeId)) {
      setActiveId(null);
      setMessages([]);
      setContext("");
    }
  };

  const batchRemove = async () => {
    if (!selectedIds.length || batchDeleting) return;
    setBatchDeleting(true);
    try {
      const { data } = await client.post("/conversations/batch-delete", {
        ids: selectedIds,
      });
      message.success(`已删除 ${data.deleted} 个对话`);
      afterDeleted(data.ids || []);
      setSelectedIds([]);
      setSelectMode(false);
      loadConvs();
    } catch (e: any) {
      message.error(e.response?.data?.detail || "批量删除失败");
    } finally {
      setBatchDeleting(false);
    }
  };

  const clearAll = async () => {
    if (clearing) return;
    setClearing(true);
    try {
      const { data } = await client.post("/conversations/clear-all");
      message.success(`已清空 ${data.deleted} 个对话`);
      setActiveId(null);
      setMessages([]);
      setContext("");
      setSelectedIds([]);
      setSelectMode(false);
      loadConvs();
    } catch (e: any) {
      message.error(e.response?.data?.detail || "清空失败");
    } finally {
      setClearing(false);
    }
  };

  const confirmClearAll = () => {
    Modal.confirm({
      title: "清空全部对话？",
      content: `将删除全部 ${convs.length} 个对话及其消息记录，此操作不可恢复。`,
      okText: "清空",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: clearAll,
    });
  };

  const copySql = (sql: string) => {
    navigator.clipboard?.writeText(sql);
    message.success("SQL 已复制");
  };

  const runOriginal = async (msgId: number, queryId: number) => {
    setExecutingId(msgId);
    try {
      await client.post("/execute", { query_id: queryId });
      navigate(`/result/${queryId}`);
    } catch (e: any) {
      message.error(e.response?.data?.detail || "执行失败");
    } finally {
      setExecutingId(null);
    }
  };

  const runEdited = async (msgId: number, sql: string) => {
    setExecutingId(msgId);
    try {
      const { data } = await client.post("/execute", { sql });
      setEditing(null);
      navigate(`/result/${data.query_id}`);
    } catch (e: any) {
      message.error(e.response?.data?.detail || "执行失败");
    } finally {
      setExecutingId(null);
    }
  };

  return (
    <Layout style={{ height: "calc(100vh - 130px)", background: "transparent" }}>
      <Sider
        width={280}
        style={{
          background: "#fff",
          borderRadius: 8,
          marginRight: 16,
          padding: 12,
          position: "relative",
          height: "100%",
          overflow: "hidden",
          flexShrink: 0,
        }}
      >
        <Button type="primary" icon={<PlusOutlined />} block onClick={newConv}>
          新建对话
        </Button>
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          {selectMode ? (
            <>
              <Button
                size="small"
                block
                onClick={selectAll}
                disabled={!convs.length}
              >
                {selectedIds.length === convs.length && convs.length > 0 ? "取消全选" : "全选"}
              </Button>
              <Button
                size="small"
                block
                danger
                icon={<DeleteOutlined />}
                disabled={!selectedIds.length}
                loading={batchDeleting}
                onClick={batchRemove}
              >
                删除({selectedIds.length})
              </Button>
              <Button size="small" block onClick={exitSelectMode}>
                完成
              </Button>
            </>
          ) : (
            <>
              <Button
                size="small"
                block
                icon={<DeleteOutlined />}
                disabled={!convs.length}
                onClick={enterSelectMode}
              >
                批量删除
              </Button>
              <Button
                size="small"
                block
                danger
                icon={<ClearOutlined />}
                disabled={!convs.length}
                onClick={confirmClearAll}
              >
                清空全部
              </Button>
            </>
          )}
        </div>
        <div
          style={{
            position: "absolute",
            top: 100,
            bottom: 8,
            left: 12,
            right: 12,
            overflowY: "auto",
          }}
        >
          <Spin spinning={loadingList}>
            <List
              dataSource={convs}
              locale={{ emptyText: <Empty description="暂无对话" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
              renderItem={(c) => (
                <List.Item
                  key={c.id}
                  onClick={() => (selectMode ? toggleSelect(c.id) : openConv(c.id))}
                  style={{
                    cursor: "pointer",
                    padding: "8px 10px",
                    borderRadius: 6,
                    background:
                      selectMode
                        ? selectedIds.includes(c.id)
                          ? "#fff1f0"
                          : "transparent"
                        : c.id === activeId
                          ? "#e6f4ff"
                          : "transparent",
                    display: "block",
                  }}
                  actions={
                    selectMode
                      ? []
                      : [
                          <Popconfirm key="del" title="删除该对话？" onConfirm={() => removeConv(c.id)}>
                            <DeleteOutlined style={{ color: "#999" }} />
                          </Popconfirm>,
                        ]
                  }
                >
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                    {selectMode && (
                      <Checkbox
                        checked={selectedIds.includes(c.id)}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => toggleSelect(c.id)}
                        style={{ marginTop: 2 }}
                      />
                    )}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 500, fontSize: 13 }}>{c.title}</div>
                      <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                        {c.last_message || "（空）"}
                      </Text>
                    </div>
                  </div>
                </List.Item>
              )}
            />
          </Spin>
        </div>
      </Sider>

      <Content
        style={{
          background: "#fff",
          borderRadius: 8,
          padding: 16,
          display: "flex",
          flexDirection: "column",
          height: "100%",
          overflow: "hidden",
        }}
      >
        {!activeId && !isNewDraft ? (
          <div
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Empty description="新建或选择左侧对话开始取数" />
          </div>
        ) : (
          <>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 12,
                paddingBottom: 12,
                borderBottom: "1px solid #f0f0f0",
              }}
            >
              <Space>
                <Text strong style={{ fontSize: 15 }}>
                  {isNewDraft ? "新对话（未保存）" : convs.find((c) => c.id === activeId)?.title || "对话"}
                </Text>
                {context && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    上下文已设置
                  </Text>
                )}
              </Space>
              {activeId && (
                <Button size="small" icon={<SettingOutlined />} onClick={() => { setCtxDraft(context); setCtxOpen(true); }}>
                  上下文设置
                </Button>
              )}
            </div>

            <div ref={listRef} style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
              <Spin spinning={loadingMsg}>
                {messages.map((m) =>
                  m.role === "user" ? (
                    <div key={m.id} style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
                      <div
                        style={{
                          maxWidth: "70%",
                          background: "#1677ff",
                          color: "#fff",
                          borderRadius: 8,
                          padding: "8px 12px",
                          whiteSpace: "pre-wrap",
                        }}
                      >
                        {m.content}
                      </div>
                    </div>
                  ) : (
                    <div key={m.id} style={{ marginBottom: 12 }}>
                      <div
                        style={{
                          maxWidth: "85%",
                          background: "#f6f6f6",
                          borderRadius: 8,
                          padding: "8px 12px",
                        }}
                      >
                        <div style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{m.content}</div>
                        {(m.trace && m.trace.length > 0) || (m.steps && m.steps.length > 0) ? (
                          <TraceSteps
                            steps={(m.trace && m.trace.length > 0 ? m.trace : m.steps) || []}
                            generating={m.generating}
                          />
                        ) : null}
                        {m.sql && (
                          <div
                            style={{
                              marginTop: 8,
                              background: "#1e1e1e",
                              color: "#d4d4d4",
                              borderRadius: 6,
                              padding: 10,
                              fontSize: 12,
                              overflow: "auto",
                            }}
                          >
                            {editing?.msgId === m.id ? (
                              <>
                                <Input.TextArea
                                  value={editing.sql}
                                  onChange={(e) =>
                                    setEditing({ msgId: m.id, sql: e.target.value })
                                  }
                                  rows={8}
                                  style={{
                                    fontFamily: "monospace",
                                    fontSize: 12,
                                    background: "#1e1e1e",
                                    color: "#d4d4d4",
                                    border: "1px solid #444",
                                  }}
                                />
                                <Space style={{ marginTop: 8 }}>
                                  <Button
                                    size="small"
                                    type="primary"
                                    loading={executingId === m.id}
                                    onClick={() => runEdited(m.id, editing.sql)}
                                  >
                                    执行修改后 SQL
                                  </Button>
                                  <Button size="small" onClick={() => setEditing(null)}>
                                    取消
                                  </Button>
                                </Space>
                              </>
                            ) : (
                              <>
                                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{m.sql}</pre>
                                <Button
                                  size="small"
                                  icon={<EditOutlined />}
                                  style={{ marginTop: 8 }}
                                  onClick={() => setEditing({ msgId: m.id, sql: m.sql! })}
                                >
                                  编辑 SQL
                                </Button>
                              </>
                            )}
                          </div>
                        )}
                        <Space style={{ marginTop: 8 }}>
                          {m.query_id && !(editing?.msgId === m.id) && (
                            <Button
                              size="small"
                              type="primary"
                              icon={<PlayCircleOutlined />}
                              loading={executingId === m.id}
                              onClick={() => runOriginal(m.id, m.query_id!)}
                            >
                              执行取数
                            </Button>
                          )}
                          {m.sql && (
                            <Button
                              size="small"
                              icon={<CopyOutlined />}
                              onClick={() => copySql(m.sql!)}
                            >
                              复制 SQL
                            </Button>
                          )}
                        </Space>
                      </div>
                    </div>
                  )
                )}
              </Spin>
            </div>

            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <Input.TextArea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="输入取数需求，可基于历史继续追问完善 SQL（如：把沉默时间改成 3 个月）"
                autoSize={{ minRows: 2, maxRows: 5 }}
                onPressEnter={(e) => {
                  if (!e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={sending}
                onClick={send}
                style={{ alignSelf: "flex-end" }}
              >
                发送
              </Button>
            </div>
          </>
        )}
      </Content>

      <Modal
        title="上下文设置"
        open={ctxOpen}
        onOk={saveContext}
        onCancel={() => setCtxOpen(false)}
        okText="保存"
        cancelText="取消"
      >
        <Paragraph type="secondary" style={{ fontSize: 12 }}>
          上下文作为常驻约束/补充信息，随每一轮提问一起发送给智能体（例如："用户范围为浙江省正常在网用户"、"账期统一为2026年6月"）。
        </Paragraph>
        <Input.TextArea
          value={ctxDraft}
          onChange={(e) => setCtxDraft(e.target.value)}
          placeholder="填写常驻约束或补充信息"
          rows={5}
        />
      </Modal>
    </Layout>
  );
}
