# Frontend Shell Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将登录页、全局主题、顶部导航和页面外壳改造为已确认的“理性研究台”视觉，同时保持所有业务页面和接口行为不变。

**Architecture:** 通过纯 TypeScript 主题令牌统一 Ant Design 配置，通过独立 CSS 文件承载产品级视觉语言。页面外壳只负责路由导航、退出和响应式布局；登录页保留现有认证调用，将错误状态改为页面内反馈。

**Tech Stack:** React 18、TypeScript 5、React Router 6、Ant Design 5、Vite 5、CSS

## Global Constraints

- 仅修改全局视觉基础、顶部导航、页面外壳和登录页。
- 不修改 Chat、本体工作台、数据查询和管理页面的内部业务结构。
- 不修改后端接口、认证协议、路由地址或数据模型。
- 不新增字体、图标或动效依赖。
- 每个独立任务完成后提交 Git；不自动推送或合并。
- 最终只做与本次变更直接相关的构建和页面可用性检查，然后启动 `127.0.0.1:5199` 供用户验收。

---

## File Map

- Create `frontend/src/theme/appTheme.ts`: 产品设计令牌和 Ant Design 主题映射。
- Create `frontend/src/styles/global.css`: 全局背景、字体、焦点、基础组件和减少动态效果规则。
- Modify `frontend/src/main.tsx`: 加载全局样式并注入主题。
- Create `frontend/src/components/navigation.ts`: 导航定义与当前路由映射的纯函数。
- Create `frontend/src/components/Layout.css`: 顶部导航、内容容器和移动端布局。
- Modify `frontend/src/components/Layout.tsx`: 语义化页面外壳、正确路由高亮和退出操作。
- Create `frontend/src/pages/Login.css`: 非对称登录页布局和状态样式。
- Create `frontend/src/pages/loginError.ts`: 将未知接口异常安全映射为登录错误文案。
- Modify `frontend/src/pages/Login.tsx`: 保留认证流程并改为页面内错误反馈。
- Create `frontend/public/ontology-mark.svg`: 产品标识和 favicon。
- Modify `frontend/index.html`: 页面标题、描述、主题色和 favicon。
- Create `frontend/tests/theme.test.ts`: 主题关键令牌契约。
- Create `frontend/tests/navigation.test.ts`: 路由到导航项的映射契约。
- Create `frontend/tests/login-error.test.ts`: 登录错误映射契约。

---

### Task 1: 全局主题与基础样式

**Files:**
- Create: `frontend/src/theme/appTheme.ts`
- Create: `frontend/src/styles/global.css`
- Modify: `frontend/src/main.tsx`
- Create: `frontend/tests/theme.test.ts`

**Interfaces:**
- Produces: `appTheme: ThemeConfig`，由 `main.tsx` 的 `ConfigProvider` 消费。
- Produces: `global.css` 中的 `--oa-*` 设计令牌，供后续布局和登录样式消费。

- [ ] **Step 1: 写主题令牌契约测试**

```ts
import { appTheme } from "../src/theme/appTheme";

function equal(actual: unknown, expected: unknown, label: string): void {
  if (actual !== expected) throw new Error(`${label}: expected ${expected}, received ${actual}`);
}

equal(appTheme.token?.colorPrimary, "#176b5f", "brand accent");
equal(appTheme.token?.borderRadius, 8, "base radius");
equal(appTheme.token?.fontFamily?.includes("Microsoft YaHei UI"), true, "Chinese system font");
equal(appTheme.components?.Button?.controlHeight, 38, "button height");
```

- [ ] **Step 2: 运行测试并确认失败**

Run from `frontend`:

```powershell
$themeTestOut = Join-Path ([System.IO.Path]::GetTempPath()) 'ontology-agent-theme-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\theme.test.ts' --bundle --platform=node --format=cjs --outfile=$themeTestOut
node $themeTestOut
```

Expected: FAIL because `src/theme/appTheme.ts` does not exist.

- [ ] **Step 3: 实现主题映射**

Create `frontend/src/theme/appTheme.ts`:

