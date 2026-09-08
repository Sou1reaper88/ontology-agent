import { selectedEvidenceMessage } from "../src/features/chat/evidenceSelection";
import { ontologyStatusPresentation } from "../src/features/chat/ontologyPresentation";

const shadow = (status: "generated" | "no_match") => ({ status });
const messages = [
  { id: 1, role: "assistant" as const, ontology_shadow: shadow("generated") },
  { id: 2, role: "user" as const, ontology_shadow: null },
  { id: 3, role: "assistant" as const, ontology_shadow: shadow("no_match") },
];

if (selectedEvidenceMessage(messages, null)?.id !== 3) {
  throw new Error("latest evidence must win");
}
if (selectedEvidenceMessage(messages, 1)?.id !== 1) {
  throw new Error("explicit selection must remain");
}
if (selectedEvidenceMessage(messages, 99)?.id !== 3) {
  throw new Error("stale selection must fall back");
}
if (
  selectedEvidenceMessage(
    [{ id: 4, role: "user" as const, ontology_shadow: null }],
    null
  ) !== null
) {
  throw new Error("empty evidence must be null");
}
if (ontologyStatusPresentation("generated").tone !== "success") {
  throw new Error("generated tone");
}
if (ontologyStatusPresentation("no_match").tone !== "neutral") {
  throw new Error("no-match is not a system error");
}
