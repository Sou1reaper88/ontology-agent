import { useState } from "react";
import { Alert, Button, Form, Input, message } from "antd";
import { useNavigate } from "react-router-dom";
import client from "../api/client";
import { loginErrorText } from "./loginError";
import "./Login.css";

export default function Login() {
  const [loading, setLoading] = useState(false);
  const [errorText, setErrorText] = useState("");
  const navigate = useNavigate();

  const onFinish = async (values: { username: string; password: string }) => {
    setErrorText("");
    setLoading(true);
    try {
      const { data } = await client.post("/auth/login", values);
      localStorage.setItem("token", data.access_token);
      localStorage.setItem("username", values.username);
      message.success("登录成功");
      navigate("/chat");
    } catch (error: unknown) {
      setErrorText(loginErrorText(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-shell">
      <div className="login-frame">
        <section className="login-panel" aria-labelledby="login-heading">
          <div className="login-form-wrap">
            <header className="login-form-heading">
              <p>欢迎回来</p>
              <h2 id="login-heading">登录工作台</h2>
              <span>使用你的项目账户继续访问智能取数与本体管理能力。</span>
            </header>

            <Form
              className="login-form"
              onFinish={onFinish}
              layout="vertical"
              requiredMark={false}
            >
              {errorText ? (
                <Alert type="error" showIcon message={errorText} role="alert" />
              ) : null}

              <Form.Item
                name="username"
                label="用户名"
                rules={[{ required: true, message: "请输入用户名" }]}
              >
                <Input autoComplete="username" placeholder="请输入用户名" />
              </Form.Item>

              <Form.Item
                name="password"
                label="密码"
                rules={[{ required: true, message: "请输入密码" }]}
              >
                <Input.Password
                  autoComplete="current-password"
                  placeholder="请输入密码"
                />
              </Form.Item>

              <Button
                className="login-submit"
                type="primary"
                htmlType="submit"
                loading={loading}
                block
              >
                进入工作台
              </Button>
            </Form>

            <p className="login-security-note">登录凭据仅用于当前项目环境的身份验证。</p>
          </div>
        </section>

        <section className="login-brand-panel" aria-label="产品介绍">
          <div className="login-brand-lockup">
            <span className="login-brand-mark" aria-hidden="true" />
            <span className="login-brand-name">
              <strong>本体取数智能体</strong>
              <span>Ontology analyst</span>
            </span>
          </div>

          <div className="login-brand-copy">
            <p className="login-eyebrow">Semantic data workspace</p>
            <h1>让业务语义成为 SQL 的依据</h1>
            <p>
              将对象、字段、业务口径、关联路径与账期策略组织成可追溯的推理依据。
            </p>
          </div>

          <ul className="login-capabilities" aria-label="产品核心能力">
            <li>
              <span>01</span>
              本体依据可追溯
            </li>
            <li>
              <span>02</span>
              业务账期可解释
            </li>
            <li>
              <span>03</span>
              SQL 差异可核对
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}
