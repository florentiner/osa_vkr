"""Streamlit UI for the GitHub Repository Analyzer."""
import json
import os
from pathlib import Path

# Load .env from project root before anything else
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

import streamlit as st

from repo_analyzer import Config, analyze_full
from repo_analyzer.pdf_parser import parse_pdf_to_sections
from repo_analyzer.pdf_parser_marker import is_marker_available, parse_pdf_to_sections_marker
from repo_analyzer.report import build_text_report

st.set_page_config(
    page_title="Student reports analysis",
    page_icon="🔍",
    layout="wide",
)

st.title("Student reports analysis")
st.caption("Evaluates thesis project repositories on a 0–100 scale and verifies paper claims.")

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Repository")
    repo_url = st.text_input(
        "GitHub URL",
        placeholder="https://github.com/owner/repo",
    )

    st.header("Paper")
    st.caption("Upload a PDF, pre-parsed sections JSON, or pre-extracted claims JSON to enable claim verification.")
    paper_file = st.file_uploader("Article", type=["pdf", "json"])

    st.header("API Keys")
    openrouter_key = st.text_input(
        "OpenRouter API Key",
        type="password",
        value=os.environ.get("OPENROUTER_KEY", ""),
    )
    github_token = st.text_input(
        "GitHub Token (optional)",
        type="password",
        value=os.environ.get("GITHUB_TOKEN", ""),
        help="Needed for private repos or to avoid rate limits.",
    )

    st.header("Model")
    model = st.selectbox(
        "Model",
        options=[
            "openai/gpt-4o-mini",
            "openai/gpt-4o",
            "deepseek/deepseek-v3",
            "anthropic/claude-3.5-haiku",
            "anthropic/claude-3.5-sonnet",
        ],
        label_visibility="collapsed",
    )

    analyze_btn = st.button(
        "Analyze",
        type="primary",
        disabled=not (repo_url and openrouter_key),
        use_container_width=True,
    )

# ── Main placeholder ──────────────────────────────────────────────────────────

if not analyze_btn:
    st.info(
        "Fill in the repository URL and OpenRouter API key, then click **Analyze**.\n\n"
        "Optionally upload a PDF article to verify which claims from the paper are implemented in the code."
    )
    st.stop()

# ── Parse paper ───────────────────────────────────────────────────────────────

paper_sections = None
pre_extracted_claims = None

if paper_file is not None:
    if paper_file.name.endswith(".pdf"):
        with st.spinner("Parsing PDF…"):
            try:
                pdf_bytes = paper_file.read()
                if is_marker_available():
                    try:
                        paper_sections = parse_pdf_to_sections_marker(
                            pdf_bytes,
                            openrouter_key=openrouter_key or None,
                            model=model or None,
                        )
                        parser_used = "marker"
                    except Exception as marker_err:
                        st.warning(f"marker failed ({marker_err}), falling back to pymupdf.")
                        paper_sections = parse_pdf_to_sections(pdf_bytes)
                        parser_used = "pymupdf"
                else:
                    paper_sections = parse_pdf_to_sections(pdf_bytes)
                    parser_used = "pymupdf"
                st.success(f"Parsed {len(paper_sections)} sections from PDF (via {parser_used}).")
            except Exception as e:
                st.error(f"PDF parsing failed: {e}")
                st.stop()
    else:
        try:
            data = json.loads(paper_file.read().decode("utf-8"))
        except Exception as e:
            st.error(f"Could not parse JSON: {e}")
            st.stop()

        # Detect claims JSON: {"result": [...], "meta": {...}} or a bare list of claim dicts
        if isinstance(data, dict) and "result" in data and isinstance(data["result"], list):
            pre_extracted_claims = data["result"]
            st.success(f"Loaded {len(pre_extracted_claims)} pre-extracted claims — skipping PDF parsing.")
        elif isinstance(data, list) and data and "claim" in data[0]:
            pre_extracted_claims = data
            st.success(f"Loaded {len(pre_extracted_claims)} pre-extracted claims — skipping PDF parsing.")
        else:
            paper_sections = data
            st.success(f"Loaded sections JSON.")

# ── Run analysis ──────────────────────────────────────────────────────────────

config = Config(
    repo_url=repo_url,
    openrouter_key=openrouter_key,
    github_token=github_token or None,
    model=model,
)

progress_bar = st.progress(0.0)
status = st.empty()


def on_progress(msg: str, pct: float) -> None:
    progress_bar.progress(min(pct, 1.0))
    status.text(msg)


try:
    report = analyze_full(
        config,
        paper_sections=paper_sections,
        pre_extracted_claims=pre_extracted_claims,
        on_progress=on_progress,
    )
except Exception as e:
    progress_bar.empty()
    status.empty()
    st.error(f"Analysis failed: {e}")
    st.stop()

progress_bar.progress(1.0)
status.empty()
progress_bar.empty()

# ── Score ─────────────────────────────────────────────────────────────────────

