export function isLatestRequest(requestId: number, latestRequestId: number): boolean {
  return requestId === latestRequestId;
}
