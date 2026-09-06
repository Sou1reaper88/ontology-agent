import re
from pathlib import Path


def test_prompt_button_is_available_while_composing_a_new_request() -> None:
    chat_source = (
        Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages" / "Chat.tsx"
    ).read_text(encoding="utf-8")

    assert re.search(
        r"\{\s*activeId\s*\|\|\s*isNewDraft\s*\?\s*\(",
        chat_source,
    )