```ts
import type { ThemeConfig } from "antd";

export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: "#176b5f",
    colorInfo: "#176b5f",
    colorSuccess: "#287a58",
    colorWarning: "#9b681f",
    colorError: "#a8463d",
    colorText: "#19221f",
    colorTextSecondary: "#66716c",
    colorBgBase: "#f4f1e9",
    colorBgContainer: "#fbfaf6",
    colorBorder: "#d8d7cf",
    borderRadius: 8,
    fontFamily:
      '"Segoe UI Variable", "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif',
    fontSize: 14,
    controlHeight: 38,
    boxShadowSecondary: "0 16px 40px rgba(33, 47, 42, 0.10)",
  },
  components: {
    Button: { controlHeight: 38, fontWeight: 500, primaryShadow: "none" },
    Card: { boxShadowTertiary: "none" },
    Input: { activeShadow: "0 0 0 3px rgba(23, 107, 95, 0.14)" },
    Menu: { itemBorderRadius: 7, itemSelectedBg: "#dcebe6", itemSelectedColor: "#124f47" },
    Table: { headerBg: "#efeee8", headerColor: "#45504b" },
  },
};
```

Create `frontend/src/styles/global.css` with these required rules:

```css
:root {
  --oa-bg: #f4f1e9;
  --oa-surface: #fbfaf6;
  --oa-surface-strong: #ffffff;
  --oa-text: #19221f;
  --oa-text-muted: #66716c;
  --oa-border: #d8d7cf;
  --oa-accent: #176b5f;
  --oa-accent-soft: #dcebe6;
  --oa-header: #16231f;
  --oa-header-text: #eef5f1;
  --oa-shadow: 0 16px 40px rgba(33, 47, 42, 0.10);
  font-family: "Segoe UI Variable", "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif;
  color: var(--oa-text);
  background: var(--oa-bg);
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}

* { box-sizing: border-box; }
html { min-width: 320px; background: var(--oa-bg); scroll-behavior: smooth; }
body { margin: 0; min-width: 320px; min-height: 100dvh; background: var(--oa-bg); }
button, input, textarea, select { font: inherit; }
code, pre, .tabular-nums { font-variant-numeric: tabular-nums; }
:focus-visible { outline: 3px solid rgba(23, 107, 95, 0.34); outline-offset: 2px; }

.ant-btn, .ant-input, .ant-input-affix-wrapper, .ant-select-selector {
  transition: border-color 180ms ease, background-color 180ms ease, transform 180ms ease;
}
.ant-btn:active { transform: translateY(1px); }
.ant-card { border-color: var(--oa-border); box-shadow: none; }
.ant-table-wrapper { font-variant-numeric: tabular-nums; }

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; }
}
```

Modify `frontend/src/main.tsx` to import `./styles/global.css`, import `appTheme`, and pass `theme={appTheme}` to `ConfigProvider` while retaining `locale={zhCN}`.

- [ ] **Step 4: 运行主题测试和生产构建**

Run the theme command from Step 2, then:

```powershell
npm run build
```

Expected: theme test exits `0`; TypeScript and Vite build complete successfully.

- [ ] **Step 5: 提交主题基础**

```powershell
git add -- frontend/src/theme/appTheme.ts frontend/src/styles/global.css frontend/src/main.tsx frontend/tests/theme.test.ts
git commit -m "style: 建立理性研究台全局主题"
```

---

### Task 2: 顶部导航与页面外壳

**Files:**
- Create: `frontend/src/components/navigation.ts`
- Create: `frontend/src/components/Layout.css`
- Modify: `frontend/src/components/Layout.tsx`
- Create: `frontend/tests/navigation.test.ts`

**Interfaces:**
- Produces: `NAV_ITEMS`，每项包含 `key`、`label` 和 `path`。
- Produces: `activeNavigationKey(pathname: string): string`，供页面外壳计算受控选中项。
- Consumes: `global.css` 中的 `--oa-*` 令牌。

- [ ] **Step 1: 写路由映射测试**

```ts
import { activeNavigationKey } from "../src/components/navigation";

function equal(actual: string, expected: string, label: string): void {
  if (actual !== expected) throw new Error(`${label}: expected ${expected}, received ${actual}`);
}

equal(activeNavigationKey("/chat"), "chat", "chat route");
equal(activeNavigationKey("/ontology"), "ontology", "ontology route");
equal(activeNavigationKey("/query"), "query", "query route");
equal(activeNavigationKey("/result/query-17"), "query", "result belongs to query");
equal(activeNavigationKey("/admin"), "admin", "admin route");
equal(activeNavigationKey("/unknown"), "", "unknown route");
```

