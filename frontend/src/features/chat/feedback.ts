import client from "../../api/client";

export type FeedbackStatus = "correct" | "needs_revision";

export interface MessageFeedback {
  id: number;
  status: FeedbackStatus;
  note: string | null;
  final_sql: string | null;
  created_at: string;
  updated_at: string;
}

export const feedbackPath = (messageId: number) => `/feedback/messages/${messageId}`;

export const feedbackValidationMessage = (status: FeedbackStatus, note: string) =>
  status === "needs_revision" && !note.trim() ? "请填写问题说明或补充口径" : null;

export async function saveMessageFeedback(
  messageId: number,
  payload: { status: FeedbackStatus; note?: string; final_sql?: string }
): Promise<MessageFeedback> {
  return (await client.put<MessageFeedback>(feedbackPath(messageId), payload)).data;
}

export async function deleteMessageFeedback(messageId: number): Promise<void> {
  await client.delete(feedbackPath(messageId));
}
