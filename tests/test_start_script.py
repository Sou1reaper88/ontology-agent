from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_windows_start_script_uses_its_own_project_directory() -> None:
    script = (PROJECT_ROOT / "start.bat").read_text(encoding="utf-8")

    assert 'set "PROJECT_ROOT=%~dp0"' in script
    assert "D:\\projects\\ontology-agent" not in script.lower()
    assert "npm.cmd run dev -- --host 127.0.0.1 --port 5199 --strictPort" in script
