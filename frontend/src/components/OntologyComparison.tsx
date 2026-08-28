import { CopyOutlined, EditOutlined } from "@ant-design/icons";
import { Button } from "antd";
import type {
  OntologyShadowResult,
  TemporalEvidence,
} from "../features/chat/types";
import { ontologyStatusPresentation } from "../features/chat/ontologyPresentation";
import "../features/chat/chat-components.css";

export type { OntologyShadowResult, TemporalEvidence } from "../features/chat/types";

interface Props {
  legacySql: string | null;
  result: OntologyShadowResult;
  onEditLegacy: () => void;
  onCopyOntology: (sql: string) => void;
  onViewEvidence?: () => void;
}

function SqlBlock({ sql }: { sql: string }) {
  return (
    <pre className="chat-sql-block">
      <code>{sql}</code>
    </pre>
  );
}

export function OntologyComparison({
  legacySql,
  result,
  onEditLegacy,
  onCopyOntology,
  onViewEvidence,
}: Props) {
  const presentation = ontologyStatusPresentation(result.status);

  if (result.status !== "generated" || !result.ontology_sql) {
    return (
      <section className="ontology-status-strip" data-tone={presentation.tone}>
        <div>
          <strong>{presentation.title}</strong>
          <p>{result.summary || presentation.description}</p>
        </div>
        {onViewEvidence ? (
          <Button type="text" onClick={onViewEvidence}>
            查看本体依据
          </Button>
        ) : null}
      </section>
    );
  }

  const tableChange = result.diff.changed
    ? `${result.diff.legacy_tables.join("、") || "未识别"} → ${
        result.diff.ontology_tables.join("、") || "未识别"
      }`
    : "两条 SQL 规范化后内容相同";

  return (
    <section className="ontology-comparison" aria-label="SQL 对比">
      <header className="ontology-comparison-header">
        <div>
          <span className="ontology-kicker">本体对比</span>
          <strong>{result.summary}</strong>
          <p>{tableChange}</p>
        </div>
        {onViewEvidence ? (
          <Button type="text" onClick={onViewEvidence}>
            查看本体依据
          </Button>
        ) : null}
      </header>

      <div className="sql-comparison-grid">
        <article className="sql-pane">
          <header className="sql-pane-header">
            <div>
              <span>现有 Agent SQL</span>
              <small>可编辑 · 可执行</small>
            </div>
          </header>
          <SqlBlock sql={legacySql || "未生成 SQL"} />
          {legacySql ? (
            <div className="sql-pane-actions">
              <Button size="small" icon={<EditOutlined />} onClick={onEditLegacy}>
                编辑现有 SQL
              </Button>
            </div>
          ) : null}
        </article>

        <article className="sql-pane sql-pane--ontology">
          <header className="sql-pane-header">
            <div>
              <span>本体驱动 SQL</span>
              <small>只读影子预览 · 不会自动执行</small>
            </div>
          </header>
          <SqlBlock sql={result.ontology_sql} />
          <div className="sql-pane-actions">
            <Button
              size="small"
              icon={<CopyOutlined />}
              onClick={() => onCopyOntology(result.ontology_sql!)}
            >
              复制本体 SQL
            </Button>
          </div>
        </article>
      </div>
    </section>
  );
}