- [ ] **Step 2: 运行测试并确认失败**

```powershell
$navigationTestOut = Join-Path ([System.IO.Path]::GetTempPath()) 'ontology-agent-navigation-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\navigation.test.ts' --bundle --platform=node --format=cjs --outfile=$navigationTestOut
node $navigationTestOut
```

Expected: FAIL because `src/components/navigation.ts` does not exist.

- [ ] **Step 3: 实现导航模型和新页面外壳**

Create `frontend/src/components/navigation.ts`:

```ts
export const NAV_ITEMS = [
  { key: "chat", label: "智能取数", path: "/chat" },
  { key: "ontology", label: "本体工作台", path: "/ontology" },
  { key: "query", label: "数据查询", path: "/query" },
  { key: "admin", label: "管理", path: "/admin" },
] as const;

export function activeNavigationKey(pathname: string): string {
  if (pathname.startsWith("/result/")) return "query";
  return NAV_ITEMS.find((item) => pathname === item.path || pathname.startsWith(`${item.path}/`))?.key ?? "";
}
```

Replace `frontend/src/components/Layout.tsx` with a semantic shell that:

- imports `Button`, `Dropdown`, `Menu` and Ant `Layout`;
- reads `location.pathname` through `useLocation()`;
- passes `selectedKeys={[activeNavigationKey(location.pathname)]}` to the desktop `Menu`;
- renders a skip link to `#main-content`;
- renders a custom square brand mark and “Ontology Analyst / 本体取数智能体” text;
- uses `NAV_ITEMS` for both desktop menu and mobile `Dropdown`;
- renders username and a real `Button type="text"` for logout;
- keeps the existing local-storage clearing and `navigate("/login")` behavior;
- renders `<main id="main-content" className="app-main"><Outlet /></main>`.

Create `frontend/src/components/Layout.css` with:

- `.app-shell` using `min-height: 100dvh` and `var(--oa-bg)`;
- a dark graphite `.app-header` with a centered max-width inner container;
- visible active navigation with the single teal accent;
- a `.skip-link` that becomes visible on focus;
- `.app-main` constrained to `max-width: 1480px` with fluid padding;
- `.mobile-navigation` hidden above `760px` and `.desktop-navigation` hidden below it;
- wrapped user controls and no horizontal overflow at `320px`.

- [ ] **Step 4: 运行导航测试和生产构建**

Run the navigation command from Step 2, then run `npm run build`.

Expected: route assertions pass and the frontend production build succeeds.

- [ ] **Step 5: 提交页面外壳**

```powershell
git add -- frontend/src/components/navigation.ts frontend/src/components/Layout.css frontend/src/components/Layout.tsx frontend/tests/navigation.test.ts
git commit -m "style: 重构全局导航与页面外壳"
```

---

### Task 3: 登录页

**Files:**
- Create: `frontend/src/pages/loginError.ts`
- Create: `frontend/src/pages/Login.css`
- Modify: `frontend/src/pages/Login.tsx`
- Create: `frontend/tests/login-error.test.ts`

**Interfaces:**
- Produces: `loginErrorText(error: unknown): string`。
- Consumes: 现有 `client.post("/auth/login", values)`、localStorage 键和 `/chat` 路由。

- [ ] **Step 1: 写登录错误映射测试**

```ts
import { loginErrorText } from "../src/pages/loginError";

function equal(actual: string, expected: string, label: string): void {
  if (actual !== expected) throw new Error(`${label}: expected ${expected}, received ${actual}`);
}

equal(loginErrorText({ response: { data: { detail: "用户名或密码错误" } } }), "用户名或密码错误", "backend detail");
equal(loginErrorText(new Error("network")), "登录失败，请检查用户名、密码或服务状态", "safe fallback");
equal(loginErrorText(null), "登录失败，请检查用户名、密码或服务状态", "null fallback");
```

- [ ] **Step 2: 运行测试并确认失败**

