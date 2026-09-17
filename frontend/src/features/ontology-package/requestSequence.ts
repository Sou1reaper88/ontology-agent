export function isLatestRequest(requestId: number, latestRequestId: number): boolean {
  return requestId === latestRequestId;
}

export function canOpenFeedbackConversation(
  feedbackUsername: string,
  currentUsername: string | null
): boolean {
  return Boolean(currentUsername) && feedbackUsername === currentUsername;
}
