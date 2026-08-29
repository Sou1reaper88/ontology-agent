import type { ReactNode } from "react";
import { ReloadOutlined } from "@ant-design/icons";
import { Button, Tag } from "antd";
import type { WorkspaceOverview } from "./types";
import {
  WORKBENCH_STAGES,
  type WorkbenchStage,
  workbenchStageSummary,
} from "./workbenchModel";

interface WorkbenchShellProps {
  overview: WorkspaceOverview;
  versionCount: number;
  activeStage: WorkbenchStage;
  refreshing: boolean;
  onStageChange: (stage: WorkbenchStage) => void;
  onRefresh: () => void;
  children: ReactNode;
}

const assetMetrics = [
  { key: "objects", label: "业务对象" },
  { key: "fields", label: "字段属性" },
  { key: "relations", label: "对象关系" },
  { key: "temporalPolicies", label: "时间策略" },
] as const;

export default function WorkbenchShell({
  overview,
  versionCount,
  activeStage,
  refreshing,
  onStageChange,
  onRefresh,
  children,
}: WorkbenchShellProps) {
  const activeDefinition = WORKBENCH_STAGES.find((stage) => stage.key === activeStage)!;

  return (
    <main className="ontology-workbench">
      <header className="ontology-workbench__header">
        <div className="ontology-workbench__identity">
          <span className="ontology-workbench__eyebrow">ONTOLOGY PACKAGE</span>
          <h1>本体构建工作台</h1>
          <p>{overview.displayName}</p>
        </div>
        <div className="ontology-workbench__status">
          <div className="ontology-workbench__status-item">
            <span>活动版本</span>
            <strong>{overview.activeVersion?.version ?? "尚未发布"}</strong>
          </div>
          <div className="ontology-workbench__status-item">
            <span>草稿修订</span>
            <strong className="tabular-nums">R{overview.revision}</strong>
          </div>
          <Button icon={<ReloadOutlined spin={refreshing} />} loading={refreshing} onClick={onRefresh}>
            刷新
          </Button>
        </div>
      </header>

      <section className="ontology-workbench__metrics" aria-label="本体资产概览">
        <div className="ontology-workbench__metrics-intro">
          <span>当前草稿</span>
          <strong>资产覆盖</strong>
        </div>
        {assetMetrics.map((metric) => (
          <div className="ontology-workbench__metric" key={metric.key}>
            <strong className="tabular-nums">{overview.counts[metric.key]}</strong>
            <span>{metric.label}</span>
          </div>
        ))}
      </section>

      <section className="ontology-workbench__workspace">
        <nav className="ontology-workbench__stages" aria-label="本体构建阶段">
          <div className="ontology-workbench__stages-heading">
            <span>构建路径</span>
            <Tag bordered={false}>{WORKBENCH_STAGES.length} 个阶段</Tag>
          </div>
          <div className="ontology-workbench__stage-list">
            {WORKBENCH_STAGES.map((stage) => {
              const selected = stage.key === activeStage;
              return (
                <button
                  type="button"
                  key={stage.key}
                  className={`ontology-workbench__stage${selected ? " is-active" : ""}`}
                  aria-current={selected ? "step" : undefined}
                  onClick={() => onStageChange(stage.key)}
                >
                  <span className="ontology-workbench__stage-number">{stage.number}</span>
                  <span className="ontology-workbench__stage-copy">
                    <strong>{stage.title}</strong>
                    <small>{workbenchStageSummary(stage.key, overview, versionCount)}</small>
                  </span>
                </button>
              );
            })}
          </div>
          <p className="ontology-workbench__compatibility">
            旧版 MySQL 元数据接口保持兼容，但不再驱动 RDF 发布。
          </p>
        </nav>

        <section className="ontology-workbench__content" aria-labelledby="active-stage-title">
          <div className="ontology-workbench__content-heading">
            <div>
              <span>阶段 {activeDefinition.number}</span>
              <h2 id="active-stage-title">{activeDefinition.title}</h2>
            </div>
            <p>{activeDefinition.description}</p>
          </div>
          <div className="ontology-workbench__panel">{children}</div>
        </section>
      </section>
    </main>
  );
}
