import { useState } from "react";
import { Button, Input, Modal, message as toast } from "antd";
import {
  deleteMessageFeedback,
  feedbackRequestErrorMessage,
  feedbackValidationMessage,
  saveMessageFeedback,
} from "./feedback";
import type { MessageFeedback } from "./feedback";
import type { ChatMessage } from "./types";

interface Props {
  message: ChatMessage;
}

export function MessageFeedbackControls({ message }: Props) {
  const [feedback, setFeedback] = useState<MessageFeedback | null>(message.feedback);
  const [revisionOpen, setRevisionOpen] = useState(false);
  const [note, setNote] = useState("");
  const [finalSql, setFinalSql] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  if (message.generating || !message.sql) return null;

  const requestError = (error: any) =>
    feedbackRequestErrorMessage(error.response?.data?.detail);

  const saveCorrect = async () => {
    setSaving(true);
    try {
      setFeedback(await saveMessageFeedback(message.id, { status: "correct" }));
    } catch (error: any) {
      toast.error(requestError(error));
    } finally {
      setSaving(false);
    }
  };

  const openRevision = () => {
    setNote(feedback?.note ?? "");
    setFinalSql(feedback?.final_sql ?? message.sql ?? "");
    setValidationError(null);
    setRevisionOpen(true);
  };

  const saveRevision = async () => {
    const error = feedbackValidationMessage("needs_revision", note);
    setValidationError(error);
    if (error) return;

    setSaving(true);
    try {
      setFeedback(
        await saveMessageFeedback(message.id, {
          status: "needs_revision",
          note,
          final_sql: finalSql,
        })
      );
      setRevisionOpen(false);
    } catch (requestFailure: any) {
      toast.error(requestError(requestFailure));
    } finally {
      setSaving(false);
    }
  };

  const withdraw = async () => {
    setSaving(true);
    try {
      await deleteMessageFeedback(message.id);
      setFeedback(null);
    } catch (error: any) {
      toast.error(requestError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="message-feedback-controls">
      <Button
        size="small"
        loading={saving}
        onClick={() => void saveCorrect()}
        type={feedback?.status === "correct" ? "primary" : "default"}
      >
        结果正确
      </Button>
      <Button
        size="small"
        disabled={saving}
        onClick={openRevision}
        type={feedback?.status === "needs_revision" ? "primary" : "default"}
      >
        需要修改
      </Button>
      {feedback ? (
        <Button size="small" type="text" loading={saving} onClick={() => void withdraw()}>
          撤销反馈
        </Button>
      ) : null}
      <Modal
        title="修改 SQL 反馈"
        open={revisionOpen}
        okText="提交反馈"
        cancelText="取消"
        confirmLoading={saving}
        cancelButtonProps={{ disabled: saving }}
        closable={!saving}
        keyboard={!saving}
        maskClosable={!saving}
        onOk={() => void saveRevision()}
        onCancel={() => {
          if (!saving) setRevisionOpen(false);
        }}
      >
        <label className="message-feedback-field">
          <span>问题说明或补充口径</span>
          <Input.TextArea
            value={note}
            status={validationError ? "error" : undefined}
            rows={3}
            onChange={(event) => {
              setNote(event.target.value);
              setValidationError(null);
            }}
          />
          {validationError ? <small className="message-feedback-error">{validationError}</small> : null}
        </label>
        <label className="message-feedback-field">
          <span>修改后的 SQL</span>
          <Input.TextArea
            value={finalSql}
            rows={8}
            onChange={(event) => setFinalSql(event.target.value)}
          />
        </label>
      </Modal>
    </div>
  );
}