score = report["summary"]["score"]
breakdown = report["summary"]["score_breakdown"]
repo_type = report["summary"]["repo_type"]

col_score, col_meta = st.columns([1, 3])
with col_score:
    color = "green" if score >= 70 else "orange" if score >= 40 else "red"
    st.markdown(
        f"<div style='text-align:center;padding:20px'>"
        f"<span style='font-size:72px;font-weight:bold;color:{color}'>{score}</span>"
        f"<span style='font-size:24px;color:gray'>/100</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
with col_meta:
    st.markdown(f"**Repository:** {repo_url}")
    st.markdown(f"**Type:** {repo_type.replace('_', ' ').title()}")
    st.markdown(f"**Analyzed:** {report['analyzed_at']}")

st.divider()

# ── Repository checks ─────────────────────────────────────────────────────────

st.subheader("Repository Checks")

CHECK_LABELS = {
    "readme": "README",
    "license": "License",
    "commits": "Commits (>5)",
    "execution_files": "Entry-point files",
    "requirements": "Requirements file",
    "tests": "Tests",
    "data_files": "Data files",
    "experiment_scripts": "Experiment scripts",
}

checks = report["checks"]
applicable_checks = [
    (key, label)
    for key, label in CHECK_LABELS.items()
    if breakdown.get(key, {}).get("applicable") is not False
]

cols = st.columns(min(len(applicable_checks), 4))
for i, (key, label) in enumerate(applicable_checks):
    bd = breakdown.get(key, {})
    passed = bd.get("passed", False)
    weight = bd.get("weight", 0)
    earned = bd.get("earned", 0)
    icon = "✅" if passed else "❌"
    with cols[i % len(cols)]:
        st.metric(label=f"{icon} {label}", value=f"{earned}/{weight} pts")

st.divider()

# ── Code quality ──────────────────────────────────────────────────────────────

st.subheader("Code Quality (informational)")
col1, col2 = st.columns(2)
with col1:
    syntax = report["summary"]["syntax"]
    ok = syntax.get("ok")
    if ok is True:
        st.success(f"Syntax: {syntax.get('summary', 'ok')}")
    elif ok is False:
        st.error(f"Syntax errors: {syntax.get('summary', '')}")
        for err in syntax.get("errors", [])[:5]:
            st.code(err, language=None)
    else:
        st.warning(f"Syntax: {syntax.get('summary', 'unavailable')}")
with col2:
    docs = report["summary"]["docstrings"]
    pct = docs.get("coverage_pct")
    if pct is not None:
        st.metric("Docstring coverage", f"{pct}%", help=docs.get("summary", ""))
    else:
        st.warning(f"Docstrings: {docs.get('summary', 'unavailable')}")

# ── Claims analysis ───────────────────────────────────────────────────────────

if "claims_analysis" in report:
    st.divider()
    ca = report["claims_analysis"]
    stats = ca["stats"]
    rate_pct = stats["implementation_rate_pct"]

    st.subheader("Claims Analysis")

    c1, c2, c3 = st.columns(3)
    c1.metric("Total claims", stats["total"])
    c2.metric("Implemented", f"{stats['implemented']} / {stats['total']}")
    rate_color = "green" if rate_pct >= 70 else "orange" if rate_pct >= 40 else "red"
    c3.markdown(
        f"<div style='text-align:center'>"
        f"<div style='font-size:13px;color:gray;margin-bottom:4px'>Implementation rate</div>"
        f"<span style='font-size:40px;font-weight:bold;color:{rate_color}'>{rate_pct}%</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("#### Claims")
    for claim in ca["claims"]:
        impl = claim.get("implementation", {})
        done = impl.get("implemented", False)
        conf = impl.get("confidence", "")
        evidence = impl.get("evidence_file") or ""
        explanation = impl.get("explanation", "")
        icon = "✅" if done else "❌"
        cat = claim.get("category", "")
        val = claim.get("value")

        with st.expander(f"{icon} {claim.get('claim', '')}"):
            cols2 = st.columns([2, 2])
            with cols2[0]:
                st.markdown(f"**Category:** `{cat}`")
                if val:
                    st.markdown(f"**Value:** `{val}`")
                st.markdown(f"**Verifiability:** {claim.get('verifiability', '')}")
            with cols2[1]:
                st.markdown(f"**Confidence:** {conf}")
                if evidence:
                    st.markdown(f"**File:** `{evidence}`")
            if claim.get("original_text"):
                st.markdown(f"*\"{claim['original_text']}\"*")
            if explanation:
                st.info(explanation)
            if claim.get("contradiction"):
                st.warning("⚠️ Contradicts another claim in the paper")

st.divider()

# ── Exports ───────────────────────────────────────────────────────────────────

col_dl1, col_dl2 = st.columns(2)
with col_dl1:
    with st.expander("Text report"):
        st.code(build_text_report(report), language=None)
with col_dl2:
    st.download_button(
        "Download JSON report",
        data=json.dumps(report, ensure_ascii=False, indent=2),
        file_name="report.json",
        mime="application/json",
    )