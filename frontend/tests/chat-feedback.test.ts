import {
  feedbackPath,
  feedbackRequestErrorMessage,
  feedbackValidationMessage,
} from "../src/features/chat/feedback";
import {
  conversationDeepLinkToConsume,
  isLatestConversationRequest,
} from "../src/features/chat/conversationDeepLink";

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

if (conversationDeepLinkToConsume(27, null) !== 27) {
  throw new Error("a valid conversation deep link must be consumed");
}
if (conversationDeepLinkToConsume(27, 27) !== null) {
  throw new Error("a consumed conversation deep link must not be consumed again");
}
if (conversationDeepLinkToConsume(0, null) !== null) {
  throw new Error("an invalid conversation deep link must be ignored");
}
if (isLatestConversationRequest(1, 2)) {
  throw new Error("an older conversation response must not commit state");
}
if (!isLatestConversationRequest(2, 2)) {
  throw new Error("the latest conversation response must commit state");
}
if (feedbackRequestErrorMessage([{ msg: "字段无效" }]) !== "反馈保存失败，请稍后重试") {
  throw new Error("structured API details must fall back to a renderable message");
}
