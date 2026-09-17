import {
  feedbackPath,
  feedbackValidationMessage,
} from "../src/features/chat/feedback";

if (feedbackPath(27) !== "/feedback/messages/27") {
  throw new Error("feedback path must be message scoped");
}
if (feedbackValidationMessage("correct", "") !== null) {
  throw new Error("correct feedback needs no note");
}
if (feedbackValidationMessage("needs_revision", "   ") !== "请填写问题说明或补充口径") {
  throw new Error("revision feedback must require a note");
}
if (feedbackValidationMessage("needs_revision", "字段口径有误") !== null) {
  throw new Error("revision feedback accepts a non-empty note");
}
