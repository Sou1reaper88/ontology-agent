from pathlib import Path


def test_authoring_guide_documents_interrupted_initialization_residue_handling() -> None:
    guide = Path(__file__).parents[2] / "docs" / "ontology-authoring.md"
    text = guide.read_text(encoding="utf-8")

    assert "## 11. 初始化中断后的残留处理" in text
    section = text.split("## 11. 初始化中断后的残留处理", 1)[1]
    for required in (
        ".<name>.staging-*",
        ".<name>.empty-backup-*",
        "目标目录",
        "manifest.yaml",
        "无人使用",
        "隔离目录",
        "不自动清理",
        "不应视为有效本体包",
    ):
        assert required in section
    for forbidden_command in ("rm -rf", "Remove-Item -Recurse", "rmdir /s", "del /s"):
        assert forbidden_command not in section
