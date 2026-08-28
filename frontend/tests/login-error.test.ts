import { loginErrorText } from "../src/pages/loginError";

function equal(actual: string, expected: string, label: string): void {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${expected}, received ${actual}`);
  }
}

equal(
  loginErrorText({ response: { data: { detail: "用户名或密码错误" } } }),
  "用户名或密码错误",
  "backend detail"
);
equal(
  loginErrorText(new Error("network")),
  "登录失败，请检查用户名、密码或服务状态",
  "safe fallback"
);
equal(
  loginErrorText(null),
  "登录失败，请检查用户名、密码或服务状态",
  "null fallback"
);
