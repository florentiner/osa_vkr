"""Parse PDF bytes to sections using the marker-pdf Python API with LLM support.

Uses marker.services.openai.OpenAIService pointed at OpenRouter so that the
same model/key used for claim extraction drives PDF parsing as well.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

# Prevent marker/torch from touching any GPU.
# Must be set before torch is imported (which happens inside marker).
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from markdown_it import MarkdownIt

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def is_marker_available() -> bool:
    try:
        import marker.converters.pdf  # noqa: F401
        return True
    except ImportError:
        return False


def _normalize_markdown(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def _extract_sections_from_markdown(markdown_text: str) -> list[dict[str, str]]:
    md = MarkdownIt()
    tokens = md.parse(markdown_text)
    lines = markdown_text.splitlines()

    headings: list[tuple[int, int, str]] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.type == "heading_open" and token.tag.startswith("h"):
            token_map = token.map or [0, 0]
            start_line = token_map[0]
            name = ""
            if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                name = tokens[i + 1].content.strip()
            if name:
                headings.append((start_line, int(token.tag[1:]), name))
        i += 1

    sections: list[dict[str, str]] = []
    for idx, (start_line, _level, name) in enumerate(headings):
        next_start = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        section_text = "\n".join(lines[start_line + 1: next_start]).strip()
        sections.append({"name": name, "text": section_text})

    return [s for s in sections if s["text"]]


def _markdown_from_rendered(rendered) -> str:
    """Extract markdown string from a marker RenderedDocument."""
    if hasattr(rendered, "markdown"):
        return rendered.markdown
    # Older / alternate marker builds expose text_from_rendered
    try:
        from marker.output import text_from_rendered  # type: ignore
        text, _, _ = text_from_rendered(rendered)
        return text
    except Exception:
        pass
    return str(rendered)


def _convert_with_python_api(
    pdf_path: Path,
    openrouter_key: str,
    model: str,
) -> str:
    """Run marker PdfConverter with LLM via OpenRouter and return markdown."""
    from marker.config.parser import ConfigParser  # type: ignore
    from marker.converters.pdf import PdfConverter  # type: ignore
    from marker.models import create_model_dict  # type: ignore

    config = {
        "use_llm": True,
        "llm_service": "marker.services.openai.OpenAIService",
        "openai_api_key": openrouter_key,
        "openai_model": model,
        "openai_base_url": _OPENROUTER_BASE_URL,
        "device": "cpu"
    }
    config_parser = ConfigParser(config)
    converter = PdfConverter(
        config=config_parser.generate_config_dict(),
        artifact_dict=create_model_dict(),
        llm_service=config_parser.get_llm_service(),
    )
    rendered = converter(str(pdf_path))
    return _markdown_from_rendered(rendered)


def parse_pdf_to_sections_marker(
    pdf_bytes: bytes,
    openrouter_key: Optional[str] = None,
    model: Optional[str] = None,
) -> list[dict[str, str]]:
    """Convert PDF bytes to sections via the marker Python API.

    When *openrouter_key* and *model* are provided, marker runs with
    ``use_llm=True`` using OpenRouter as the OpenAI-compatible backend.
    Without credentials, marker runs in plain (no-LLM) mode.

    Raises RuntimeError if the marker package is not installed.
    """
    if not is_marker_available():
        raise RuntimeError(
            "marker-pdf package not found. Install with: pip install marker-pdf"
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = Path(tmp_dir) / "input.pdf"
        pdf_path.write_bytes(pdf_bytes)

        if openrouter_key and model:
            md_text = _convert_with_python_api(pdf_path, openrouter_key, model)
        else:
            # Plain conversion without LLM
            from marker.config.parser import ConfigParser  # type: ignore
            from marker.converters.pdf import PdfConverter  # type: ignore
            from marker.models import create_model_dict  # type: ignore

            config_parser = ConfigParser({})
            converter = PdfConverter(
                config=config_parser.generate_config_dict(),
                artifact_dict=create_model_dict(),
            )
            rendered = converter(str(pdf_path))
            md_text = _markdown_from_rendered(rendered)

    md_text = _normalize_markdown(md_text)
    sections = _extract_sections_from_markdown(md_text)
    return sections if sections else [{"name": "Document", "text": "(no text extracted)"}]