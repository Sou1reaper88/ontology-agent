import { appTheme } from "../src/theme/appTheme";

function equal(actual: unknown, expected: unknown, label: string): void {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${expected}, received ${actual}`);
  }
}

equal(appTheme.token?.colorPrimary, "#176b5f", "brand accent");
equal(appTheme.token?.borderRadius, 8, "base radius");
equal(
  appTheme.token?.fontFamily?.includes("Microsoft YaHei UI"),
  true,
  "Chinese system font"
);
equal(appTheme.components?.Button?.controlHeight, 38, "button height");
