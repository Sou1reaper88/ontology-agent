import type { RefObject } from "react";
import {
  CopyOutlined,
  EditOutlined,
  PlayCircleOutlined,
} from "@ant-design/icons";
import { Button, Input, Skeleton, Space } from "antd";
import { OntologyComparison } from "../../components/OntologyComparison";
import {
  getAssistantContent,
  getSqlPresentation,
} from "./messagePresentation";
import { TraceSteps } from "./TraceSteps";
import type { ChatMessage, EditingSql } from "./types";
import "./chat-components.css";

interface Props {
  messages: ChatMessage[];
  loading: boolean;
  listRef: RefObject<HTMLDivElement>;
  editing: EditingSql | null;
  executingId: number | null;
  selectedEvidenceId: number | null;
  onEditChange: (editing: EditingSql) => void;
  onCancelEdit: () => void;
  onRunEdited: (messageId: number, sql: string) => void;
  onRunOriginal: (messageId: number, queryId: number) => void;
  onCopySql: (sql: string) => void;
  onSelectEvidence: (message: ChatMessage) => void;
}

export function MessageTimeline({
  messages,
  loading,
  listRef,
  editing,
  executingId,
  selectedEvidenceId,
  onEditChange,
  onCancelEdit,
  onRunEdited,
  onRunOriginal,
  onCopySql,
  onSelectEvidence,
}: Props) {
  return (
    <div className="message-timeline" ref={listRef} aria-live="polite">
      {loading ? (
        <div className="message-skeleton" aria-label="正在加载消息">
          <Skeleton active paragraph={{ rows: 2 }} />
          <Skeleton active paragraph={{ rows: 5 }} />
        </div>
      ) : (
        messages.map((message) => {
          if (message.role === "user") {
            return (
              <article key={message.id} className="user-message">
                <span className="message-role-label">你的需求</span>
                <p>{message.content}</p>
              </article>
            );
          }

          const traceSteps =
            (message.trace && message.trace.length > 0
              ? message.trace
              : message.steps) || [];
          const isEditing = editing?.msgId === message.id;
          const evidenceSelected = selectedEvidenceId === message.id;
          const sqlPresentation = getSqlPresentation(message, isEditing);
          const isInferredProgram =
            message.program?.mode === "inferred_program";
          const inferenceEvidence = message.program?.inference_evidence;

          return (
            <article
              key={message.id}
              className="assistant-report"
              data-generating={message.generating || undefined}
            >
              <header className="assistant-report-header">
                <div>
                  <span className="message-role-label">智能体回答</span>
                  {message.generating ? <small>正在生成</small> : null}
                </div>
                {message.ontology_shadow ? (
                  <Button
                    size="small"
                    type={evidenceSelected ? "primary" : "text"}
                    onClick={() => onSelectEvidence(message)}
                    aria-current={evidenceSelected ? "true" : undefined}
                  >
                    {evidenceSelected ? "正在查看依据" : "查看本体依据"}
                  </Button>
                ) : null}
              </header>

              <div className="assistant-answer">
                {getAssistantContent(message.content, Boolean(message.program)) ||
                  (message.generating ? "正在理解需求并生成 SQL…" : "")}
              </div>

              {message.error ? <div className="assistant-error">{message.error}</div> : null}

              {traceSteps.length ? (
                <TraceSteps steps={traceSteps} generating={message.generating} />
              ) : null}

              {sqlPresentation.showComparison && message.ontology_shadow ? (
                <OntologyComparison
                  legacySql={message.sql}
                  result={message.ontology_shadow}
                  onEditLegacy={() =>
                    message.sql && onEditChange({ msgId: message.id, sql: message.sql })
                  }
                  onCopyOntology={onCopySql}
                  onViewEvidence={() => onSelectEvidence(message)}
                />
              ) : null}

              {message.sql && sqlPresentation.showSqlPanel ? (
                <section
                  className="legacy-sql-editor"
                  aria-label={sqlPresentation.label}
                  data-kind={sqlPresentation.kind}
                >
                  {sqlPresentation.kind === "program" ? (
                    <header
                      className="program-sql-header"
                      data-inferred={isInferredProgram || undefined}
                    >
                      <div>
                        <span className="ontology-kicker">
                          {isInferredProgram
                            ? "CANDIDATE INFERENCE"
                            : "GENERATED PROGRAM"}
                        </span>
                        <strong>
                          {isInferredProgram ? "候选取数程序" : "取数程序"}
                        </strong>
                        <p>
                          {isInferredProgram
                            ? "LLM 推断、未经本体确认、不可自动执行。"
                            : "仅生成脚本，不会由智能体自动执行。"}
                        </p>
                      </div>
                      <div className="program-sql-meta">
                        <span>{message.program?.platform.toUpperCase()}</span>
                        <span>{message.program?.steps.length ?? 0} 个物化步骤</span>
                        {inferenceEvidence ? (
                          <span>置信度 {inferenceEvidence.overall_confidence}</span>
                        ) : null}
                      </div>
                    </header>
                  ) : null}
                  {isInferredProgram && inferenceEvidence ? (
                    <section className="inference-evidence" aria-label="候选推断依据">
                      <div>
                        <strong>为什么这样生成</strong>
                        <ul>
                          {inferenceEvidence.reasons.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                      {inferenceEvidence.unresolved_items.length ? (
                        <div>
                          <strong>尚未确认</strong>
                          <ul>
                            {inferenceEvidence.unresolved_items.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      {inferenceEvidence.ontology_suggestions.length ? (
                        <div>
                          <strong>如何补充本体</strong>
                          <ul>
                            {inferenceEvidence.ontology_suggestions.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </section>
                  ) : null}
                  {isEditing ? (
                    <>
                      <Input.TextArea
                        value={editing.sql}
                        onChange={(event) =>
                          onEditChange({ msgId: message.id, sql: event.target.value })
                        }
                        rows={8}
                        className="sql-edit-textarea"
                      />
                      <Space className="legacy-sql-actions" wrap>
                        <Button
                          size="small"
                          type="primary"
                          loading={executingId === message.id}
                          onClick={() => onRunEdited(message.id, editing.sql)}
                        >
                          执行修改后 SQL
                        </Button>
                        <Button size="small" onClick={onCancelEdit}>
                          取消
                        </Button>
                      </Space>
                    </>
                  ) : (
                    <>
                      <pre className="chat-sql-block">
                        <code>{message.sql}</code>
                      </pre>
                      {sqlPresentation.allowEdit ? (
                        <div className="legacy-sql-actions">
                          <Button
                            size="small"
                            icon={<EditOutlined />}
                            onClick={() =>
                              onEditChange({ msgId: message.id, sql: message.sql! })
                            }
                          >
                            编辑 SQL
                          </Button>
                        </div>
                      ) : null}
                    </>
                  )}
                </section>
              ) : null}

              <div className="assistant-actions">
                {message.query_id && sqlPresentation.allowExecute ? (
                  <Button
                    size="small"
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    loading={executingId === message.id}
                    onClick={() =>
                      onRunOriginal(message.id, message.query_id!)
                    }
                  >
                    执行取数
                  </Button>
                ) : null}
                {message.sql ? (
                  <Button
                    size="small"
                    icon={<CopyOutlined />}
                    onClick={() => onCopySql(message.sql!)}
                  >
                    复制 SQL
                  </Button>
                ) : null}
              </div>
            </article>
          );
        })
      )}
    </div>
  );
}
