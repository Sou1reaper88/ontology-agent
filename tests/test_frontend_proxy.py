from pathlib import Path


def test_saved_prompt_requests_are_proxied_to_the_backend() -> None:
    frontend_dir = Path(__file__).resolve().parents[1] / "frontend"

    for config_name in ("vite.config.ts", "vite.config.js"):
        vite_config = (frontend_dir / config_name).read_text(encoding="utf-8")
        assert '"/prompts": "http://127.0.0.1:8001"' in vite_config
