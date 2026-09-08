interface EvidenceCandidate {
  id: number;
  role: "user" | "assistant";
  ontology_shadow: unknown | null;
}

export function selectedEvidenceMessage<T extends EvidenceCandidate>(
  messages: readonly T[],
  selectedId: number | null
): T | null {
  if (selectedId !== null) {
    const selected = messages.find(
      (message) =>
        message.id === selectedId &&
        message.role === "assistant" &&
        message.ontology_shadow !== null
    );
    if (selected) return selected;
  }

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "assistant" && message.ontology_shadow !== null) {
      return message;
    }
  }

  return null;
}
