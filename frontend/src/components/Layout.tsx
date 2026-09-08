import { Button, Dropdown, Menu } from "antd";
import type { MenuProps } from "antd";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { activeNavigationKey, NAV_ITEMS } from "./navigation";
import "./Layout.css";

const menuItems: MenuProps["items"] = NAV_ITEMS.map((item) => ({
  key: item.key,
  label: item.label,
}));

export default function MainLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const username = localStorage.getItem("username") || "admin";

  const onNavigate: MenuProps["onClick"] = ({ key }) => {
    const target = NAV_ITEMS.find((item) => item.key === key);
    if (target) navigate(target.path);
  };

  const onLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    navigate("/login");
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳转到主要内容
      </a>

      <header className="app-header">
        <div className="app-header-inner">
          <Link className="app-brand" to="/chat" aria-label="本体取数智能体首页">
            <span className="app-brand-mark" aria-hidden="true" />
            <span className="app-brand-copy">
              <span className="app-brand-name">本体取数智能体</span>
              <span className="app-brand-subtitle">Ontology analyst</span>
            </span>
          </Link>

          <nav aria-label="主要导航">
            <Menu
              className="desktop-navigation"
              mode="horizontal"
              selectedKeys={[activeNavigationKey(location.pathname)]}
              onClick={onNavigate}
              items={menuItems}
            />
          </nav>

          <Dropdown
            menu={{ items: menuItems, onClick: onNavigate }}
            placement="bottomRight"
            trigger={["click"]}
          >
            <Button className="mobile-navigation" type="text" aria-label="打开主要导航">
              菜单
            </Button>
          </Dropdown>

          <div className="app-user-actions">
            <span className="app-user-name" title={username}>
              {username}
            </span>
            <Button className="app-logout" type="text" onClick={onLogout}>
              退出
            </Button>
          </div>
        </div>
      </header>

      <main id="main-content" className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
