from typing import Callable, Optional

from .checks import run_all_checks
from .claims import extract_claims, verify_claims
from .config import Config
from .github_client import get_tree
from .report import build_report

Progress = Optional[Callable[[str, float], None]]


def analyze_repo(config: Config, on_progress: Progress = None) -> dict:
    """Step 1 only: repo quality score (0-100)."""
    if on_progress:
        on_progress("Fetching repository tree...", 0.05)

    flat_paths, all_paths = get_tree(config.repo_url, config.github_token)
    checks = run_all_checks(flat_paths, all_paths, config, on_progress=on_progress)

    if on_progress:
        on_progress("Building report...", 0.97)
    return build_report(checks, config.repo_url)


def analyze_full(
    config: Config,
    paper_sections: Optional[list[dict]] = None,
    pre_extracted_claims: Optional[list[dict]] = None,
    on_progress: Progress = None,
) -> dict:
    """
    Full pipeline:
      1. Repo quality score (0-100).
      2. Extract claims from paper sections (if paper_sections provided)
         OR use pre_extracted_claims to skip extraction entirely.
      3. Verify claims against repository code.

    on_progress(message, fraction) is called at key steps.
    """
    def _prog(msg: str, pct: float) -> None:
        if on_progress:
            on_progress(msg, pct)

    # ── Step 1: repo analysis (uses progress 0.0 → 0.55) ─────────────────────
    def _repo_progress(msg: str, pct: float) -> None:
        _prog(msg, pct * 0.55)

    _prog("Fetching repository tree...", 0.02)
    flat_paths, all_paths = get_tree(config.repo_url, config.github_token)
    checks = run_all_checks(flat_paths, all_paths, config, on_progress=_repo_progress)
    report = build_report(checks, config.repo_url)

    if pre_extracted_claims is not None:
        claims = pre_extracted_claims
        _prog(f"Using {len(claims)} pre-extracted claims, skipping extraction.", 0.55)
    elif paper_sections:
        # ── Step 2: claim extraction (0.55 → 0.80) ────────────────────────────
        def _extract_progress(msg: str, pct: float) -> None:
            _prog(msg, 0.55 + pct * 0.25)

        claims = extract_claims(paper_sections, config, on_progress=_extract_progress)
    else:
        _prog("Done.", 1.0)
        return report

    # ── Step 3: claim verification (0.80 → 0.98) ─────────────────────────────
    def _verify_progress(msg: str, pct: float) -> None:
        _prog(msg, 0.80 + pct * 0.18)

    claims_result = verify_claims(claims, flat_paths, config, on_progress=_verify_progress)
    report["claims_analysis"] = claims_result

    _prog("Done.", 1.0)
    return report