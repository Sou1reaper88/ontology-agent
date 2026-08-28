import {
  ClearOutlined,
  DeleteOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { Button, Checkbox, Empty, Popconfirm, Skeleton } from "antd";
import type { ConversationItem } from "./types";
import "./chat-components.css";

interface Props {
  conversations: ConversationItem[];
  activeId: number | null;
  loading: boolean;
  selectMode: boolean;
  selectedIds: number[];
  batchDeleting: boolean;
  clearing: boolean;
  onNew: () => void;
  onOpen: (id: number) => void;
  onEnterSelectMode: () => void;
  onExitSelectMode: () => void;
  onToggleSelect: (id: number) => void;
  onSelectAll: () => void;
  onBatchRemove: () => void;
  onClearAll: () => void;
  onRemove: (id: number) => void;
}

export function ConversationSidebar({
  conversations,
  activeId,
  loading,
  selectMode,
  selectedIds,
  batchDeleting,
  clearing,
  onNew,
  onOpen,
  onEnterSelectMode,
  onExitSelectMode,
  onToggleSelect,
  onSelectAll,
  onBatchRemove,
  onClearAll,
  onRemove,
}: Props) {
  const allSelected =
    conversations.length > 0 && selectedIds.length === conversations.length;

  return (
    <div className="conversation-sidebar-content">
      <header className="conversation-sidebar-header">
        <div>
          <span>工作目录</span>
          <strong>取数会话</strong>
        </div>
        <span className="conversation-count tabular-nums">
          {conversations.length}
        </span>
      </header>

      <Button type="primary" icon={<PlusOutlined />} block onClick={onNew}>
        新建取数需求
      </Button>

      <div className="conversation-toolbar">
        {selectMode ? (
          <>
            <Button size="small" onClick={onSelectAll} disabled={!conversations.length}>
              {allSelected ? "取消全选" : "全选"}
            </Button>
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={!selectedIds.length}
              loading={batchDeleting}
              onClick={onBatchRemove}
            >
              删除 {selectedIds.length}
            </Button>
            <Button size="small" type="text" onClick={onExitSelectMode}>
              完成
            </Button>
          </>
        ) : (
          <>
            <Button
              size="small"
              type="text"
              icon={<DeleteOutlined />}
              disabled={!conversations.length}
              onClick={onEnterSelectMode}
            >
              批量管理
            </Button>
            <Button
              size="small"
              type="text"
              danger
              icon={<ClearOutlined />}
              disabled={!conversations.length}
              loading={clearing}
              onClick={onClearAll}
            >
              清空
            </Button>
          </>
        )}
      </div>

      <div className="conversation-list-scroll">
        {loading ? (
          <div className="conversation-skeleton" aria-label="正在加载会话">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} active title paragraph={{ rows: 1 }} />
            ))}
          </div>
        ) : conversations.length ? (
          <ol className="conversation-list">
            {conversations.map((conversation) => {
              const selected = selectedIds.includes(conversation.id);
              const active = !selectMode && conversation.id === activeId;
              const updated = conversation.updated_at
                ? conversation.updated_at.slice(0, 16).replace("T", " ")
                : "";

              return (
                <li
                  key={conversation.id}
                  className="conversation-item"
                  data-active={active || undefined}
                  data-selected={selected || undefined}
                >
                  {selectMode ? (
                    <label className="conversation-select-row">
                      <Checkbox
                        checked={selected}
                        onChange={() => onToggleSelect(conversation.id)}
                      />
                      <span className="conversation-copy">
                        <strong>{conversation.title}</strong>
                        <small>{conversation.last_message || "空会话"}</small>
                      </span>
                    </label>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="conversation-open"
                        onClick={() => onOpen(conversation.id)}
                        aria-current={active ? "page" : undefined}
                      >
                        <span className="conversation-copy">
                          <strong>{conversation.title}</strong>
                          <small>{conversation.last_message || "空会话"}</small>
                          {updated ? <time>{updated}</time> : null}
                        </span>
                      </button>
                      <Popconfirm
                        title="删除该对话？"
                        onConfirm={() => onRemove(conversation.id)}
                      >
                        <Button
                          className="conversation-delete"
                          type="text"
                          size="small"
                          danger
                          icon={<DeleteOutlined />}
                          aria-label={`删除会话：${conversation.title}`}
                        />
                      </Popconfirm>
                    </>
                  )}
                </li>
              );
            })}
          </ol>
        ) : (
          <Empty
            className="conversation-empty"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="还没有取数会话"
          >
            <Button size="small" onClick={onNew}>
              新建需求
            </Button>
          </Empty>
        )}
      </div>
    </div>
  );
}
