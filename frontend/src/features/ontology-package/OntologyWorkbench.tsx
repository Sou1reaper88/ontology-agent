import { useCallback, useEffect, useState } from "react";
import { Alert, Card, Col, Empty, Row, Spin, Statistic, Tag, Typography, message } from "antd";
import { apiErrorMessage, fetchVersions, fetchWorkspaceOverview } from "./api";
import DiagnosticsPanel from "./DiagnosticsPanel";
import ImportPanel from "./ImportPanel";
import ObjectPanel from "./ObjectPanel";
import RelationPanel from "./RelationPanel";
import TemporalPanel from "./TemporalPanel";
import VersionPanel from "./VersionPanel";
import type { VersionSummary, WorkspaceOverview } from "./types";

interface OntologyWorkbenchProps {
  workspaceId: string;
}

export default function OntologyWorkbench({ workspaceId }: OntologyWorkbenchProps) {
  const [overview, setOverview] = useState<WorkspaceOverview | null>(null);
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const refreshWorkspace = useCallback(async () => {
    setLoading(true);
    try {
      const [nextOverview, nextVersions] = await Promise.all([
        fetchWorkspaceOverview(workspaceId),
        fetchVersions(workspaceId),
      ]);
      setOverview(nextOverview);
      setVersions(nextVersions);
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

  const navigateToEditor = (target: "objects" | "relations" | "temporal") => {
    const id = { objects: "object-editor", relations: "relation-editor", temporal: "temporal-editor" }[target];
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  if (loading && !overview) {
    return <Spin size="large" style={{ display: "block", margin: "96px auto" }} />;
  }

  if (!overview) {
    return <Empty description="无法加载本体包工作台" />;
  }

  const { counts } = overview;
  return (
    <div style={{ maxWidth: 1440, margin: "0 auto", padding: "8px 0 28px" }}>
      <Card bordered={false} style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]} align="middle">
          <Col flex="auto">
            <Typography.Title level={2} style={{ margin: 0 }}>
              本体包工作台
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: "8px 0 0" }}>
              {overview.displayName}
            </Typography.Paragraph>
          </Col>
          <Col>
            <Tag color="green">活动版本：{overview.activeVersion?.version ?? "未发布"}</Tag>
          </Col>
          <Col>
            <Tag color="blue">草稿修订：{overview.revision}</Tag>
          </Col>
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: 18 }}>
          <Col xs={12} md={6}><Statistic title="对象" value={counts.objects} /></Col>
          <Col xs={12} md={6}><Statistic title="字段" value={counts.fields} /></Col>
          <Col xs={12} md={6}><Statistic title="关系" value={counts.relations} /></Col>
          <Col xs={12} md={6}><Statistic title="时间策略" value={counts.temporalPolicies} /></Col>
        </Row>
      </Card>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="兼容说明"
        description="旧版 MySQL 元数据 API 仍保持兼容，但不再驱动 RDF 发布。"
      />

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={8}>
          <ImportPanel
            workspaceId={workspaceId}
            revision={overview.revision}
            onChanged={refreshWorkspace}
            onConflict={handleConflict}
          />
        </Col>
        <Col xs={24} xl={16}>
          <Card title="对象与字段" bordered={false} loading={loading}>
            <ObjectPanel
              workspaceId={workspaceId}
              revision={overview.revision}
              objects={overview.objects}
              onChanged={refreshWorkspace}
              onConflict={handleConflict}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={12}>
          <RelationPanel
            workspaceId={workspaceId}
            revision={overview.revision}
            objects={overview.objects}
            relations={overview.relations}
            onChanged={refreshWorkspace}
            onConflict={handleConflict}
          />
        </Col>
        <Col xs={24} xl={12}>
          <TemporalPanel
            workspaceId={workspaceId}
            revision={overview.revision}
            objects={overview.objects}
            policies={overview.temporalPolicies}
            onChanged={refreshWorkspace}
            onConflict={handleConflict}
          />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={10}>
          <DiagnosticsPanel
            workspaceId={workspaceId}
            revision={overview.revision}
            diagnostics={overview.diagnostics}
            dispositions={overview.dispositions}
            objects={overview.objects}
            onChanged={refreshWorkspace}
            onConflict={handleConflict}
            onNavigate={navigateToEditor}
          />
        </Col>
        <Col xs={24} xl={14}>
          <VersionPanel
            workspaceId={workspaceId}
            revision={overview.revision}
            versions={versions}
            diagnostics={overview.diagnostics}
            dispositions={overview.dispositions}
            onChanged={refreshWorkspace}
            onConflict={handleConflict}
          />
        </Col>
      </Row>
    </div>
  );
}
