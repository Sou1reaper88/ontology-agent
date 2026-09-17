export function conversationDeepLinkToConsume(
  linkedConversationId: number,
  consumedConversationId: number | null
): number | null {
  if (
    !Number.isInteger(linkedConversationId) ||
    linkedConversationId <= 0 ||
    linkedConversationId === consumedConversationId
  ) {
    return null;
  }
  return linkedConversationId;
}
