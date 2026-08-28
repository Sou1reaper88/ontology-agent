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
    Button: {
      controlHeight: 38,
      fontWeight: 500,
      primaryShadow: "none",
    },
    Card: {
      boxShadowTertiary: "none",
    },
    Input: {
      activeShadow: "0 0 0 3px rgba(23, 107, 95, 0.14)",
    },
    Menu: {
      itemBorderRadius: 7,
      itemSelectedBg: "#dcebe6",
      itemSelectedColor: "#124f47",
    },
    Table: {
      headerBg: "#efeee8",
      headerColor: "#45504b",
    },
  },
};