```powershell
$loginTestOut = Join-Path ([System.IO.Path]::GetTempPath()) 'ontology-agent-login-error-test.cjs'
& '.\node_modules\.bin\esbuild.cmd' '.\tests\login-error.test.ts' --bundle --platform=node --format=cjs --outfile=$loginTestOut
node $loginTestOut
```

Expected: FAIL because `src/pages/loginError.ts` does not exist.

- [ ] **Step 3: 实现错误映射和新登录页**

Create `frontend/src/pages/loginError.ts`:

```ts
type ErrorWithDetail = { response?: { data?: { detail?: unknown } } };

export function loginErrorText(error: unknown): string {
  const detail = (error as ErrorWithDetail | null)?.response?.data?.detail;
  return typeof detail === "string" && detail.trim()
    ? detail
    : "登录失败，请检查用户名、密码或服务状态";
}
```

Update `Login.tsx` to:

- retain `client.post("/auth/login", values)`, token/username storage, success message and `/chat` navigation;
- add `errorText` state and clear it before each submission;
- render an Ant `Alert` inside the form when `errorText` is present;
- call `setErrorText(loginErrorText(error))` instead of a global error toast;
- remove credential-revealing placeholders and use `autoComplete="username"` / `autoComplete="current-password"`;
- render the brand panel and login panel described by the approved design;
- apply `Login.css` class names instead of inline styles.

Create `Login.css` with a warm neutral full-height shell, restrained radial texture, asymmetric two-column desktop grid, dark graphite brand panel, light form panel, compact form width, responsive single-column layout below `760px`, and reduced-motion support. Use only existing `--oa-*` tokens plus local semantic values.

- [ ] **Step 4: 运行登录测试和生产构建**

Run the login command from Step 2, then run `npm run build`.

Expected: error mapping assertions pass and the frontend production build succeeds.

- [ ] **Step 5: 提交登录页**

```powershell
git add -- frontend/src/pages/loginError.ts frontend/src/pages/Login.css frontend/src/pages/Login.tsx frontend/tests/login-error.test.ts
git commit -m "style: 重塑本体智能体登录体验"
```

---

### Task 4: 产品元信息与运行验收

**Files:**
- Create: `frontend/public/ontology-mark.svg`
- Modify: `frontend/index.html`
- Create: `docs/engineering-journal/2026-08-28-frontend-shell-redesign.md`

**Interfaces:**
- Produces: favicon、中文页面标题和描述。
- Produces: 本次重构的难点、取舍和验证记录，供后续项目总结及简历材料使用。

- [ ] **Step 1: 写产品元信息**

Create `frontend/public/ontology-mark.svg` as a simple teal-on-graphite SVG mark representing connected semantic nodes. Update `frontend/index.html` to use:

```html
<meta name="description" content="基于业务本体生成、解释与校验 SQL 的智能取数工作台" />
<meta name="theme-color" content="#16231f" />
<link rel="icon" type="image/svg+xml" href="/ontology-mark.svg" />
<title>本体取数智能体</title>
```

- [ ] **Step 2: 记录工程实践**

Create `docs/engineering-journal/2026-08-28-frontend-shell-redesign.md`，记录：

- 从 110 处内联样式和默认 Ant 风格中划定首期边界；
- 使用集中式主题令牌兼容既有页面；
- 用受控路由状态修复固定导航高亮；
- 在不改变认证接口的前提下改进错误反馈和敏感占位文本；
- 后续仍需分块改造 Chat 和本体工作台内部结构。

- [ ] **Step 3: 运行最小必要验证**

From `frontend`, run the three bundled contract tests and production build. Expected: every test exits `0`, then `npm run build` succeeds with no TypeScript errors.

- [ ] **Step 4: 提交产品元信息与记录**

```powershell
git add -- frontend/public/ontology-mark.svg frontend/index.html docs/engineering-journal/2026-08-28-frontend-shell-redesign.md
git commit -m "docs: 记录前端外壳重构实践"
```

- [ ] **Step 5: 启动前端供用户查看**

Resolve the current listener for port `5199` and stop it only if its command line belongs to this project worktree. Start:

```powershell
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5199
```

Expected: `http://127.0.0.1:5199/login` and `http://127.0.0.1:5199/chat` return HTTP `200`. Keep the service running and ask the user to perform visual acceptance before starting the next redesign block.
