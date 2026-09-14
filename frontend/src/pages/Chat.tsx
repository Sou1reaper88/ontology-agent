import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Drawer,
  Grid,
  Input,
  Modal,
  Select,
  Space,
  Typography,
  message,
} from "antd";
import {
  DatabaseOutlined,
  MenuOutlined,
  SendOutlined,
  SettingOutlined,
  PlusOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import client from "../api/client";
import { ConversationSidebar } from "../features/chat/ConversationSidebar";
import { MessageTimeline } from "../features/chat/MessageTimeline";
import { FeedbackIdentifier } from "../features/chat/FeedbackIdentifier";
import { OntologyEvidencePanel } from "../features/chat/OntologyEvidencePanel";
import { selectedEvidenceMessage } from "../features/chat/evidenceSelection";
import type {
  ChatMessage,
  ConversationItem,
  EditingSql,
} from "../features/chat/types";
import "./Chat.css";

const { Paragraph } = Typography;
type SavedPrompt = { id: number; name: string; content: string };

export default function Chat() {
  const navigate = useNavigate();
  const screens = Grid.useBreakpoint();
  const desktopConversations = screens.lg ?? true;
  const desktopEvidence = screens.xl ?? true;

  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [isNewDraft, setIsNewDraft] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [prompts, setPrompts] = useState<SavedPrompt[]>([]);
  const [selectedPromptId, setSelectedPromptId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [loadingList, setLoadingList] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [promptOpen, setPromptOpen] = useState(false);
  const [editingPromptId, setEditingPromptId] = useState<number | null>(null);
  const [promptName, setPromptName] = useState("");
  const [promptContent, setPromptContent] = useState("");
  const [editing, setEditing] = useState<EditingSql | null>(null);
  const [executingId, setExecutingId] = useState<number | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [clearing, setClearing] = useState(false);
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<number | null>(null);
  const [conversationDrawerOpen, setConversationDrawerOpen] = useState(false);
  const [evidenceDrawerOpen, setEvidenceDrawerOpen] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const evidenceMessage = selectedEvidenceMessage(messages, selectedEvidenceId);
  const activeEvidenceId = evidenceMessage?.id ?? null;
  const activeTitle = isNewDraft
    ? "新取数需求"
    : conversations.find((conversation) => conversation.id === activeId)?.title ||
      "智能取数";

  const loadConversations = useCallback(async () => {
    setLoadingList(true);
    try {
      const { data } = await client.get("/conversations");
      setConversations(data || []);
    } catch (error: any) {
      message.error(error.response?.data?.detail || "对话列表加载失败");
    } finally {
      setLoadingList(false);
    }
  }, []);

  const loadMessages = useCallback(async (id: number) => {
    setLoadingMessages(true);
    try {
      const { data } = await client.get(`/conversations/${id}`);
      setMessages(
        (data.messages || []).map((item: any) => ({
          ...item,
          steps: item.trace || null,
          generating: false,
          error: null,
        }))
      );
    } catch (error: any) {
      message.error(error.response?.data?.detail || "对话加载失败");
    } finally {
      setLoadingMessages(false);
    }
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: 99999, behavior: "smooth" });
  }, [messages]);

  const openConversation = (id: number) => {
    setIsNewDraft(false);
    setActiveId(id);
    setSelectedEvidenceId(null);
    setEditing(null);
    setConversationDrawerOpen(false);
    loadMessages(id);
  };

  const newConversation = () => {
    setIsNewDraft(true);
    setActiveId(null);
    setMessages([]);
    setSelectedEvidenceId(null);
    setEditing(null);
    setConversationDrawerOpen(false);
  };

  const pollMessage = (conversationId: number, messageId: number) => {
    const timer = window.setInterval(async () => {
      try {
        const { data } = await client.get(
          `/conversations/messages/${messageId}/status`
        );
        setMessages((previous) =>
          previous.map((item) =>
            item.id === messageId
              ? {
                  ...item,
                  steps: data.steps || [],
                  generating: data.status === "generating",
                  error: data.error || null,
                  ontology_shadow: data.ontology_shadow || null,
                  program: data.program || null,
                }
              : item
          )
        );
        if (data.status === "success") {
          window.clearInterval(timer);
          const detail = await client.get(`/conversations/${conversationId}`);
          setMessages(detail.data.messages || []);
          loadConversations();
        } else if (data.status === "failed") {
          window.clearInterval(timer);
          setMessages((previous) =>
            previous.map((item) =>
              item.id === messageId
                ? {
                    ...item,
                    content: data.error || "生成失败",
                    generating: false,
                    error: data.error || null,
                  }
                : item
            )
          );
          loadConversations();
        }
      } catch {
        window.clearInterval(timer);
      }
    }, 800);
  };

  const send = async () => {
    const content = input.trim();
    if (!content || sending) return;

    setSending(true);
    setInput("");
    setMessages((previous) => [
      ...previous,
      {
        id: -Date.now(),
        role: "user",
        content,
        sql: null,
        query_id: null,
        trace: null,
        steps: null,
        generating: false,
        error: null,
        ontology_shadow: null,
        program: null,
        created_at: "",
      },
    ]);

    try {
      let conversationId = activeId;
      if (!conversationId && isNewDraft) {
        const { data: created } = await client.post("/conversations", {
          title: content.slice(0, 20),
        });
        conversationId = created.id;
        setIsNewDraft(false);
      }
      if (!conversationId) throw new Error("对话未就绪");

      const { data } = await client.post(
        `/conversations/${conversationId}/messages`,
        {
          content,
          system_time: new Date().toISOString().slice(0, 10),
          prompt_id: selectedPromptId,
        }
      );
      setSelectedPromptId(null);
      setActiveId(conversationId);
      setMessages((previous) => [
        ...previous,
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
          ontology_shadow: null,
          program: null,
          created_at: "",
        },
      ]);
      pollMessage(conversationId, data.message_id);
    } catch (error: any) {
      setMessages((previous) => previous.filter((item) => item.id > 0));
      message.error(error.response?.data?.detail || "消息发送失败");
    } finally {
      setSending(false);
    }
  };

  const loadPrompts = async () => {
    try {
      const { data } = await client.get("/prompts");
      setPrompts(data || []);
    } catch (error: any) {
      message.error(error.response?.data?.detail || "提示词加载失败");
    }
  };

  const openPrompts = async () => {
    await loadPrompts();
    setPromptOpen(true);
  };

  const newPrompt = () => {
    setEditingPromptId(null); setPromptName(""); setPromptContent("");
  };

  const editPrompt = (id: number | null) => {
    const item = prompts.find((prompt) => prompt.id === id);
    setEditingPromptId(item?.id ?? null);
    setPromptName(item?.name ?? ""); setPromptContent(item?.content ?? "");
  };

  const savePrompt = async () => {
    if (!promptName.trim() || !promptContent.trim()) return message.warning("请填写名称和提示词内容");
    try {
      if (editingPromptId) await client.patch(`/prompts/${editingPromptId}`, { name: promptName, content: promptContent });
      else await client.post("/prompts", { name: promptName, content: promptContent });
      message.success("提示词已保存"); newPrompt(); await loadPrompts();
    } catch (error: any) { message.error(error.response?.data?.detail || "保存失败"); }
  };

  const deletePromptNow = async () => {
    if (!editingPromptId) return;
    try {
      await client.delete(`/prompts/${editingPromptId}`);
      if (selectedPromptId === editingPromptId) setSelectedPromptId(null);
      message.success("提示词已删除"); newPrompt(); await loadPrompts();
    } catch (error: any) { message.error(error.response?.data?.detail || "删除失败"); }
  };

  const deletePrompt = () => Modal.confirm({
    title: "删除这个共享提示词？",
    content: "所有用户都将无法再选择它；已经发送的轮次不受影响。",
    okText: "删除", okButtonProps: { danger: true }, cancelText: "取消",
    onOk: deletePromptNow,
  });

  const removeConversation = async (id: number) => {
    try {
      await client.delete(`/conversations/${id}`);
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
        setSelectedEvidenceId(null);
      }
      loadConversations();
    } catch (error: any) {
      message.error(error.response?.data?.detail || "删除失败");
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
    setSelectedIds((previous) =>
      previous.includes(id)
        ? previous.filter((selectedId) => selectedId !== id)
        : [...previous, id]
    );
  };

  const selectAll = () => {
    setSelectedIds((previous) =>
      previous.length === conversations.length
        ? []
        : conversations.map((conversation) => conversation.id)
    );
  };

  const afterDeleted = (ids: number[]) => {
    if (activeId != null && ids.includes(activeId)) {
      setActiveId(null);
      setMessages([]);
      setSelectedEvidenceId(null);
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
      loadConversations();
    } catch (error: any) {
      message.error(error.response?.data?.detail || "批量删除失败");
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
      setSelectedEvidenceId(null);
      setSelectedIds([]);
      setSelectMode(false);
      loadConversations();
    } catch (error: any) {
      message.error(error.response?.data?.detail || "清空失败");
    } finally {
      setClearing(false);
    }
  };

  const confirmClearAll = () => {
    Modal.confirm({
      title: "清空全部对话？",
      content: `将删除全部 ${conversations.length} 个对话及其消息记录，此操作不可恢复。`,
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

  const runOriginal = async (messageId: number, queryId: number) => {
    setExecutingId(messageId);
    try {
      await client.post("/execute", { query_id: queryId });
      navigate(`/result/${queryId}`);
    } catch (error: any) {
      message.error(error.response?.data?.detail || "执行失败");
    } finally {
      setExecutingId(null);
    }
  };

  const runEdited = async (messageId: number, sql: string) => {
    setExecutingId(messageId);
    try {
      const { data } = await client.post("/execute", { sql });
      setEditing(null);
      navigate(`/result/${data.query_id}`);
    } catch (error: any) {
      message.error(error.response?.data?.detail || "执行失败");
    } finally {
      setExecutingId(null);
    }
  };

  const selectEvidence = (selectedMessage: ChatMessage) => {
    setSelectedEvidenceId(selectedMessage.id);
    if (!desktopEvidence) setEvidenceDrawerOpen(true);
  };

  const sidebar = (
    <ConversationSidebar
      conversations={conversations}
      activeId={activeId}
      loading={loadingList}
      selectMode={selectMode}
      selectedIds={selectedIds}
      batchDeleting={batchDeleting}
      clearing={clearing}
      onNew={newConversation}
      onOpen={openConversation}
      onEnterSelectMode={enterSelectMode}
      onExitSelectMode={exitSelectMode}
      onToggleSelect={toggleSelect}
      onSelectAll={selectAll}
      onBatchRemove={batchRemove}
      onClearAll={confirmClearAll}
      onRemove={removeConversation}
    />
  );

  const evidence = (
    <OntologyEvidencePanel result={evidenceMessage?.ontology_shadow ?? null} />
  );

  return (
    <>
      <section className="chat-workbench" aria-label="智能取数工作台">
        {desktopConversations ? (
          <aside className="chat-conversation-panel" aria-label="取数会话">
            {sidebar}
          </aside>
        ) : null}

        <section className="chat-main-panel">
          <header className="chat-main-header">
            <div className="chat-title-group">
              {!desktopConversations ? (
                <Button
                  type="text"
                  icon={<MenuOutlined />}
                  onClick={() => setConversationDrawerOpen(true)}
                >
                  会话
                </Button>
              ) : null}
              <div>
                <span>智能取数工作台</span>
                <h1>{activeTitle}</h1>
                <FeedbackIdentifier conversationId={activeId} />
                {selectedPromptId ? <small>下一轮将应用所选提示词，发送后自动取消</small> : null}
              </div>
            </div>

            <div className="chat-header-actions">
              {!desktopEvidence ? (
                <Button
                  icon={<DatabaseOutlined />}
                  onClick={() => setEvidenceDrawerOpen(true)}
                >
                  本体依据
                </Button>
              ) : null}
              {activeId || isNewDraft ? (
                <Button
                  icon={<SettingOutlined />}
                  onClick={openPrompts}
                >
                  提示词
                </Button>
              ) : null}
            </div>
          </header>

          {!activeId && !isNewDraft ? (
            <div className="chat-start-state">
              <span className="chat-start-mark" aria-hidden="true" />
              <span>从业务问题开始</span>
              <h2>描述你的取数需求</h2>
              <p>智能体会结合已发布本体，展示 SQL、业务账期和语义依据。</p>
              <Button type="primary" onClick={newConversation}>
                新建取数需求
              </Button>
            </div>
          ) : (
            <>
              <MessageTimeline
                conversationId={activeId}
                messages={messages}
                loading={loadingMessages}
                listRef={listRef}
                editing={editing}
                executingId={executingId}
                selectedEvidenceId={activeEvidenceId}
                onEditChange={setEditing}
                onCancelEdit={() => setEditing(null)}
                onRunEdited={runEdited}
                onRunOriginal={runOriginal}
                onCopySql={copySql}
                onSelectEvidence={selectEvidence}
              />

              <div className="chat-composer">
                <Input.TextArea
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  placeholder="输入取数需求，可继续追问完善 SQL；Enter 发送，Shift+Enter 换行"
                  autoSize={{ minRows: 2, maxRows: 5 }}
                  onPressEnter={(event) => {
                    if (!event.shiftKey) {
                      event.preventDefault();
                      send();
                    }
                  }}
                />
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  loading={sending}
                  onClick={send}
                >
                  发送
                </Button>
              </div>
            </>
          )}
        </section>

        {desktopEvidence ? (
          <aside className="chat-evidence-panel" aria-label="本体依据">
            <header className="chat-evidence-heading">
              <span>Ontology evidence</span>
              <h2>本体依据</h2>
            </header>
            <div className="chat-evidence-scroll">{evidence}</div>
          </aside>
        ) : null}
      </section>

      {!desktopConversations ? (
        <Drawer
          title="取数会话"
          placement="left"
          width={320}
          open={conversationDrawerOpen}
          onClose={() => setConversationDrawerOpen(false)}
          styles={{ body: { padding: 16 } }}
        >
          {sidebar}
        </Drawer>
      ) : null}

      {!desktopEvidence ? (
        <Drawer
          title="本体依据"
          placement="right"
          width={390}
          open={evidenceDrawerOpen}
          onClose={() => setEvidenceDrawerOpen(false)}
          styles={{ body: { padding: 18 } }}
        >
          {evidence}
        </Drawer>
      ) : null}

      <Modal
        title="提示词"
        open={promptOpen}
        footer={null}
        onCancel={() => setPromptOpen(false)}
      >
        <Paragraph type="secondary" className="context-help">
          所有用户共享提示词。每次只能选择一条，仅应用到下一轮全部模型调用，发送后自动取消。
        </Paragraph>
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Space.Compact style={{ width: "100%" }}>
            <Select allowClear style={{ flex: 1 }} placeholder="选择下一轮使用的提示词"
              value={selectedPromptId} options={prompts.map((item) => ({ value: item.id, label: item.name }))}
              onChange={(value) => { setSelectedPromptId(value ?? null); editPrompt(value ?? null); }} />
            <Button icon={<PlusOutlined />} onClick={newPrompt}>新建</Button>
          </Space.Compact>
          <Input value={promptName} onChange={(event) => setPromptName(event.target.value)} placeholder="提示词名称" />
        <Input.TextArea
          value={promptContent}
          onChange={(event) => setPromptContent(event.target.value)}
          placeholder="填写提示词内容"
          rows={7}
        />
          <Space>
            <Button type="primary" onClick={savePrompt}>{editingPromptId ? "保存修改" : "创建提示词"}</Button>
            {editingPromptId ? <Button danger icon={<DeleteOutlined />} onClick={deletePrompt}>删除</Button> : null}
            <Button onClick={() => setPromptOpen(false)}>完成</Button>
          </Space>
        </Space>
      </Modal>
    </>
  );
}
