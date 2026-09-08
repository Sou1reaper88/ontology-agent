import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Button, Empty, Spin, message } from "antd";
import { useSearchParams } from "react-router-dom";
import { apiErrorMessage, fetchVersions, fetchWorkspaceOverview } from "./api";
import DiagnosticsPanel from "./DiagnosticsPanel";
import ImportPanel from "./ImportPanel";
import ObjectDetailPanel from "./ObjectDetailPanel";
import ObjectPanel from "./ObjectPanel";
import RelationPanel from "./RelationPanel";
import TemporalPanel from "./TemporalPanel";
import VersionPanel from "./VersionPanel";
import WorkbenchShell from "./WorkbenchShell";
import type { VersionSummary, WorkspaceOverview } from "./types";
import { selectedOntologyObject, withSelectedObject } from "./objectNavigation";
import { initialWorkbenchStage, type WorkbenchStage } from "./workbenchModel";
import "./object-detail.css";
import "./ontology-workbench.css";

interface OntologyWorkbenchProps {
  workspaceId: string;
}

export default function OntologyWorkbench({ workspaceId }: OntologyWorkbenchProps) {
  const [overview, setOverview] = useState<WorkspaceOverview | null>(null);
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeStage, setActiveStage] = useState<WorkbenchStage | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

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

  const requestedObjectId = searchParams.get("object");
  const selectedObject = selectedOntologyObject(overview.objects, requestedObjectId);
  const selectObject = (objectId: string | null, replace = false) => {
    setSearchParams(withSelectedObject(searchParams, objectId), { replace });
  };

  const objectContent = selectedObject ? (
    <ObjectDetailPanel
      workspaceId={workspaceId}
      revision={overview.revision}
      object={selectedObject}
      onChanged={refreshWorkspace}
      onConflict={handleConflict}
      onBack={() => selectObject(null, true)}
    />
  ) : requestedObjectId ? (
    <section className="ontology-object-invalid">
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="对象已不存在或当前链接已经失效"
      >
        <Button type="primary" onClick={() => selectObject(null, true)}>
          返回对象列表
        </Button>
      </Empty>
    </section>
  ) : (
    <ObjectPanel objects={overview.objects} onSelectObject={(objectId) => selectObject(objectId)} />
  );

  const panels: Record<WorkbenchStage, ReactNode> = {
    import: (
      <ImportPanel
        workspaceId={workspaceId}
        revision={overview.revision}
        onChanged={refreshWorkspace}
        onConflict={handleConflict}
      />
    ),
    objects: objectContent,
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
        objects={overview.objects}
        policies={overview.temporalPolicies}
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
        onNavigate={(target) => {
          if (target === "objects") selectObject(null, true);
          setActiveStage(target);
        }}
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
