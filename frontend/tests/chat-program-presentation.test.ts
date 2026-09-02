import assert from "node:assert/strict";
import {
  getAssistantContent,
  getSqlPresentation,
} from "../src/features/chat/messagePresentation";

const programMessage = {
  sql: "DROP TABLE IF EXISTS temp_result;\nCREATE TABLE temp_result AS SELECT 1;",
  query_id: null,
  ontology_shadow: { status: "unavailable" },
  program: { program_id: "a1b2c3d4e5f6" },
};

assert.deepEqual(getSqlPresentation(programMessage, false), {
  kind: "program",
  label: "取数程序",
  showComparison: false,
  showSqlPanel: true,
  allowEdit: false,
  allowExecute: false,
});

assert.equal(
  getAssistantContent(
    "## 取数程序\n- 物化步骤：1\n\n## SQL 脚本\n\nDROP TABLE temp_result;",
    true
  ),
  "## 取数程序\n- 物化步骤：1"
);
assert.equal(getAssistantContent("普通回答", false), "普通回答");

const legacyMessage = {
  sql: "SELECT 1;",
  query_id: 7,
  ontology_shadow: { status: "unavailable" },
  program: null,
};

assert.deepEqual(getSqlPresentation(legacyMessage, false), {
  kind: "query",
  label: "现有 SQL",
  showComparison: true,
  showSqlPanel: true,
  allowEdit: true,
  allowExecute: true,
});

console.log("chat program presentation tests passed");
