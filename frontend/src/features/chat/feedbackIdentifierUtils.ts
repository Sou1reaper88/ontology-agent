export function formatFeedbackIdentifier(
  conversationId: number | null,
  messageId?: number,
): string | null {
  if (!Number.isSafeInteger(conversationId) || conversationId === null || conversationId <= 0) {
    return null;
  }
  if (messageId !== undefined && (!Number.isSafeInteger(messageId) || messageId <= 0)) {
    return null;
  }
  return messageId === undefined
    ? `C-${conversationId}`
    : `C-${conversationId} / M-${messageId}`;
}

export async function copyFeedbackIdentifier(value: string): Promise<void> {
  if (!navigator.clipboard?.writeText) {
    throw new Error("clipboard_unavailable");
  }
  await navigator.clipboard.writeText(value);
}
