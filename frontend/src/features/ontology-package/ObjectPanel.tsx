import { Empty, Input, Tag } from "antd";
import { RightOutlined } from "@ant-design/icons";
import { useMemo, useState } from "react";
import { filterOntologyObjects } from "./objectNavigation";
import type { DraftObject } from "./types";

interface ObjectPanelProps {
  objects: DraftObject[];
  onSelectObject: (objectId: string) => void;
}

export default function ObjectPanel({ objects, onSelectObject }: ObjectPanelProps) {
  const [query, setQuery] = useState("");
  const visibleObjects = useMemo(
    () => filterOntologyObjects(objects, query),
    [objects, query]
  );
  const fieldCount = objects.reduce((total, item) => total + item.fields.length, 0);

  return (
    <section className="ontology-object-directory" id="object-editor">
      <div className="ontology-object-directory__toolbar">
        <div>
          <span>语义对象目录</span>
          <strong>
            {objects.length} 个对象 · {fieldCount} 个字段
          </strong>
        </div>
        <Input.Search
          allowClear
          placeholder="搜索中文名、物理表名或描述"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="搜索本体对象"
        />
      </div>

      {visibleObjects.length ? (
        <div className="ontology-object-directory__list">
          {visibleObjects.map((item) => (
            <button
              type="button"
              className="ontology-object-directory__item"
              key={item.id}
              onClick={() => onSelectObject(item.id)}
            >
              <span className="ontology-object-directory__index tabular-nums">
                {String(objects.indexOf(item) + 1).padStart(2, "0")}
              </span>
              <span className="ontology-object-directory__identity">
                <strong>{item.label || item.physicalName}</strong>
                <code>{item.physicalName}</code>
              </span>
              <span className="ontology-object-directory__description">
                {item.description || "尚未填写对象描述"}
              </span>
              <span className="ontology-object-directory__meta">
                <Tag bordered={false} color={item.status === "active" ? "green" : "default"}>
                  {item.status === "active" ? "启用" : "停用"}
                </Tag>
                <span className="tabular-nums">{item.fields.length} 个字段</span>
              </span>
              <RightOutlined className="ontology-object-directory__arrow" />
            </button>
          ))}
        </div>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={objects.length ? "没有匹配的对象" : "尚无对象，请先导入元数据"}
        />
      )}
    </section>
  );
}
