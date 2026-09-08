type ErrorWithDetail = {
  response?: {
    data?: {
      detail?: unknown;
    };
  };
};

export function loginErrorText(error: unknown): string {
  const detail = (error as ErrorWithDetail | null)?.response?.data?.detail;

  return typeof detail === "string" && detail.trim()
    ? detail
    : "登录失败，请检查用户名、密码或服务状态";
}
