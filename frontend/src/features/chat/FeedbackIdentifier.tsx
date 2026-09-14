import { message } from "antd";
import { copyFeedbackIdentifier, formatFeedbackIdentifier } from "./feedbackIdentifierUtils";
import "./chat-components.css";

export function FeedbackIdentifier({
  conversationId,
  messageId,
}: {
  conversationId: number | null;
  messageId?: number;
}) {
  const value = formatFeedbackIdentifier(conversationId, messageId);
  if (!value) return null;

  return (
    <button
      type="button"
      className="feedback-identifier"
      aria-label={`复制反馈编号 ${value}`}
      title={`复制反馈编号 ${value}`}
      onClick={async (event) => {
        event.stopPropagation();
        try {
          await copyFeedbackIdentifier(value);
          message.success("反馈编号已复制");
        } catch {
          message.error("反馈编号复制失败，请重试或手动记录编号");
        }
      }}
    >
      {value}
    </button>
  );
}
