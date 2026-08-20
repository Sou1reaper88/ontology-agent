import { Layout, Menu } from "antd";
import { Outlet, useNavigate } from "react-router-dom";

const { Header, Content } = Layout;

export default function MainLayout() {
  const navigate = useNavigate();
  const username = localStorage.getItem("username") || "admin";

  const onLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    navigate("/login");
  };

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header style={{ display: "flex", alignItems: "center" }}>
        <div style={{ color: "#fff", fontSize: 16, marginRight: 32, whiteSpace: "nowrap" }}>
          本体取数智能体
        </div>
        <Menu
          theme="dark"
          mode="horizontal"
          defaultSelectedKeys={["chat"]}
          onClick={(e) => navigate(`/${e.key}`)}
          items={[
            { key: "chat", label: "对话" },
            { key: "ontology", label: "本体定义" },
            { key: "query", label: "数据查询" },
            { key: "admin", label: "管理后台" },
          ]}
          style={{ flex: 1 }}
        />
        <span style={{ color: "#fff", marginRight: 16, cursor: "pointer" }} onClick={onLogout}>
          {username} · 退出
        </span>
      </Header>
      <Content style={{ padding: 24 }}>
        <Outlet />
      </Content>
    </Layout>
  );
}
