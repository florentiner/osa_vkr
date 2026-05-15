"""
Convert a PDF (bytes) to a list of {"name": str, "text": str} sections.

Strategy:
  1. Extract text spans with font-size metadata via pymupdf.
  2. Identify headings as spans significantly larger than body text (or bold + short).
  3. Group body text between consecutive headings into sections.
  4. If fewer than 2 sections are found, fall back to a regex heuristic on plain text.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional


# ── Regex fallback: common academic paper heading patterns ────────────────────

_HEADING_RE = re.compile(
    r"^(?:"
    r"\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z ,:\-]{2,60}"          # 1. Introduction / 2.1 Setup
    r"|(?:Abstract|Introduction|Background|Related\s+Work"
    r"|Literature\s+Review|Method(?:ology)?s?|Approach"
    r"|Experiments?(?:\s+Setup)?|Evaluation|Results?"
    r"|Discussion|Conclusion|Future\s+Work"
    r"|Acknowledgm(?:ent)?s?|References|Appendix)"
    r"[s]?[:\s]*"
    r")$",
    re.IGNORECASE | re.MULTILINE,
)


def _sections_from_regex(text: str) -> list[dict]:
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [{"name": "Document", "text": text.strip()}]

    sections: list[dict] = []
    for i, match in enumerate(matches):
        name = match.group().strip().rstrip(":")
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if name and body:
            sections.append({"name": name, "text": body})
    return sections


# ── pymupdf-based extraction ──────────────────────────────────────────────────

def _collect_spans(pdf_bytes: bytes) -> list[dict]:
    import fitz  # pymupdf

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    spans: list[dict] = []
    for page in doc:
        blocks = page.get_text("dict")["blocks"]  # type: ignore[arg-type]
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                line_texts = []
                line_size = 0.0
                line_bold = False
                for span in line["spans"]:
                    t = span["text"]
                    if t.strip():
                        line_texts.append(t)
                        line_size = max(line_size, round(span["size"], 1))
                        line_bold = line_bold or bool(span["flags"] & (1 << 4))
                text = " ".join(line_texts).strip()
                if text:
                    spans.append({"text": text, "size": line_size, "bold": line_bold})
    doc.close()
    return spans


def _sections_from_fitz(pdf_bytes: bytes) -> list[dict]:
    spans = _collect_spans(pdf_bytes)
    if not spans:
        return []

    sizes = [s["size"] for s in spans]
    size_counts = Counter(sizes)
    body_size: float = size_counts.most_common(1)[0][0]
    heading_threshold = body_size * 1.12  # ≥12% larger than body

    def _is_heading(span: dict) -> bool:
        text = span["text"]
        if len(text) > 120:
            return False
        if span["size"] >= heading_threshold:
            return True
        if span["bold"] and len(text) <= 80 and not text.endswith(","):
            return True
        return False

    sections: list[dict] = []
    current_name: Optional[str] = None
    current_lines: list[str] = []

    for span in spans:
        if _is_heading(span):
            if current_name and current_lines:
                sections.append({"name": current_name, "text": " ".join(current_lines).strip()})
            current_name = span["text"].strip().rstrip(":")
            current_lines = []
        else:
            if current_name is not None:
                current_lines.append(span["text"])

    if current_name and current_lines:
        sections.append({"name": current_name, "text": " ".join(current_lines).strip()})

    return [s for s in sections if s["text"]]


# ── Public API ────────────────────────────────────────────────────────────────

def parse_pdf_to_sections(pdf_bytes: bytes) -> list[dict]:
    """
    Parse a PDF (raw bytes) into a list of {"name": str, "text": str}.
    Returns at least one section even if structure detection fails.
    """
    # Try font-based detection first
    sections = _sections_from_fitz(pdf_bytes)

    # If too few sections, fall back to regex on plain text
    if len(sections) < 3:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        plain = "\n".join(page.get_text("text") for page in doc)
        doc.close()
        regex_sections = _sections_from_regex(plain)
        if len(regex_sections) >= len(sections):
            sections = regex_sections

    return sections if sections else [{"name": "Document", "text": "(no text extracted)"}]