export const NAV_ITEMS = [
  { key: "chat", label: "智能取数", path: "/chat" },
  { key: "ontology", label: "本体工作台", path: "/ontology" },
  { key: "query", label: "数据查询", path: "/query" },
  { key: "admin", label: "管理", path: "/admin" },
] as const;

export function activeNavigationKey(pathname: string): string {
  if (pathname.startsWith("/result/")) return "query";

  return (
    NAV_ITEMS.find(
      (item) => pathname === item.path || pathname.startsWith(`${item.path}/`)
    )?.key ?? ""
  );
}
