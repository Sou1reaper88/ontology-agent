import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Card, Empty, Spin, message } from "antd";
import { apiErrorMessage, fetchVersions, fetchWorkspaceOverview } from "./api";
import DiagnosticsPanel from "./DiagnosticsPanel";
import ImportPanel from "./ImportPanel";
import ObjectPanel from "./ObjectPanel";
import RelationPanel from "./RelationPanel";
import TemporalPanel from "./TemporalPanel";
import VersionPanel from "./VersionPanel";
import WorkbenchShell from "./WorkbenchShell";
import type { VersionSummary, WorkspaceOverview } from "./types";
import { initialWorkbenchStage, type WorkbenchStage } from "./workbenchModel";
import "./ontology-workbench.css";

interface OntologyWorkbenchProps {
  workspaceId: string;
}

export default function OntologyWorkbench({ workspaceId }: OntologyWorkbenchProps) {
  const [overview, setOverview] = useState<WorkspaceOverview | null>(null);
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeStage, setActiveStage] = useState<WorkbenchStage | null>(null);

  const refreshWorkspace = useCallback(async () => {
    setLoading(true);
    try {
      const [nextOverview, nextVersions] = await Promise.all([
        fetchWorkspaceOverview(workspaceId),
        fetchVersions(workspaceId),
      ]);
      setOverview(nextOverview);
      setVersions(nextVersions);
      setActiveStage((current) => current ?? initialWorkbenchStage(nextOverview.counts.objects));
    } catch (error) {
      message.error(apiErrorMessage(error, "本体包工作台加载失败"));
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void refreshWorkspace();
  }, [refreshWorkspace]);

  const handleConflict = async () => {
    message.warning("草稿已被更新，已为你刷新；请核对后重新保存");
    await refreshWorkspace();
  };

  if (loading && !overview) {
    return <Spin size="large" style={{ display: "block", margin: "96px auto" }} />;
  }

  if (!overview || !activeStage) {
    return <Empty description="无法加载本体包工作台" />;
  }

  const panels: Record<WorkbenchStage, ReactNode> = {
    import: (
      <ImportPanel
        workspaceId={workspaceId}
        revision={overview.revision}
        onChanged={refreshWorkspace}
        onConflict={handleConflict}
      />
    ),
    objects: (
      <Card className="ontology-workbench__object-card" bordered={false} loading={loading}>
        <ObjectPanel
          workspaceId={workspaceId}
          revision={overview.revision}
          objects={overview.objects}
          onChanged={refreshWorkspace}
          onConflict={handleConflict}
        />
      </Card>
    ),
    relations: (
      <RelationPanel
        workspaceId={workspaceId}
        revision={overview.revision}
        objects={overview.objects}
        relations={overview.relations}
        onChanged={refreshWorkspace}
        onConflict={handleConflict}
      />
    ),
    temporal: (
      <TemporalPanel
        workspaceId={workspaceId}
        revision={overview.revision}
        objects={overview.objects}
        policies={overview.temporalPolicies}
        onChanged={refreshWorkspace}
        onConflict={handleConflict}
      />
    ),
    diagnostics: (
      <DiagnosticsPanel
        workspaceId={workspaceId}
        revision={overview.revision}
        diagnostics={overview.diagnostics}
        dispositions={overview.dispositions}
        objects={overview.objects}
        relations={overview.relations}
        policies={overview.temporalPolicies}
        onChanged={refreshWorkspace}
        onConflict={handleConflict}
        onNavigate={(target) => setActiveStage(target)}
      />
    ),
    versions: (
      <VersionPanel
        workspaceId={workspaceId}
        revision={overview.revision}
        versions={versions}
        diagnostics={overview.diagnostics}
        dispositions={overview.dispositions}
        onChanged={refreshWorkspace}
        onConflict={handleConflict}
      />
    ),
  };

  return (
    <WorkbenchShell
      overview={overview}
      versionCount={versions.length}
      activeStage={activeStage}
      refreshing={loading}
      onStageChange={setActiveStage}
      onRefresh={() => void refreshWorkspace()}
    >
      {panels[activeStage]}
    </WorkbenchShell>
  );
}
